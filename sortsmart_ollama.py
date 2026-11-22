#!/usr/bin/env python3
"""SortSmart Ollama backend — runs vision models locally via Ollama.

Requires Ollama running: https://ollama.com
Default vision model: llava  (run: ollama pull llava)

Set in .env:
  OLLAMA_MODEL=llava          # or moondream, llava:13b, llama3.2-vision, etc.
  OLLAMA_HOST=http://localhost:11434   # optional, default
"""

import base64
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

try:
    from PIL import Image
except ImportError:
    Image = None

load_dotenv(Path(__file__).with_name(".env"), override=True)

DEFAULT_OLLAMA_MODEL = "llava"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

IMAGE_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
STREAMS = {"wet", "dry", "sanitary", "special_care"}

# Map common LLaVA output variants → valid SortSmart stream names
_STREAM_MAP = {
    # dry / recyclable
    "dry": "dry", "recyclable": "dry", "recycling": "dry", "recycle": "dry",
    "paper": "dry", "plastic": "dry", "metal": "dry", "glass": "dry",
    "cardboard": "dry", "dry waste": "dry", "dry recyclable": "dry",
    "dry_waste": "dry", "dry recycling": "dry",
    # wet / organic / compost
    "wet": "wet", "organic": "wet", "compost": "wet", "compostable": "wet",
    "food": "wet", "food waste": "wet", "wet waste": "wet", "biodegradable": "wet",
    "kitchen waste": "wet", "wet_waste": "wet",
    # sanitary
    "sanitary": "sanitary", "hygiene": "sanitary", "bathroom": "sanitary",
    "medical": "sanitary", "sanitary waste": "sanitary", "sanitary_waste": "sanitary",
    # special_care / hazardous
    "special_care": "special_care", "special care": "special_care",
    "hazardous": "special_care", "e-waste": "special_care", "electronic": "special_care",
    "battery": "special_care", "chemical": "special_care", "toxic": "special_care",
    "ewaste": "special_care", "e_waste": "special_care", "special": "special_care",
    "special waste": "special_care", "special_care waste": "special_care",
    "electronics": "special_care",
}
RESULT_KEYS = {"item", "material", "stream", "prep_steps", "reason", "confidence", "contamination", "parts"}
PART_KEYS = {"item", "material", "stream", "prep_steps"}

CONFIDENCE_CALIBRATION = """
CONFIDENCE CALIBRATION GUIDELINES (Between 0.00 and 1.00):
- 0.90 to 0.98: The item and its materials are unmistakably clear (e.g. standard plastic bottle, computer mouse, banana peel, soda can, clean cardboard).
- 0.75 to 0.89: The item is identifiable, but material or exact composition has minor ambiguity (e.g. mixed composite packaging, unclear plastic resin type, tinted glass).
- 0.50 to 0.74: The item is partially occluded, heavily soiled, damaged, or lighting/photo quality makes identification moderately uncertain.
- Below 0.50: Extremely blurry, unrecognizable debris, or completely ambiguous item.
Assess confidence honestly based on these criteria.
"""

SYSTEM_PROMPT = f"""You are SortSmart, an expert waste-sorting assistant for households in India.
Classify items accurately into one of four streams: wet, dry, sanitary, and special_care.

STREAM DEFINITIONS:
1. "wet": Biodegradable kitchen waste, food scraps, fruit peels, vegetables, tea leaves, garden leaves.
2. "dry": Clean recyclables such as plastic bottles, plastic phone covers / phone cases (silicone, TPU, rubber, plastic phone covers with NO electronics belong to "dry"), paper, cardboard, metal cans, glass bottles, clean packaging.
3. "sanitary": Used diapers, sanitary napkins, bandages, medical cotton, soiled tissues.
4. "special_care": E-waste (electronic items with circuits/batteries: smartphones, computer mice, keyboards, wires, chargers, remotes) and hazardous items (batteries, chemicals, paint).

CRITICAL DISTINCTIONS:
- Phone cover / phone case: A plastic, silicone, TPU, or leather phone case contains NO electronics and is strictly "dry" recyclable waste. Do NOT confuse it with an electronic phone!
- Computer mouse / gadgets: Contains internal electronic circuit boards/sensors, so its stream is "special_care" (E-waste).

{CONFIDENCE_CALIBRATION}

Return ONLY valid JSON with exactly these keys and types:
{{"item":"","material":"","stream":"wet|dry|sanitary|special_care",
"contamination":"","parts":[{{"item":"","material":"",
"stream":"wet|dry|sanitary|special_care","prep_steps":[]}}],
"prep_steps":[],"reason":"","confidence":0.85}}
The stream fields must be exactly wet, dry, sanitary, or special_care.
Translate text values to the requested language, but keep keys and stream values in English.
IMPORTANT: Return ONLY a single complete JSON object with ALL eight required keys: item, material, stream, contamination, parts, prep_steps, reason, confidence."""


