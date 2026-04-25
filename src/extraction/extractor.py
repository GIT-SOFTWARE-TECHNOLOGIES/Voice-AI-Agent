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
SYSTEM_PROMPT = """You are a hotel operations assistant. Read the call transcript and extract the service request into a structured JSON object.

Always return ONLY a valid JSON object — no explanation, no markdown, no code fences.

First identify the service_type from: taxi, laundry, food_order, maintenance

Then return the matching structure:

If taxi:
{
  "service_type": "taxi",
  "room_number": "string or null",
  "destination": "string or null",
  "pickup_time": "string or null",
  "status": "pending"
}

If laundry:
{
  "service_type": "laundry",
  "room_number": "string or null",
  "items": [{"name": "string", "quantity": integer}],
  "pickup_time": "string or null",
  "delivery_deadline": "string or null",
  "special_notes": "string or null",
  "urgency": "urgent | normal",
  "status": "pending"
}

If food_order:
{
  "service_type": "food_order",
  "room_number": "string or null",
  "items": [{"name": "string", "quantity": integer}],
  "delivery_deadline": "string or null",
  "special_notes": "string or null",
  "urgency": "urgent | normal",
  "status": "pending"
}

If maintenance:
{
  "service_type": "maintenance",
  "room_number": "string or null",
  "issue_description": "string or null",
  "urgency": "urgent | normal",
  "pickup_time": "string or null",
  "status": "pending"
}

Always set status to "pending".
urgency is "urgent" if guest expressed urgency or discomfort, otherwise "normal".
"""

MENU = {
    "cheese pizza":  350,
    "burger":        199,
    "french fries":  99,
    "sandwich":      149,
    "cold coffee":   129,
}

def enrich_food_items(items: list[dict]) -> tuple[list[dict], int]:
    enriched = []
    for item in items:
        name = item["name"].lower().strip()
        if name not in MENU:
            raise ValueError(f"Unknown menu item: '{item['name']}'")
        enriched.append({
            "name":     item["name"],
            "quantity": item["quantity"],
            "price":    MENU[name],
            "subtotal": MENU[name] * item["quantity"],
        })
    total = sum(i["subtotal"] for i in enriched)
    return enriched, total



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

    if extracted.get("service_type") == "food_order":
        extracted["items"], extracted["total_price"] = enrich_food_items(extracted["items"])

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