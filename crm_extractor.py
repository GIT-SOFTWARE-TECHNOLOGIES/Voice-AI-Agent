"""
crm_extractor.py
================
Transforms a session's conversation turns into a structured CRM JSON
using Phi-3 Mini running on RunPod via Ollama.

Usage (called automatically from personaplex_agent_new.py on session end):
    from src.crm_extractor import extract_crm

    crm = extract_crm(
        session_id=transcript.session_id,
        room_name=transcript.room_name,
        turns=transcript.get_turns(),
    )
"""

import json
import logging
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("crm_extractor")

CRM_DIR      = Path("crm_outputs")
OLLAMA_MODEL = "phi3:mini"
VALID_SERVICE_TYPES = {"laundry", "room_service", "food_and_beverages", "maintenance"}

# ── Set your RunPod Ollama URL here ──────────────────────────────────────────
OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "https://dbt5plox79jws5m-11434.proxy.runpod.net/api/generate"
)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data transformation engine.
Convert the input transcript JSON into the target CRM JSON.

Rules:
- Output ONLY valid JSON, nothing else
- No explanations, no markdown, no code blocks
- Extract room number from conversation text if not in the "room" field
- If a field is missing, use null
- service_type must be one of: laundry, room_service, food_and_beverages, maintenance
- urgency is "urgent" only for complaints or broken/not-working items, otherwise "normal"
- status is always "pending"
- confidence: "high" if all fields are clear, "medium" if partially inferred, "low" if uncertain

Target Schema:
{"room_number": "string", "service_type": "laundry | room_service | food_and_beverages | maintenance", "items": [{"name": "string", "quantity": number}], "pickup_time": "string | null", "delivery_deadline": "string | null", "special_notes": "string | null", "urgency": "normal | urgent", "status": "pending", "confidence": "high | medium | low"}"""


def _call_ollama_streaming(prompt: str) -> str:
    """
    Calls Ollama with stream=True and assembles the full response.
    Returns the complete response string.
    Raises requests exceptions on failure.
    """
    response = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
        timeout=120,
        stream=True,
    )
    response.raise_for_status()

    full_response = ""
    for line in response.iter_lines():
        if line:
            try:
                chunk = json.loads(line)
                full_response += chunk.get("response", "")
                if chunk.get("done"):
                    break
            except json.JSONDecodeError:
                logger.warning("Could not parse stream chunk: %r", line)
                continue

    return full_response.strip()


def _call_ollama_non_streaming(prompt: str) -> str:
    """
    Calls Ollama with stream=False.
    Returns the complete response string.
    Raises requests exceptions on failure.
    """
    response = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()

    raw_text = response.text
    logger.debug("Raw HTTP response body: %r", raw_text[:500])

    if not raw_text.strip():
        raise ValueError("Empty response body from Ollama")

    return response.json().get("response", "").strip()


def _call_ollama(prompt: str) -> str:
    """
    Tries non-streaming first; falls back to streaming if response is empty.
    """
    try:
        result = _call_ollama_non_streaming(prompt)
        if result:
            return result
        logger.warning("Non-streaming returned empty — retrying with streaming")
    except (ValueError, requests.exceptions.JSONDecodeError) as e:
        logger.warning("Non-streaming failed (%s) — retrying with streaming", e)

    return _call_ollama_streaming(prompt)


def _strip_markdown_fences(text: str) -> str:
    """Strips ```json ... ``` or ``` ... ``` fences if model adds them."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


def extract_crm(
    input_data: dict = None,
    *,
    session_id: str = None,
    room_name: str = None,
    turns: list[dict] = None,
) -> dict | None:
    """
    Two ways to call this:

    1. Pass a pre-built dict (for testing / manual use):
       extract_crm({"call_id": "x", "conversation": [...], ...}, session_id="x")

    2. Pass individual fields (called from agent finally block):
       extract_crm(session_id="x", room_name="room1", turns=[...])
    """
    CRM_DIR.mkdir(parents=True, exist_ok=True)

    if input_data is not None:
        input_json = input_data
        if session_id is None:
            session_id = input_data.get("call_id", "unknown")
    else:
        input_json = {
            "call_id": session_id,
            "room": room_name,
            "conversation": [
                {"role": t["role"], "text": t["text"]}
                for t in (turns or [])
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    prompt = f"{SYSTEM_PROMPT}\n\nInput:\n{json.dumps(input_json, ensure_ascii=False)}"

    raw = ""
    try:
        raw = _call_ollama(prompt)
        logger.debug("Ollama raw output: %r", raw[:500])

        if not raw:
            logger.error("Ollama returned an empty response after all attempts")
            return None

        raw = _strip_markdown_fences(raw)
        crm = json.loads(raw)

        # Save to file for audit trail
        out_path = CRM_DIR / f"{session_id}_crm.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(crm, f, indent=2, ensure_ascii=False)

        logger.info("CRM extraction saved → %s", out_path)
        logger.info("CRM result: %s", json.dumps(crm))
        return crm

    except requests.exceptions.ConnectionError:
        logger.error(
            "Cannot reach Ollama on RunPod — check OLLAMA_URL and that 'ollama serve' is running"
        )
    except requests.exceptions.Timeout:
        logger.error(
            "Ollama timed out — model may still be loading, wait 30s and retry"
        )
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP error from Ollama: %s", e)
    except json.JSONDecodeError as e:
        logger.error("Model returned invalid JSON: %s | raw output was: %r", e, raw)
    except Exception as e:
        logger.error("CRM extraction failed: %s", e, exc_info=True)

    return None


def _validate_and_fix(crm: dict) -> dict:
    """Fix common model hallucinations in enum fields."""
    
    # Fix service_type fuzzy matching
    st = crm.get("service_type", "")
    if st not in VALID_SERVICE_TYPES:
        if "maint" in st:
            crm["service_type"] = "maintenance"
        elif "food" in st or "bev" in st:
            crm["service_type"] = "food_and_beverages"
        elif "laundry" in st:
            crm["service_type"] = "laundry"
        elif "room" in st:
            crm["service_type"] = "room_service"
        else:
            logger.warning("Unknown service_type %r — keeping as-is", st)

    # Fix urgency
    if crm.get("urgency") not in {"normal", "urgent"}:
        crm["urgency"] = "normal"

    # Fix status
    crm["status"] = "pending"

    # Fix confidence
    if crm.get("confidence") not in {"high", "medium", "low"}:
        crm["confidence"] = "low"

    return crm