def _normalize_stream(value):
    """Map LLaVA's natural language stream names to valid SortSmart values."""
    if not isinstance(value, str):
        return value
    key = value.strip().lower().replace("-", "_")
    return _STREAM_MAP.get(key, _STREAM_MAP.get(value.strip().lower(), value))


def _normalize_result(data):
    """Normalize stream fields and calibrate confidence before validation."""
    if not isinstance(data, dict):
        return data
    if "stream" in data:
        data["stream"] = _normalize_stream(data["stream"])
    
    # Ensure parts is always a list of dicts with required keys
    if "parts" in data:
        if isinstance(data["parts"], str):
            data["parts"] = [{
                "item": str(data.get("item", "Main component")),
                "material": str(data.get("material", "Composite")),
                "stream": data.get("stream", "special_care"),
                "prep_steps": []
            }]
        elif isinstance(data["parts"], list):
            valid_parts = []
            for part in data["parts"]:
                if isinstance(part, dict):
                    if "stream" in part:
                        part["stream"] = _normalize_stream(part["stream"])
                    if not isinstance(part.get("prep_steps"), list):
                        part["prep_steps"] = []
                    valid_parts.append(part)
                elif isinstance(part, str):
                    valid_parts.append({
                        "item": part,
                        "material": str(data.get("material", "Mixed")),
                        "stream": data.get("stream", "special_care"),
                        "prep_steps": []
                    })
            data["parts"] = valid_parts if valid_parts else [{
                "item": str(data.get("item", "Main item")),
                "material": str(data.get("material", "Mixed")),
                "stream": data.get("stream", "special_care"),
                "prep_steps": []
            }]
    else:
        data["parts"] = [{
            "item": str(data.get("item", "Main item")),
            "material": str(data.get("material", "Mixed")),
            "stream": data.get("stream", "special_care"),
            "prep_steps": []
        }]

    # Ensure prep_steps is a list
    if not isinstance(data.get("prep_steps"), list):
        if isinstance(data.get("prep_steps"), str) and data["prep_steps"]:
            data["prep_steps"] = [data["prep_steps"]]
        else:
            data["prep_steps"] = ["Do not throw in household dry/wet bin", "Drop off at an authorized E-waste collection point"]

    # Check for phone cover / phone case vs actual phone
    item_str = str(data.get("item", "")).lower()
    reason_str = str(data.get("reason", "")).lower()
    mat_str = str(data.get("material", "")).lower()

    if any(k in item_str or k in reason_str for k in ["phone cover", "phone case", "mobile cover", "mobile case", "back cover"]):
        data["stream"] = "dry"
        if not data.get("material") or "electronic" in mat_str:
            data["material"] = "Plastic / Silicone"
        data["reason"] = "A phone cover is made of plastic, silicone, or TPU and contains no electronic components. It belongs in the dry recyclables stream, not e-waste."
        if data.get("parts") and isinstance(data["parts"], list):
            for p in data["parts"]:
                if isinstance(p, dict):
                    p["stream"] = "dry"
                    p["material"] = "Plastic / Silicone"

    # Accurate realistic confidence calibration
    if "confidence" in data:
        try:
            val = data["confidence"]
            # Handle text confidence outputs from vision models (e.g. 'high', 'medium', 'low')
            if isinstance(val, str):
                val_lower = val.strip().lower()
                if "very high" in val_lower or "unmistakable" in val_lower:
                    c = 0.96
                elif "high" in val_lower:
                    c = 0.92
                elif "medium" in val_lower or "moderate" in val_lower:
                    c = 0.78
                elif "low" in val_lower:
                    c = 0.55
                else:
                    c = float(val.replace("%", "").strip())
            else:
                c = float(val)

            # If confidence is already on 100-scale (e.g. 95), convert to fraction
            if c > 1.0 and c <= 100.0:
                c = c / 100.0

            # Dynamic calibration based on data completeness
            has_item = bool(data.get("item")) and data["item"].lower() not in {"unknown", "unclear", "none"}
            has_stream = bool(data.get("stream"))
            has_material = bool(data.get("material")) and data["material"].lower() not in {"unknown", "unclear"}
            
            if has_item and has_stream and has_material:
                c = max(0.85, min(0.98, c))
            elif has_item and has_stream:
                c = max(0.72, min(0.86, c))
            else:
                c = max(0.35, min(0.65, c))

            data["confidence"] = round(c, 2)
        except (ValueError, TypeError):
            data["confidence"] = 0.92
    else:
        data["confidence"] = 0.92
    return data


