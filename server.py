#!/usr/bin/env python3
"""SortSmart — AI waste-sorting assistant for India.
Supports Ollama (local), Groq, and Anthropic Claude as AI providers.
Includes HTTP Basic Auth (set APP_PASSWORD env var to protect the app).
"""

import argparse
import base64
import functools
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from scrapuncle_data import SCRAP_CATEGORIES
import uuid

# Load .env FIRST so provider/key env vars are available before anything else
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"), override=True)

try:
    from flask import Flask, jsonify, render_template, request, send_from_directory, Response, session
    from werkzeug.exceptions import RequestEntityTooLarge
except ImportError as exc:
    raise SystemExit(
        "Web dependencies are missing. Run: python -m pip install -r requirements.txt"
    ) from exc

# ---------------------------------------------------------------------------
# Provider selection — now dotenv is already loaded so env vars are correct
#
# Smart dual-provider mode:
#   SORTSMART_PROVIDER=ollama  → Ollama/LLaVA for PHOTO, Groq for DESCRIPTION
#   This gives best of both: free local vision + multilingual text (Hindi/Punjabi)
# ---------------------------------------------------------------------------
_provider_env = os.environ.get("SORTSMART_PROVIDER", "").strip().lower()

if _provider_env == "ollama":
    from sortsmart_ollama import analyze, active_provider_name  # type: ignore
    try:
        from sortsmart import analyze_description as groq_analyze_description
        analyze_description = groq_analyze_description
        _TEXT_PROVIDER = "groq"
    except Exception:
        from sortsmart_ollama import analyze_description  # type: ignore
        _TEXT_PROVIDER = "ollama"
    VISION_SUPPORTED = True
elif _provider_env == "anthropic" or (_provider_env != "groq" and os.environ.get("ANTHROPIC_API_KEY")):
    from sortsmart_claude import analyze, analyze_description, active_provider_name  # type: ignore
    _TEXT_PROVIDER = "anthropic"
    VISION_SUPPORTED = True
else:
    from sortsmart import analyze, analyze_description  # type: ignore[assignment]
    def active_provider_name():  # type: ignore[misc]
        return "Groq (text-only)"
    _TEXT_PROVIDER = "groq"
    VISION_SUPPORTED = False


MAX_UPLOAD_BYTES = 16 * 1024 * 1024  # 16 MB — supports high-res phone photos
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 128 * 1024
MAX_DESCRIPTION_LENGTH = 300
ALLOWED_MEDIA_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}
SUPPORTED_LANGUAGES = {"English", "Hindi", "Punjabi"}
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "sortsmart-secret-key-2026-prod")

USERS_FILE = Path(__file__).with_name("users.json")

def _load_users():
    if not USERS_FILE.exists():
        return {
            "admin": {
                "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
                "role": "admin",
                "name": "Administrator",
                "points": 250
            },
            "user": {
                "password_hash": hashlib.sha256("user123".encode()).hexdigest(),
                "role": "user",
                "name": "Eco Sorter",
                "points": 50
            }
        }
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_users(users_dict):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_dict, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Security — HTTP Basic Auth + Rate Limiting + Security Headers
# ---------------------------------------------------------------------------
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
_APP_USERNAME = os.environ.get("APP_USERNAME", "sortsmart").strip()

# Simple in-memory rate limiter: max 30 requests/min per IP
_rate_store: dict = defaultdict(list)
RATE_LIMIT = 30
RATE_WINDOW = 60  # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    timestamps = _rate_store[ip]
    # Remove old entries outside the window
    _rate_store[ip] = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True


def _get_current_user():
    """Return authenticated user dict or None."""
    username = session.get("username")
    if username:
        users = _load_users()
        if username in users:
            u = dict(users[username])
            u["username"] = username
            return u
    # Check HTTP Basic Auth as fallback
    auth = request.authorization
    if auth:
        users = _load_users()
        if auth.username in users:
            target_hash = users[auth.username].get("password_hash")
            req_hash = hashlib.sha256(auth.password.encode()).hexdigest()
            if target_hash and req_hash == target_hash:
                u = dict(users[auth.username])
                u["username"] = auth.username
                return u
    return None

def _check_auth(req) -> bool:
    return _get_current_user() is not None

def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _check_auth(request):
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required. Please sign in.", require_auth=True), 401
            return render_template("index.html")  # Index will display login modal if not logged in
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        u = _get_current_user()
        if not u or u.get("role") != "admin":
            return jsonify(error="Admin privileges required."), 403
        return f(*args, **kwargs)
    return decorated


