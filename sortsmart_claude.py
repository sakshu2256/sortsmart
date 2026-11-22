#!/usr/bin/env python3
"""SortSmart AI backend: Anthropic Claude primary, Groq fallback.

Provider selection (checked in order):
  1. SORTSMART_PROVIDER env var — "anthropic" or "groq" (overrides auto-detect)
  2. If ANTHROPIC_API_KEY is set  → use Anthropic Claude
  3. If GROQ_API_KEY is set       → use Groq (original behaviour)
  4. Neither set → RuntimeError with actionable message
"""

import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=True)

# ---------------------------------------------------------------------------
# Shared constants (keep in sync with sortsmart.py)
# ---------------------------------------------------------------------------
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

IMAGE_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
STREAMS = {"wet", "dry", "sanitary", "special_care"}
RESULT_KEYS = {"item", "material", "stream", "prep_steps", "reason", "confidence", "contamination", "parts"}
PART_KEYS = {"item", "material", "stream", "prep_steps"}

SPEECH_LOCALE_PREFIXES = {"English": "en_", "Hindi": "hi_", "Punjabi": "pa_"}
SPOKEN_STREAMS = {
    "English": {"wet": "wet waste", "dry": "dry waste", "sanitary": "sanitary waste", "special_care": "special-care waste"},
    "Hindi": {"wet": "गीला कचरा", "dry": "सूखा कचरा", "sanitary": "स्वच्छता का कचरा", "special_care": "विशेष देखभाल वाला कचरा"},
    "Punjabi": {"wet": "ਗਿੱਲਾ ਕੂੜਾ", "dry": "ਸੁੱਕਾ ਕੂੜਾ", "sanitary": "ਸੈਨੇਟਰੀ ਕੂੜਾ", "special_care": "ਖ਼ਾਸ ਸੰਭਾਲ ਵਾਲਾ ਕੂੜਾ"},
}
SPEECH_LABELS = {
    "English": {"main": "Main stream", "condition": "Visible condition", "prep": "Preparation", "part": "Sort this part as"},
    "Hindi": {"main": "मुख्य कचरा वर्ग", "condition": "दिखाई देने वाली स्थिति", "prep": "तैयारी", "part": "इस हिस्से को इसमें डालें"},
    "Punjabi": {"main": "ਮੁੱਖ ਕੂੜਾ ਕਿਸਮ", "condition": "ਦਿਖਾਈ ਦੇਣ ਵਾਲੀ ਹਾਲਤ", "prep": "ਤਿਆਰੀ", "part": "ਇਸ ਹਿੱਸੇ ਨੂੰ ਇਸ ਤਰ੍ਹਾਂ ਛਾਂਟੋ"},
}

SYSTEM_PROMPT = """You are SortSmart, a waste-sorting assistant for households in India.
Classify items using this prototype's four streams: wet, dry, sanitary, and
special_care. This is not a verified municipal rules database: do not claim
legal compliance or invent city-specific collection instructions. If local
rules may differ, say so in the reason and lower confidence.

Use the image or short description to identify the item, material, and visible
contamination. If it has separately sortable components (for example, a greasy
cardboard box and a clean plastic lid), give each component its own stream and
prep steps in parts. Otherwise include one part for the whole item. Keep the
overall stream as the main component's stream. Mention uncertain observations
as uncertain; do not infer hidden materials or contamination.

Return ONLY JSON with exactly these keys and types:
{"item":"","material":"","stream":"wet|dry|sanitary|special_care",
"contamination":"","parts":[{"item":"","material":"",
"stream":"wet|dry|sanitary|special_care","prep_steps":[]}],
"prep_steps":[],"reason":"","confidence":0.0}
The stream fields must be exactly wet, dry, sanitary, or special_care.
Translate text values to the requested language, but keep keys and stream
values in English. If unsure, lower confidence."""


# ---------------------------------------------------------------------------
# Validation (identical to sortsmart.py so both modules can be used together)
# ---------------------------------------------------------------------------

def validate_result(data):
    """Validate the model's JSON against SortSmart's response contract."""
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
    if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
        raise ValueError("Preparation steps must be a list of strings.")


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _active_provider():
    """Return 'anthropic' or 'groq' based on env configuration."""
    explicit = os.environ.get("SORTSMART_PROVIDER", "").strip().lower()
    if explicit == "anthropic":
        return "anthropic"
    if explicit == "groq":
        return "groq"
    # Auto-detect: prefer Anthropic if key is present
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    raise RuntimeError(
        "No AI provider key found. Set ANTHROPIC_API_KEY (recommended) or GROQ_API_KEY "
        "in your .env file or shell environment. See README-SortSmart.md for setup."
    )


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

def _request_sorting_anthropic(content_blocks, model):
    """Call Anthropic Claude and return a validated JSON result."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The Anthropic SDK is not installed. Run: python -m pip install anthropic"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY in your .env file or shell environment.")

    client = anthropic.Anthropic(api_key=api_key)
    model_id = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)

    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

    if not response.content:
        raise ValueError("The Anthropic API response did not contain a result.")

    text = response.content[0].text if response.content else ""
    if not text:
        raise ValueError("The Anthropic API response did not contain a text result.")

    # Claude sometimes wraps JSON in a markdown code fence — strip it
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop first line (``` or ```json) and last line (```)
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("The model returned invalid JSON.") from exc
    return validate_result(result)


def _make_anthropic_image_block(image_bytes, media_type):
    """Build an Anthropic image content block from raw bytes."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        },
    }