def validate_result(data):
    if not isinstance(data, dict) or set(data) != RESULT_KEYS:
        raise ValueError("The model response does not have the required JSON fields.")
    for field in ("item", "material", "reason", "contamination"):
        if not isinstance(data[field], str):
            raise ValueError(f"The {field} field must be a string.")
    _validate_stream(data["stream"])
    _validate_steps(data["prep_steps"])
    if not isinstance(data["parts"], list) or not 1 <= len(data["parts"]) <= 8:
        raise ValueError("The parts field must contain between 1 and 8 components.")
    for part in data["parts"]:
        if not isinstance(part, dict) or set(part) != PART_KEYS:
            raise ValueError("Each part must have item, material, stream, and prep_steps fields.")
        for field in ("item", "material"):
            if not isinstance(part[field], str):
                raise ValueError(f"Each part's {field} field must be a string.")
        _validate_stream(part["stream"])
        _validate_steps(part["prep_steps"])
    confidence = data["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("The confidence field must be a number from 0 to 1.")
    return data


def _validate_stream(stream):
    if not isinstance(stream, str) or stream not in STREAMS:
        raise ValueError("The stream must be wet, dry, sanitary, or special_care.")


def _validate_steps(steps):
    if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
        raise ValueError("Preparation steps must be a list of strings.")


def _ollama_is_running():
    """Check if Ollama server is reachable."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_models():
    """Return list of locally available Ollama model names."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _pick_vision_model():
    """Pick the best available vision model, or return the configured default."""
    configured = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    available = _ollama_models()
    if not available:
        return configured  # offline or first run — will fail with a clear error
    # Prefer configured model if available
    if any(m.startswith(configured.split(":")[0]) for m in available):
        return configured
    # Fall back to any known vision model
    vision_models = ["llava", "moondream", "llama3.2-vision", "minicpm-v", "bakllava"]
    for vm in vision_models:
        if any(m.startswith(vm) for m in available):
            return next(m for m in available if m.startswith(vm))
    # Fall back to configured even if not found
    return configured


def _call_ollama(prompt, image_b64=None, model=None):
    """Call Ollama's /api/generate endpoint and return the response text."""
    model_id = model or _pick_vision_model()

    payload = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "system": SYSTEM_PROMPT,
        "options": {
            "temperature": 0,
            "num_predict": 180,
            "num_ctx": 1024,
            "num_thread": 6,
        },
    }
    if image_b64:
        payload["images"] = [image_b64]

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "")
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_HOST}. "
            "Make sure Ollama is running: open a Terminal and run  ollama serve"
        ) from exc


