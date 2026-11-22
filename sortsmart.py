#!/usr/bin/env python3
"""Identify a waste item and suggest how to sort its components."""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=True)

DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
IMAGE_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
STREAMS = {"wet", "dry", "sanitary", "special_care"}
RESULT_KEYS = {
    "item",
    "material",
    "stream",
    "prep_steps",
    "reason",
    "confidence",
    "contamination",
    "parts",
}
PART_KEYS = {"item", "material", "stream", "prep_steps"}
SPEECH_LOCALE_PREFIXES = {"English": "en_", "Hindi": "hi_", "Punjabi": "pa_"}
SPOKEN_STREAMS = {
    "English": {
        "wet": "wet waste",
        "dry": "dry waste",
        "sanitary": "sanitary waste",
        "special_care": "special-care waste",
    },
    "Hindi": {
        "wet": "गीला कचरा",
        "dry": "सूखा कचरा",
        "sanitary": "स्वच्छता का कचरा",
        "special_care": "विशेष देखभाल वाला कचरा",
    },
    "Punjabi": {
        "wet": "ਗਿੱਲਾ ਕੂੜਾ",
        "dry": "ਸੁੱਕਾ ਕੂੜਾ",
        "sanitary": "ਸੈਨੇਟਰੀ ਕੂੜਾ",
        "special_care": "ਖ਼ਾਸ ਸੰਭਾਲ ਵਾਲਾ ਕੂੜਾ",
    },
}
SPEECH_LABELS = {
    "English": {"main": "Main stream", "condition": "Visible condition", "prep": "Preparation", "part": "Sort this part as"},
    "Hindi": {"main": "मुख्य कचरा वर्ग", "condition": "दिखाई देने वाली स्थिति", "prep": "तैयारी", "part": "इस हिस्से को इसमें डालें"},
    "Punjabi": {"main": "ਮੁੱਖ ਕੂੜਾ ਕਿਸਮ", "condition": "ਦਿਖਾਈ ਦੇਣ ਵਾਲੀ ਹਾਲਤ", "prep": "ਤਿਆਰੀ", "part": "ਇਸ ਹਿੱਸੇ ਨੂੰ ਇਸ ਤਰ੍ਹਾਂ ਛਾਂਟੋ"},
}
SYSTEM_PROMPT = """You are SortSmart, a waste-sorting assistant for households in India.
Classify items into four streams: wet, dry, sanitary, and special_care.

RULES:
- Electronics, cables, batteries, gadgets, chargers, appliances, and computer accessories (like a mouse, keyboard, remote) belong to "special_care" (E-waste), even if their outer shell is plastic.
- Explain in reason why it is classified as such (e.g. explain that internal electronics/circuits require special_care e-waste recycling, while the outer shell is plastic).

Return ONLY a JSON object with this exact schema:
{
  "item": "name of item",
  "material": "main material (e.g. plastic and electronics)",
  "stream": "wet|dry|sanitary|special_care",
  "contamination": "visible contamination or none",
  "parts": [
    {
      "item": "component name",
      "material": "material",
      "stream": "wet|dry|sanitary|special_care",
      "prep_steps": ["step 1"]
    }
  ],
  "prep_steps": ["step 1"],
  "reason": "explanation of disposal",
  "confidence": 0.95
}"""


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


def _request_sorting(content, model):
    """Request and validate one JSON sorting decision."""
    try:
        from groq import APIError, Groq
    except ImportError as exc:
        raise RuntimeError(
            "The Groq SDK is not installed. Run: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    if not os.environ.get("GROQ_API_KEY"):
        raise RuntimeError("Set GROQ_API_KEY in your environment or project .env file.")

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    # Build messages
    if isinstance(content, str):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{content}\nRespond with a valid JSON object matching the requested schema."},
        ]
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    try:
        response = client.chat.completions.create(
            model=model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            messages=messages,
            max_tokens=1400,
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


def analyze(image_bytes, media_type="image/jpeg", lang="English", model=None):
    """Send an image to Groq and return a validated sorting result."""
    if not image_bytes:
        raise ValueError("The selected image is empty.")
    if media_type not in IMAGE_TYPES.values():
        raise ValueError(f"Unsupported image media type: {media_type}")
    return _request_sorting(
        [
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{media_type};base64,"
                        f"{base64.b64encode(image_bytes).decode('ascii')}"
                    )
                },
            },
            {"type": "text", "text": f"Analyze the waste item. Reply in {lang}."},
        ],
        model,
    )


