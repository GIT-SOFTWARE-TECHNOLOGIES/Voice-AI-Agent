"""
transcript_parser.py
━━━━━━━━━━━━━━━━━━━━
Parses the full transcript (list of JSON turn objects) sent by your voice agent.

Each turn looks like:
  {"session_id": "...", "room": "...", "role": "user"|"agent", "text": "...", "ts": ..., "turn_index": ...}

What this module does:
  1. Extracts destination, pickup_time, room_number, guest_name, guest_phone from the conversation
  2. Detects booking confirmation ("yes", "confirm", etc. after final summary)
  3. Detects cancellation intent
  4. Returns a ParsedTranscript with everything the worker needs

Your voice agent calls POST /transcript on every new user turn,
passing the full transcript so far (all turns as a JSON array).
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List

from src.taxi.intent_detector import detect_taxi_intent, extract_destination, extract_pickup_time



# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ParsedTranscript:
    session_id:   Optional[str] = None

    # Booking intent
    has_taxi_intent: bool = False
    intent_confidence: Optional[str] = None   # "high" | "medium"

    # Extracted from conversation
    destination:  Optional[str] = None
    pickup_time:  Optional[str] = None
    room_number:  Optional[str] = None
    guest_name:   Optional[str] = None
    guest_phone:  Optional[str] = None

    # Booking state
    booking_confirmed: bool = False   # user said "confirm"/"yes" after final summary
    booking_cancelled: bool = False

    # What's still missing (your agent can use this to ask the right question)
    missing_fields: List[str] = field(default_factory=list)

    # Last user text (for quick intent check)
    last_user_text: str = ""


# ── Confirmation / cancellation patterns ──────────────────────────────────────

_CONFIRM = re.compile(
    r"\b(yes|yep|yeah|confirm|confirmed|correct|sure|ok|okay|go ahead|proceed|book it|book|want to book|please|six|fine|great|perfect|sounds good)\b",
    re.IGNORECASE
)
_CANCEL = re.compile(
    r"\b(no|cancel|stop|never mind|forget it|don't book|don't proceed|abort)\b",
    re.IGNORECASE
)

# ── Field extractors ───────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"\b(\d{10})\b")
_ROOM_RE  = re.compile(r"\b(\d{1,4}[A-Za-z]?)\b")

# Words that are NOT names (filter false positives from name extraction)
_NOT_A_NAME = {
    "yes", "no", "ok", "okay", "sure", "confirm", "confirmed", "correct",
    "hello", "hi", "thanks", "thank", "please", "airport", "station",
    "mall", "hotel", "lobby", "taxi", "cab", "ride", "book", "booking",
    "now", "later", "time", "pm", "am", "cancel", "done",
}


def _extract_phone(text: str) -> Optional[str]:
    m = _PHONE_RE.search(text)
    return m.group(1) if m else None


def _extract_room(text: str) -> Optional[str]:
    """Extract room number — handles both '202' and '2, 0, 2' spoken formats."""
    # First try direct number
    m = re.search(r'\b(\d{1,4})\b', text)
    if m:
        candidate = m.group(1)
        if len(candidate) <= 4:
            return candidate

    # Handle spoken digits like "2, 0, 2" or "2 0 2" → "202"
    spoken = re.sub(r'[\s,]+', '', text)
    m = re.search(r'\b(\d{1,4})\b', spoken)
    if m:
        candidate = m.group(1)
        if len(candidate) <= 4:
            return candidate

    return None


def _extract_name(text: str) -> Optional[str]:
    """
    Extract a guest name from a short user reply.
    Assumes the user replied with just their name (e.g. "Abhay" or "Abhay Sharma").
    Filters out common non-name words.
    """
    text = text.strip()
    # Must be short (a name reply is usually 1-3 words)
    words = text.split()
    if len(words) > 4 or len(words) == 0:
        return None
    # All words must be alpha (no digits, no punctuation)
    if not all(w.isalpha() for w in words):
        return None
    # Filter out known non-name words
    if any(w.lower() in _NOT_A_NAME for w in words):
        return None
    return text.title()


# ── Agent question classifier ─────────────────────────────────────────────────
# We detect what the agent just asked so we know what the next user reply means.

_Q_DESTINATION = re.compile(r"\b(where|destination|going|drop)\b", re.IGNORECASE)
_Q_ROOM        = re.compile(r"\b(room number|room no|your room)\b", re.IGNORECASE)
_Q_NAME        = re.compile(r"\b(your name|may i have your name|name please)\b", re.IGNORECASE)
_Q_PHONE       = re.compile(r"\b(contact number|phone number|mobile number|number please)\b", re.IGNORECASE)
_Q_TIME        = re.compile(r"\b(when|what time|pickup time|right now or|specific time)\b", re.IGNORECASE)
# Final confirmation only — NOT "is that correct" (used mid-conversation after each field)
_Q_CONFIRM = re.compile(
    r"\b(i will now proceed|proceed to book|book your taxi|please confirm|shall i confirm|confirm your booking|taxi will be waiting|booked your taxi|taxi is confirmed|have a great|anything else|all set)\b",
    re.IGNORECASE
)

def _last_agent_question(turns: list) -> Optional[str]:
    """Return what topic the agent most recently asked about."""
    for turn in reversed(turns):
        if turn.get("role") == "agent":
            t = turn.get("text", "")
            if _Q_CONFIRM.search(t):    return "confirm"
            if _Q_PHONE.search(t):      return "phone"
            if _Q_NAME.search(t):       return "name"
            if _Q_ROOM.search(t):       return "room"
            if _Q_TIME.search(t):       return "time"
            if _Q_DESTINATION.search(t): return "destination"
            break
    return None


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_transcript(turns: list) -> ParsedTranscript:
    """
    Parse the full transcript and return a ParsedTranscript.

    Args:
        turns: list of dicts, each with keys: role, text, ts, turn_index, session_id (optional)

    Returns:
        ParsedTranscript with all extracted fields and booking state.
    """
    result = ParsedTranscript()

    if not turns:
        return result

    # Session ID from first turn
    result.session_id = turns[0].get("session_id")

    user_turns  = [t for t in turns if t.get("role") == "user"]
    agent_turns = [t for t in turns if t.get("role") == "agent"]

    if not user_turns:
        return result

    # Last user text
    last_user = user_turns[-1]
    result.last_user_text = last_user.get("text", "").strip()

    # ── Step 1: detect taxi intent across all user turns ──────────────────────
    all_user_text = " ".join(t.get("text", "") for t in user_turns)
    intent = detect_taxi_intent(all_user_text)

    if intent["intent"] == "cancel_taxi":
        result.booking_cancelled = True
        return result

    if intent["intent"] == "book_taxi":
        result.has_taxi_intent    = True
        result.intent_confidence  = intent["confidence"]

    # ── Step 2: extract fields from context-aware turn matching ───────────────
    # Walk through turns in order; when agent asks something, the next user reply answers it.

    for i, turn in enumerate(turns):
        if turn.get("role") != "agent":
            continue

        agent_text = turn.get("text", "")

        # Find the next user turn after this agent turn
        next_user = next(
            (t for t in turns[i+1:] if t.get("role") == "user"),
            None
        )
        if not next_user:
            continue
        user_reply = next_user.get("text", "").strip()

        # What did the agent ask?
        if _Q_DESTINATION.search(agent_text) and not result.destination:
            dest = extract_destination(user_reply) or (user_reply.title() if len(user_reply) < 40 else None)
            if dest:
                result.destination = dest

        elif _Q_ROOM.search(agent_text) and not result.room_number:
            room = _extract_room(user_reply)
            if room:
                result.room_number = room

        elif _Q_NAME.search(agent_text) and not result.guest_name:
            name = _extract_name(user_reply)
            if name:
                result.guest_name = name

        elif _Q_PHONE.search(agent_text) and not result.guest_phone:
            phone = _extract_phone(user_reply)
            if phone:
                result.guest_phone = phone

        elif _Q_TIME.search(agent_text) and not result.pickup_time:
            result.pickup_time = extract_pickup_time(user_reply)

        elif _Q_CONFIRM.search(agent_text):
            # User reply to final confirmation
            if _CONFIRM.search(user_reply):
                result.booking_confirmed = True
            elif _CANCEL.search(user_reply):
                result.booking_cancelled = True

    # ── Step 3: fallback — scan all user texts for fields still missing ───────
    # ── Step 3: fallback — also check agent turns for confirmed pickup time ────
    for turn in turns:
        text = turn.get("text", "")
        role = turn.get("role", "")

        # Extract destination from user turns
        if role == "user" and not result.destination:
            d = extract_destination(text)
            if d:
                result.destination = d

        if role == "user" and not result.guest_phone:
            p = _extract_phone(text)
            if p:
                result.guest_phone = p

        # Extract pickup time from BOTH user and agent turns
        if not result.pickup_time:
            pt = extract_pickup_time(text)
            if pt and pt != "now":
                result.pickup_time = pt

        # Extract room number from user turns — handle spoken digits
        if role == "user" and not result.room_number:
            room = _extract_room(text)
            if room:
                result.room_number = room

    # ── Step 4: also check first user turn for intent keywords ─────────────────
    if not result.has_taxi_intent:
        first_intent = detect_taxi_intent(user_turns[0].get("text", ""))
        if first_intent["intent"] == "book_taxi":
            result.has_taxi_intent   = True
            result.intent_confidence = first_intent["confidence"]

    # ── Step 5: calculate missing fields ──────────────────────────────────────
    # guest_name and guest_phone come from HubSpot CRM — not required from conversation.
    # Only destination, room_number, pickup_time must be collected in the call.
    missing = []
    if not result.destination:  missing.append("destination")
    if not result.room_number:  missing.append("room_number")
    if not result.pickup_time:  missing.append("pickup_time")
    result.missing_fields = missing

    return result