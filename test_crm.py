"""
test_crm.py
===========
Quick smoke-test for crm_extractor.extract_crm().

Run from the project root:
    python test_crm.py
"""

import logging
import json
from crm_extractor import extract_crm

# Show logs in terminal while testing
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Test 1: laundry request ───────────────────────────────────────────────────
test_input = {
    "call_id": "test_001",
    "room": None,                        # Intentionally missing — model must extract from text
    "conversation": [
        {"role": "agent", "text": "Hello, how can I help you today?"},
        {"role": "guest", "text": "Hi, I'm in room 302. I need laundry service."},
        {"role": "agent", "text": "Of course! What items do you need laundered?"},
        {"role": "guest", "text": "Two shirts and one jacket. Return tomorrow morning please."},
    ],
    "timestamp": "2026-04-16T10:00:00Z",
}

print("\n" + "="*60)
print("TEST 1 — Laundry request (room extracted from conversation)")
print("="*60)

# ✅ FIX: Do NOT pass session_id here — it's already inside the dict as "call_id"
result = extract_crm(test_input)

print("OUTPUT:")
print(json.dumps(result, indent=2) if result else "None — check logs above for error")


# ── Test 2: maintenance urgent request ───────────────────────────────────────
test_input_2 = {
    "call_id": "test_002",
    "room": "504",
    "conversation": [
        {"role": "agent", "text": "Good evening, how can I assist you?"},
        {"role": "guest", "text": "The air conditioning in my room is broken. It's very hot!"},
        {"role": "agent", "text": "I'm sorry to hear that. We'll send someone right away."},
    ],
    "timestamp": "2026-04-16T22:00:00Z",
}

print("\n" + "="*60)
print("TEST 2 — Maintenance urgent (room in dict, urgency should be 'urgent')")
print("="*60)

result2 = extract_crm(test_input_2)

print("OUTPUT:")
print(json.dumps(result2, indent=2) if result2 else "None — check logs above for error")


# ── Test 3: keyword-argument form (simulates agent finally block) ─────────────
print("\n" + "="*60)
print("TEST 3 — Keyword-argument form (agent finally block style)")
print("="*60)

result3 = extract_crm(
    session_id="test_003",
    room_name="201",
    turns=[
        {"role": "agent", "text": "Room service, how can I help?"},
        {"role": "guest", "text": "I'd like to order a club sandwich and a cola please."},
    ],
)

print("OUTPUT:")
print(json.dumps(result3, indent=2) if result3 else "None — check logs above for error")