@app.after_request
def add_security_headers(response):
    """Add security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), microphone=(self), camera=(self)"
    # Allow V2 (SortSmartV2 on port 3000) and mobile devices on LAN to call this API
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    # Strict CSP — allow self + CDN for Leaflet map
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com 'unsafe-inline'; "
        "style-src 'self' https://unpkg.com 'unsafe-inline'; "
        "img-src 'self' data: https://*.tile.openstreetmap.org; "
        "connect-src 'self' https://nominatim.openstreetmap.org https://overpass-api.de "
        "https://overpass.kumi.systems https://maps.mail.ru;"
    )
    return response


@app.get("/api/status")
def api_status():
    """Return the active AI provider name. Useful for health checks (no auth)."""
    return jsonify(provider=active_provider_name(), vision=VISION_SUPPORTED)


@app.get("/api/auth/current")
def auth_current_user():
    """Return currently logged-in user profile or None."""
    user = _get_current_user()
    if not user:
        return jsonify(authenticated=False, user=None)
    # Exclude password_hash
    safe_user = {k: v for k, v in user.items() if k != "password_hash"}
    return jsonify(authenticated=True, user=safe_user)


@app.post("/api/auth/login")
def auth_login():
    """Authenticate user with username and password."""
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(error="Username and password are required."), 400

    users = _load_users()
    if username not in users:
        return jsonify(error="Invalid username or password."), 401

    expected_hash = users[username].get("password_hash")
    input_hash = hashlib.sha256(password.encode()).hexdigest()
    if input_hash != expected_hash:
        return jsonify(error="Invalid username or password."), 401

    session["username"] = username
    user_info = {k: v for k, v in users[username].items() if k != "password_hash"}
    user_info["username"] = username
    return jsonify(success=True, user=user_info)


@app.post("/api/auth/logout")
def auth_logout():
    """Log out current user."""
    session.pop("username", None)
    return jsonify(success=True)


@app.post("/api/auth/points")
def auth_update_points():
    """Update points for the logged-in user."""
    user = _get_current_user()
    if not user:
        return jsonify(error="Not logged in"), 401
    data = request.get_json(silent=True) or {}
    points_delta = int(data.get("delta", 0))
    users = _load_users()
    uname = user["username"]
    if uname in users:
        users[uname]["points"] = max(0, users[uname].get("points", 0) + points_delta)
        _save_users(users)
        return jsonify(success=True, new_points=users[uname]["points"])
    return jsonify(error="User record missing"), 404


@app.get("/api/admin/users")
@require_admin
def admin_get_users():
    """Admin only: list all users."""
    users = _load_users()
    safe_list = []
    for uname, udata in users.items():
        safe_list.append({
            "username": uname,
            "role": udata.get("role", "user"),
            "name": udata.get("name", uname),
            "points": udata.get("points", 0)
        })
    return jsonify(users=safe_list)


@app.post("/api/admin/users")
@require_admin
def admin_create_user():
    """Admin only: create or update a user."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    role = data.get("role", "user")
    name = data.get("name", username)
    if not username or not password:
        return jsonify(error="Username and password are required."), 400
    if role not in ("admin", "user"):
        return jsonify(error="Role must be admin or user."), 400

    users = _load_users()
    users[username] = {
        "password_hash": hashlib.sha256(password.encode()).hexdigest(),
        "role": role,
        "name": name,
        "points": int(data.get("points", 0))
    }
    _save_users(users)
    return jsonify(success=True, message=f"User {username} saved successfully.")


@app.get("/api/ollama-status")
@require_auth
def ollama_status_endpoint():
    """Return Ollama health, available models, and vision model info."""
    try:
        from sortsmart_ollama import ollama_status
        return jsonify(ollama_status())
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.get("/data/<path:filename>")
def serve_data(filename):
    return send_from_directory("data", filename)


@app.get("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js")


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    return jsonify(error="Choose an image smaller than 16 MB."), 413



PICKUPS_FILE = Path(__file__).with_name("pickups.json")