_LANG_INSTRUCTION = {
    "English": "Reply entirely in English.",
    "Hindi":   "IMPORTANT: सभी text values हिंदी में लिखें (item, material, contamination, prep_steps, reason सब हिंदी में). Keys और stream values अंग्रेज़ी में रखें। Reply in Hindi.",
    "Punjabi": "IMPORTANT: ਸਾਰੇ text values ਪੰਜਾਬੀ ਵਿੱਚ ਲਿਖੋ (item, material, contamination, prep_steps, reason ਸਭ ਪੰਜਾਬੀ ਵਿੱਚ). Keys ਅਤੇ stream values ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਰੱਖੋ। Reply in Punjabi.",
}

def analyze_description(description, lang="English", model=None):
    """Analyze a short text description without requesting an image."""
    description = description.strip()
    if not description:
        raise ValueError("Enter a short description of the item.")
    if len(description) > 300:
        raise ValueError("The item description must be 300 characters or fewer.")
    lang_note = _LANG_INSTRUCTION.get(lang, f"Reply in {lang}.")
    return _request_sorting(
        f"Analyze this waste item: {description}\n{lang_note}",
        model,
    )


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


def _macos_voice(lang):
    try:
        voices = subprocess.run(
            ["say", "-v", "?"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except FileNotFoundError as exc:
        raise RuntimeError("The macOS `say` command is unavailable.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Could not list installed macOS speech voices.") from exc

    locale_prefix = SPEECH_LOCALE_PREFIXES[lang]
    matches = [
        (line.split()[0], next((word for word in line.split() if word.startswith(locale_prefix)), ""))
        for line in voices.splitlines()
        if line.split()
    ]
    match = next(
        (name for name, locale in matches if locale == f"{locale_prefix}IN"),
        None,
    ) or next((name for name, locale in matches if locale.startswith(locale_prefix)), None)
    if not match:
        raise RuntimeError(
            f"No macOS speech voice for {lang} is installed. Add a matching voice "
            "in System Settings → Accessibility → Spoken Content."
        )
    return match


def speak_result(result, lang):
    """Read the sorting result using an installed macOS speech voice."""
    if sys.platform != "darwin":
        raise RuntimeError("CLI speech playback is available on macOS only.")
    if lang not in SPEECH_LOCALE_PREFIXES:
        raise RuntimeError("CLI speech playback supports English, Hindi, or Punjabi.")
    voice = _macos_voice(lang)
    try:
        subprocess.run(["say", "-v", voice, speech_text(result, lang)], check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("The macOS `say` command is unavailable.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("macOS speech playback failed.") from exc


def main():
    parser = argparse.ArgumentParser(
        description="Identify waste from a photo and suggest how to sort it."
    )
    parser.add_argument("image", type=Path, help="Path to a JPEG, PNG, GIF, or WebP image")
    parser.add_argument("--language", default="English", help="Language for the result")
    parser.add_argument(
        "--model",
        default=None,
        help=f"Groq model ID (default: GROQ_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--speak",
        action="store_true",
        help="read the result aloud using an installed macOS speech voice",
    )
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error(f"image file not found: {args.image}")
    media_type = IMAGE_TYPES.get(args.image.suffix.lower())
    if media_type is None:
        parser.error("image must have a .jpg, .jpeg, .png, .gif, or .webp extension")

    try:
        result = analyze(args.image.read_bytes(), media_type, args.language, args.model)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"SortSmart: {exc}\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.speak:
        try:
            speak_result(result, args.language)
        except RuntimeError as exc:
            parser.exit(1, f"SortSmart: {exc}\n")


if __name__ == "__main__":
    main()
