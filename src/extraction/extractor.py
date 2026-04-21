"""
extractor.py
------------
Reads a hotel call transcript and uses Claude to extract
structured service request data as JSON.
"""

import os
import json
from groq import Groq
import time
from dotenv import load_dotenv
load_dotenv()


# The system prompt tells grok exactly what to extract and how to format it
SYSTEM_PROMPT = """You are a hotel operations assistant. Your job is to read a call transcript 
between a hotel AI agent and a guest, then extract the service request details into a structured JSON object.

Always return ONLY a valid JSON object — no explanation, no markdown, no code fences.

The JSON must follow this exact structure:
{
  "room_number": "string or null",
  "service_type": "laundry | room_service | food_and_beverages | maintenance | conceirge",
  "items": [
    {"name": "string", "quantity": integer}
  ],
  "pickup_time": "string or null",
  "delivery_deadline": "string or null",
  "special_notes": "string or null",
  "urgency": "urgent | normal",
  "status": "pending",
  "confidence": "high | medium | low"
}

Service type rules — pick the closest match:
- "laundry"            → clothes pickup, washing, dry cleaning, ironing
- "room_service"       → towels, pillows, bedding, toiletries, housekeeping, extra amenities
- "food_and_beverages" → food orders, drinks, room dining, meal delivery
- "maintenance"        → broken appliances, AC issues, plumbing, electrical, anything that needs repair
- "concierge" → taxi booking, airport transfers, tour arrangements, 
                 wake-up calls, reservations, any guest assistance request

Field rules:
- items: list every requested item with its quantity. If no specific items, use [].
- pickup_time: when to collect (laundry) or when to arrive (maintenance/room_service).
- delivery_deadline: when it must be returned or completed by.
- special_notes: allergies, access instructions, urgency details, preferences.
- urgency: "urgent" if the guest expressed urgency or discomfort (e.g. hot room, no water), otherwise "normal".
- confidence reflects how clearly the full request was stated.
- Always set status to "pending".
"""



def parse_jsonl_transcript(raw: str) -> tuple[str, dict]:
    lines = []
    metadata = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        
        if not metadata:  # grab from first entry
            metadata = {
                "session_id": entry.get("session_id"),
                "room":       entry.get("room"),
            }
        role = "Agent" if entry["role"] == "agent" else "Guest"
        lines.append(f"{role}: {entry['text']}")
    return "\n".join(lines), metadata


def extract(transcript: str, metadata: dict = None) -> dict:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript}
                ],
                temperature=0.1,
                stream=False,
            )
            break
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)

    raw_response = response.choices[0].message.content.strip()

    if raw_response.startswith("```"):
        raw_response = raw_response.strip("`")
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]
        raw_response = raw_response.strip()

    try:
        extracted = json.loads(raw_response)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from LLM:\n{raw_response}")

    # Attach session metadata if available
    if metadata:
        extracted["session_id"] = metadata.get("session_id")
        extracted["room_name"]  = metadata.get("room")

    return extracted
    


def extract_from_file(filepath: str) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    first_line = raw.strip().split("\n")[0].strip()
    if first_line.startswith("{"):
        transcript, metadata = parse_jsonl_transcript(raw)
    else:
        transcript = raw
        metadata = {}

    if not transcript.strip():
        raise ValueError(f"No usable transcript content in file: {filepath}")

    return extract(transcript, metadata)


# ── Quick test when run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Default to the demo transcript if no path given
    path = sys.argv[1] if len(sys.argv) > 1 else "demo/laundry_transcript.txt"

    print(f"Reading transcript from: {path}\n")
    result = extract_from_file(path)
    print("Extracted JSON:")
    print(json.dumps(result, indent=2))