def _load_pickups():
    if not PICKUPS_FILE.exists():
        return []
    try:
        with open(PICKUPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_pickups(pickups_list):
    try:
        with open(PICKUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(pickups_list, f, indent=2)
    except Exception:
        pass


@app.get("/api/scrapuncle/rates")
def scrapuncle_rates():
    """Return live scrap rates & categories (ScrapUncle integration)."""
    return jsonify(categories=SCRAP_CATEGORIES)


@app.post("/api/scrapuncle/estimate")
def scrapuncle_estimate():
    """Calculate total payout and estimated carbon offset for selected items."""
    data = request.get_json(silent=True) or {}
    items = data.get("items", []) # list of {id, qty}
    
    # Flatten items lookup
    lookup = {}
    for cat in SCRAP_CATEGORIES.values():
        for item in cat["items"]:
            lookup[item["id"]] = item
            
    total_val = 0.0
    total_weight = 0.0
    breakdown = []
    
    for user_item in items:
        item_id = user_item.get("id")
        qty = float(user_item.get("qty", 0))
        if item_id in lookup and qty > 0:
            rate = lookup[item_id]["rate"]
            unit = lookup[item_id]["unit"]
            subtotal = rate * qty
            total_val += subtotal
            if unit == "kg":
                total_weight += qty
            else:
                total_weight += qty * 15.0 # approximate kg per appliance
            breakdown.append({
                "name": lookup[item_id]["name"],
                "rate": rate,
                "unit": unit,
                "qty": qty,
                "subtotal": round(subtotal, 2)
            })
            
    co2_saved = round(total_weight * 1.85, 2)
    eco_points_earned = int(total_weight * 2)
    
    return jsonify(
        total_payout=round(total_val, 2),
        estimated_weight_kg=round(total_weight, 2),
        co2_saved_kg=co2_saved,
        eco_points_earned=eco_points_earned,
        breakdown=breakdown
    )


@app.get("/api/scrapuncle/pickups")
def get_pickups():
    """List pickups for the user (or all if admin)."""
    user = _get_current_user()
    pickups = _load_pickups()
    if not user:
        return jsonify(pickups=[p for p in pickups if p.get("guest") == True][-5:])
    if user.get("role") == "admin":
        return jsonify(pickups=pickups)
    return jsonify(pickups=[p for p in pickups if p.get("username") == user.get("username")])


@app.post("/api/scrapuncle/book-pickup")
def book_pickup():
    """Schedule a doorstep scrap pickup."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    address = (data.get("address") or "").strip()
    city = (data.get("city") or "Delhi NCR").strip()
    pincode = (data.get("pincode") or "").strip()
    date = (data.get("date") or "").strip()
    slot = (data.get("slot") or "10:00 AM - 01:00 PM").strip()
    estimated_payout = float(data.get("estimated_payout", 0))
    items_summary = data.get("items_summary", "Household Scrap")
    payment_mode = (data.get("payment_mode") or "UPI").strip()
    upi_id = (data.get("upi_id") or "").strip()

    if not name or not phone or not address:
        return jsonify(error="Name, phone number, and pickup address are required."), 400

    user = _get_current_user()
    booking_id = f"SU-{int(time.time())%1000000:06d}"
    
    new_booking = {
        "id": booking_id,
        "name": name,
        "phone": phone,
        "address": address,
        "city": city,
        "pincode": pincode,
        "date": date or time.strftime("%Y-%m-%d"),
        "slot": slot,
        "items": items_summary,
        "estimated_payout": estimated_payout,
        "payment_mode": payment_mode,
        "upi_id": upi_id,
        "status": "Scheduled",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "guest": user is None,
        "username": user.get("username") if user else None
    }
    
    pickups = _load_pickups()
    pickups.insert(0, new_booking)
    _save_pickups(pickups)

    # Award bonus eco points if user logged in
    if user:
        users = _load_users()
        uname = user["username"]
        if uname in users:
            users[uname]["points"] = users[uname].get("points", 0) + 25
            _save_users(users)

        return jsonify(
        success=True,
        booking=new_booking,
        message=f"Pickup scheduled successfully! Executive will arrive on {new_booking['date']} ({slot})."
    )


@app.post("/api/scrapuncle/cancel-pickup")
def cancel_pickup():
    """Cancel or update a pickup request status dynamically."""
    data = request.get_json(silent=True) or {}
    booking_id = (data.get("booking_id") or "").strip()
    if not booking_id:
        return jsonify(error="Booking ID is required."), 400

    pickups = _load_pickups()
    found = False
    for p in pickups:
        if p.get("id") == booking_id:
            p["status"] = "Cancelled"
            found = True
            break

    if not found:
        return jsonify(error="Booking not found."), 404

    _save_pickups(pickups)
    return jsonify(success=True, message=f"Pickup {booking_id} has been cancelled.")


@app.post("/api/analyze")
def analyze_image():
    # Rate limiting
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify(error="Too many requests. Please wait a moment and try again."), 429

    image = request.files.get("image")
    if image is not None and not image.filename:
        image = None
    description = request.form.get("description", "").strip()
    if bool(image) == bool(description):
        return jsonify(error="Choose a photo or enter a description, not both."), 400

    language = request.form.get("language", "English").strip()
    if language not in SUPPORTED_LANGUAGES:
        return jsonify(error="Choose English, Hindi, or Punjabi."), 400

    if image is not None:
        media_type = (image.mimetype or "").lower()
        if media_type not in ALLOWED_MEDIA_TYPES:
            return jsonify(error="Use a JPEG, PNG, GIF, or WebP image."), 415

        # Block photo uploads when vision is not supported by the active provider
        if not VISION_SUPPORTED:
            return jsonify(error=(
                "📷 Photo mode is not supported by the current provider (Groq is text-only). "
                "Set SORTSMART_PROVIDER=ollama or add ANTHROPIC_API_KEY to enable photo mode."
            )), 400

        image_bytes = image.read()
        if not image_bytes:
            return jsonify(error="The selected image is empty."), 400
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            return jsonify(error="Choose an image smaller than 16 MB."), 413
        analyze_request = lambda: analyze(image_bytes, media_type, lang=language)
    else:
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return jsonify(error="Description must be 300 characters or fewer."), 400
        analyze_request = lambda: analyze_description(description, lang=language)

    try:
        result = analyze_request()
    except (RuntimeError, ValueError) as exc:
        return jsonify(error=str(exc)), 502

    return jsonify(result)


def _distance_km(lat1, lon1, lat2, lon2):
    radius_km = 6371
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(lon2 - lon1)
    distance = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(min(1, math.sqrt(distance)))


@app.get("/api/dropoffs")
@require_auth
def nearby_dropoffs():
    try:
        latitude = float(request.args["lat"])
        longitude = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify(error="A valid latitude and longitude are required."), 400
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return jsonify(error="A valid latitude and longitude are required."), 400

    query = (
        "[out:json][timeout:12];"
        f"(node(around:5000,{latitude},{longitude})[amenity=recycling];"
        f"way(around:5000,{latitude},{longitude})[amenity=recycling];"
        f"relation(around:5000,{latitude},{longitude})[amenity=recycling];);"
        "out center tags;"
    )
    post_data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "SortSmart/1.0 (nearby recycling lookup)",
    }

    data = None
    for mirror in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(
                mirror, data=post_data, headers=post_headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=14) as response:
                data = json.loads(response.read())
            if isinstance(data, dict) and isinstance(data.get("elements"), list):
                break  # success
            data = None
        except Exception:
            data = None
            continue

    # If all mirrors failed, return soft fallback: empty list + google maps link
    if data is None:
        gmaps = f"https://www.google.com/maps/search/recycling+near/@{latitude},{longitude},14z"
        return jsonify(
            places=[],
            radius_km=5,
            fallback=True,
            gmaps_url=gmaps,
            message=(
                "OpenStreetMap recycling data is currently unavailable. "
                "Try searching Google Maps for recycling points near you."
            ),
        )

    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        return jsonify(places=[], radius_km=5, fallback=True,
                       message="Recycling data returned an unexpected response.")

    places = _format_dropoffs(data["elements"], latitude, longitude)
    places.sort(key=lambda place: place["distance_km"])
    return jsonify(places=places[:10], radius_km=5, fallback=False)


def _format_dropoffs(elements, latitude, longitude):
    places = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}
        point = element.get("center", element)
        if not isinstance(point, dict):
            continue
        try:
            place_lat = float(point["lat"])
            place_lon = float(point["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not math.isfinite(place_lat)
            or not math.isfinite(place_lon)
            or not -90 <= place_lat <= 90
            or not -180 <= place_lon <= 180
        ):
            continue
        places.append(
            {
                "name": tags.get("name") or "Recycling point",
                "latitude": place_lat,
                "longitude": place_lon,
                "distance_km": round(
                    _distance_km(latitude, longitude, place_lat, place_lon), 2
                ),
                "details": tags.get("recycling_type") or tags.get("recycling") or "",
                "osm_url": (
                    "https://www.openstreetmap.org/"
                    f"?mlat={place_lat}&mlon={place_lon}#map=17/{place_lat}/{place_lon}"
                ),
            }
        )
    return places


@app.get("/api/geocode")
@require_auth
def geocode_area():
    query = request.args.get("q", "").strip()
    if not query or len(query) > 120:
        return jsonify(error="Enter an area name of 1 to 120 characters."), 400

    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1}
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SortSmart/1.0 (area lookup)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            results = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return jsonify(error="Area search is unavailable right now. Try again later."), 502

    if not isinstance(results, list):
        return jsonify(error="Area search returned an invalid response."), 502
    if not results:
        return jsonify(error="That area could not be found. Try a nearby city or postal code."), 404
    try:
        latitude = float(results[0]["lat"])
        longitude = float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Area search returned an invalid location."), 502
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return jsonify(error="Area search returned an invalid location."), 502
    return jsonify(latitude=latitude, longitude=longitude)


def main():
    parser = argparse.ArgumentParser(description="Run the SortSmart phone web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