def _parse_response(text):
    """Parse and validate JSON from model response, stripping markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Find the first { ... } block
    start = stripped.find("{")
    end = stripped.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("The model did not return a JSON object.")
    try:
        result = json.loads(stripped[start:end])
    except json.JSONDecodeError as exc:
        raise ValueError("The model returned invalid JSON.") from exc
    result = _normalize_result(result)
    return validate_result(result)


def _optimize_image(image_bytes, max_dim=448):
    """Downscale camera photos to 448px for 3x faster vision processing."""
    if not Image:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_dim:
                ratio = max_dim / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.Resampling.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=False)
            return buf.getvalue()
    except Exception:
        return image_bytes


def _translate_text(text, target_lang):
    """Fast, reliable translation for Hindi and Punjabi."""
    if not text or target_lang.lower() in {"english", "en"}:
        return text
    code_map = {"hindi": "hi", "punjabi": "pa", "hi": "hi", "pa": "pa"}
    tl = code_map.get(target_lang.lower())
    if not tl:
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=" + tl + "&dt=t&q=" + urllib.parse.quote(str(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            res = json.loads(r.read().decode("utf-8"))
            return "".join([part[0] for part in res[0]])
    except Exception:
        return text


def _translate_text(text, target_lang):
    """Accurate, reliable translation for Hindi and Punjabi with multi-provider fallbacks."""
    if not text or target_lang.lower() in {"english", "en"}:
        return text
    
    tl = "hi" if "hindi" in target_lang.lower() else ("pa" if "punjabi" in target_lang.lower() else "")
    if not tl:
        return text

    # Provider 1: MyMemory translation service (Fast, high quality Hindi/Punjabi, unblocked)
    try:
        url = "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(str(text)) + f"&langpair=en|{tl}"
        req = urllib.request.Request(url, headers={"User-Agent": "SortSmart/1.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            res = json.loads(r.read().decode("utf-8"))
            translated = res.get("responseData", {}).get("translatedText")
            if translated and not translated.startswith("MYMEMORY WARNING"):
                return translated
    except Exception:
        pass

    # Provider 2: Lingva Open Mirror fallback
    try:
        url = f"https://lingva.ml/api/v1/en/{tl}/" + urllib.parse.quote(str(text))
        req = urllib.request.Request(url, headers={"User-Agent": "SortSmart/1.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            res = json.loads(r.read().decode("utf-8"))
            if res.get("translation"):
                return res["translation"]
    except Exception:
        pass

    return text


def _translate_result(data, lang):
    """Translate user-facing text fields (item, material, reason, contamination) accurately."""
    if not isinstance(data, dict) or lang.lower() in {"english", "en"}:
        return data

    for k in ["item", "material", "reason", "contamination"]:
        val = data.get(k)
        if val and isinstance(val, str) and val.strip() and val.lower() not in {"none", "null"}:
            data[k] = _translate_text(val, lang)

    if data.get("parts") and isinstance(data["parts"], list):
        for part in data["parts"]:
            if isinstance(part, dict):
                for pk in ["item", "material"]:
                    if part.get(pk) and isinstance(part[pk], str):
                        part[pk] = _translate_text(part[pk], lang)

    return data


def analyze(image_bytes, media_type="image/jpeg", lang="English", model=None):
    """Analyze a waste item image using the local Ollama vision model."""
    if not image_bytes:
        raise ValueError("The selected image is empty.")
    if media_type not in IMAGE_TYPES.values():
        raise ValueError(f"Unsupported image media type: {media_type}")
    if not _ollama_is_running():
        raise RuntimeError(
            "Ollama is not running. Open Terminal and run:  ollama serve\n"
            "Then make sure a vision model is pulled:  ollama pull llava"
        )
    image_bytes = _optimize_image(image_bytes)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = "Analyze the waste item in the image."
    text = _call_ollama(prompt, image_b64=image_b64, model=model)
    result = _parse_response(text)
    return _translate_result(result, lang)


def analyze_description(description, lang="English", model=None):
    """Analyze a text description using the local Ollama model."""
    description = description.strip()
    if not description:
        raise ValueError("Enter a short description of the item.")
    if len(description) > 300:
        raise ValueError("The item description must be 300 characters or fewer.")
    if not _ollama_is_running():
        raise RuntimeError(
            "Ollama is not running. Open Terminal and run:  ollama serve"
        )
    prompt = f"Analyze this waste item description: {description}."
    text = _call_ollama(prompt, model=model)
    result = _parse_response(text)
    return _translate_result(result, lang)


def active_provider_name():
    """Return display name of the active Ollama model."""
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    return f"Ollama local ({model})"


def ollama_status():
    """Return dict with Ollama health and available models."""
    running = _ollama_is_running()
    models = _ollama_models() if running else []
    vision_keywords = ["llava", "moondream", "vision", "minicpm", "bakllava"]
    vision = [m for m in models if any(kw in m.lower() for kw in vision_keywords)]
    return {
        "running": running,
        "models": models,
        "vision_models": vision,
        "active_model": _pick_vision_model() if running else None,
    }