# ---------------------------------------------------------------------------
# Groq backend (unchanged from original sortsmart.py)
# ---------------------------------------------------------------------------

def _request_sorting_groq(content, model):
    """Call Groq and return a validated JSON result (original implementation)."""
    try:
        from groq import APIError, Groq
    except ImportError as exc:
        raise RuntimeError(
            "The Groq SDK is not installed. Run: python -m pip install groq"
        ) from exc

    if not os.environ.get("GROQ_API_KEY"):
        raise RuntimeError("Set GROQ_API_KEY in your .env file or shell environment.")

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    reminder = (
        "IMPORTANT: Return ONLY a single complete JSON object with ALL eight "
        "required keys: item, material, stream, contamination, parts, "
        "prep_steps, reason, confidence. Do NOT truncate or omit any key."
    )

    if isinstance(content, str):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
            {"role": "user", "content": reminder},
        ]
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content + [{"type": "text", "text": reminder}]},
        ]

    try:
        response = client.chat.completions.create(
            model=model or os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            messages=messages,
            max_tokens=1200,
            temperature=0,
            response_format={"type": "json_object"},
        )
    except APIError as exc:
        raise RuntimeError(f"Groq API request failed: {exc}") from exc

    if not response.choices:
        raise ValueError("The Groq API response did not contain a result.")
    text = response.choices[0].message.content
    if not text:
        raise ValueError("The API response did not contain a text result.")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("The model returned invalid JSON.") from exc
    return validate_result(result)


# ---------------------------------------------------------------------------
# Unified public API  (same signatures as sortsmart.py's analyze / analyze_description)
# ---------------------------------------------------------------------------

def analyze(image_bytes, media_type="image/jpeg", lang="English", model=None):
    """Send an image to the active AI provider and return a validated sorting result.

    Provider priority: Anthropic Claude > Groq (see _active_provider()).
    Falls back to Groq automatically if Anthropic fails and GROQ_API_KEY is set.
    """
    if not image_bytes:
        raise ValueError("The selected image is empty.")
    if media_type not in IMAGE_TYPES.values():
        raise ValueError(f"Unsupported image media type: {media_type}")

    provider = _active_provider()
    if provider == "anthropic":
        try:
            return _request_sorting_anthropic(
                [
                    _make_anthropic_image_block(image_bytes, media_type),
                    {"type": "text", "text": f"Analyze the waste item. Reply in {lang}."},
                ],
                model,
            )
        except RuntimeError as exc:
            # Fall back to Groq if key is available and Anthropic failed
            if os.environ.get("GROQ_API_KEY"):
                groq_content = [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
                        },
                    },
                    {"type": "text", "text": f"Analyze the waste item. Reply in {lang}."},
                ]
                return _request_sorting_groq(groq_content, None)
            raise

    # Groq path
    groq_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
            },
        },
        {"type": "text", "text": f"Analyze the waste item. Reply in {lang}."},
    ]
    return _request_sorting_groq(groq_content, model)


def analyze_description(description, lang="English", model=None):
    """Analyze a text description. Uses Anthropic Claude first, falls back to Groq."""
    description = description.strip()
    if not description:
        raise ValueError("Enter a short description of the item.")
    if len(description) > 300:
        raise ValueError("The item description must be 300 characters or fewer.")

    prompt = f"Analyze this waste item description: {description}\nReply in {lang}."
    provider = _active_provider()

    if provider == "anthropic":
        try:
            return _request_sorting_anthropic(
                [{"type": "text", "text": prompt}],
                model,
            )
        except RuntimeError:
            if os.environ.get("GROQ_API_KEY"):
                return _request_sorting_groq(prompt, None)
            raise

    return _request_sorting_groq(prompt, model)


# ---------------------------------------------------------------------------
# Speech helpers (identical to sortsmart.py)
# ---------------------------------------------------------------------------

def speech_text(result, lang):
    """Build a spoken summary with stream names localized for the selected language."""
    labels = SPEECH_LABELS[lang]
    streams = SPOKEN_STREAMS[lang]
    segments = [
        result["item"],
        f"{labels['main']}: {streams[result['stream']]}",
        result["contamination"] and f"{labels['condition']}: {result['contamination']}",
        result["prep_steps"] and f"{labels['prep']}: {'. '.join(result['prep_steps'])}",
    ]
    for part in result["parts"]:
        part_text = f"{part['item']}, {part['material']}. {labels['part']}: {streams[part['stream']]}"
        if part["prep_steps"]:
            part_text += f". {'. '.join(part['prep_steps'])}"
        segments.append(part_text)
    segments.append(result["reason"])
    return ". ".join(segment for segment in segments if segment)


def active_provider_name():
    """Return a human-readable name of the active AI provider for status/health checks."""
    try:
        provider = _active_provider()
    except RuntimeError:
        return "none"
    if provider == "anthropic":
        model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        return f"Anthropic Claude ({model})"
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    return f"Groq ({model})"
