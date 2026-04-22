"""
transcript_parser.py
━━━━━━━━━━━━━━━━━━━━
Parses the full transcript from a live voice agent conversation.

Handles real voice agent conversations where:
- Room numbers may be spoken as digits: "2, 0, 2" or "2 0 2" → "202"
- Agent may confirm booking in natural language: "Your taxi will be ready"
- Destination may not always be explicitly stated
- Pickup time may come from agent's confirmation turn
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List

from src.taxi.intent_detector import detect_taxi_intent, extract_destination, extract_pickup_time


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ParsedTranscript:
    session_id:   Optional[str] = None

    has_taxi_intent: bool = False
    intent_confidence: Optional[str] = None

    destination:  Optional[str] = None
    pickup_time:  Optional[str] = None
    room_number:  Optional[str] = None
    guest_name:   Optional[str] = None
    guest_phone:  Optional[str] = None

    booking_confirmed: bool = False
    booking_cancelled: bool = False

    missing_fields: List[str] = field(default_factory=list)
    last_user_text: str = ""


# ── Patterns ───────────────────────────────────────────────────────────────────

_CONFIRM = re.compile(
    r"\b(yes|yep|yeah|confirm|confirmed|correct|sure|ok|okay|go ahead|"
    r"proceed|book it|book|want to book|please|sounds good|perfect|great|fine)\b",
    re.IGNORECASE
)
_CANCEL = re.compile(
    r"\b(no|cancel|stop|never mind|forget it|don't book|don't proceed|abort)\b",
    re.IGNORECASE
)

# Detects when agent naturally confirms booking in its own words
_AGENT_BOOKING_DONE = re.compile(
    r"\b(taxi will be|taxi is confirmed|booked your taxi|taxi has been|"
    r"waiting outside|arrive within|on its way|driver will|cab will be|"
    r"your ride|arranged your taxi|taxi for you)\b",
    re.IGNORECASE
)

_PHONE_RE = re.compile(r"\b(\d{10})\b")

_NOT_A_NAME = {
    "yes", "no", "ok", "okay", "sure", "confirm", "confirmed", "correct",
    "hello", "hi", "thanks", "thank", "please", "airport", "station",
    "mall", "hotel", "lobby", "taxi", "cab", "ride", "book", "booking",
    "now", "later", "time", "pm", "am", "cancel", "done", "want",
}


# ── Field extractors ───────────────────────────────────────────────────────────

def _extract_phone(text: str) -> Optional[str]:
    m = _PHONE_RE.search(text)
    return m.group(1) if m else None


def _extract_room(text: str) -> Optional[str]:
    """
    Extract room number — handles:
    - Direct: "202", "101", "304B"
    - Spoken digits: "2, 0, 2" → "202", "2 3 2 1" → "2321"
    - Agent confirming: "Your room is 2 0 2"
    """
    # Remove commas and extra spaces, join digits
    cleaned = re.sub(r'[\s,]+', '', text)

    # Find 2-4 digit number (room numbers are 2-4 digits)
    m = re.search(r'\b(\d{2,4})\b', cleaned)
    if m:
        candidate = m.group(1)
        if 2 <= len(candidate) <= 4:
            return candidate

    # Try original text for numbers like "101" or "204B"
    m = re.search(r'\b(\d{1,4}[A-Za-z]?)\b', text)
    if m:
        candidate = m.group(1)
        if 2 <= len(re.sub(r'[A-Za-z]', '', candidate)) <= 4:
            return candidate

    return None


def _extract_name(text: str) -> Optional[str]:
    text = text.strip()
    words = text.split()
    if len(words) > 4 or len(words) == 0:
        return None
    if not all(w.isalpha() for w in words):
        return None
    if any(w.lower() in _NOT_A_NAME for w in words):
        return None
    return text.title()


def _extract_room_from_agent(text: str) -> Optional[str]:
    """Extract room number when agent confirms it: 'Your room is 2 0 2'"""
    m = re.search(
        r'\b(?:room(?:\s+(?:number|no|is))?|room\s+is)\s+([\d\s,]{1,10})',
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(1)
        digits = re.sub(r'[\s,]+', '', raw)
        if 2 <= len(digits) <= 4:
            return digits
    return None


def _extract_time_from_agent(text: str) -> Optional[str]:
    """Extract pickup time when agent confirms it: 'Got it, 6 PM' or 'taxi for 7:30 PM'"""
    patterns = [
        r'\b(?:for|at|by|around)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b',
        r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b',
        r'\bin\s+(\d+\s+(?:minutes?|mins?|hours?))\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


# ── Agent question classifier ──────────────────────────────────────────────────

_Q_DESTINATION = re.compile(r"\b(where|destination|going|drop|which place)\b", re.IGNORECASE)
_Q_ROOM        = re.compile(r"\b(room number|room no|your room|which room)\b", re.IGNORECASE)
_Q_NAME        = re.compile(r"\b(your name|may i have your name|name please|what.*name)\b", re.IGNORECASE)
_Q_PHONE       = re.compile(r"\b(contact number|phone number|mobile number|number please)\b", re.IGNORECASE)
_Q_TIME        = re.compile(r"\b(when|what time|pickup time|right now or|specific time|what.*time)\b", re.IGNORECASE)
_Q_CONFIRM     = re.compile(
    r"\b(i will now proceed|proceed to book|book your taxi|please confirm|"
    r"shall i confirm|confirm your booking|taxi will be waiting|booked your taxi|"
    r"taxi is confirmed|have a great|anything else|all set|is that correct|"
    r"shall i go ahead)\b",
    re.IGNORECASE
)


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_transcript(turns: list) -> ParsedTranscript:
    result = ParsedTranscript()

    if not turns:
        return result

    result.session_id = turns[0].get("session_id")

    user_turns  = [t for t in turns if t.get("role") == "user"]
    agent_turns = [t for t in turns if t.get("role") == "agent"]

    if not user_turns:
        return result

    last_user = user_turns[-1]
    result.last_user_text = last_user.get("text", "").strip()

    # ── Step 1: detect taxi intent ─────────────────────────────────────────────
    all_user_text = " ".join(t.get("text", "") for t in user_turns)
    intent = detect_taxi_intent(all_user_text)

    if intent["intent"] == "cancel_taxi":
        result.booking_cancelled = True
        return result

    if intent["intent"] == "book_taxi":
        result.has_taxi_intent   = True
        result.intent_confidence = intent["confidence"]

    # ── Step 2: context-aware turn matching ────────────────────────────────────
    for i, turn in enumerate(turns):
        if turn.get("role") != "agent":
            continue

        agent_text = turn.get("text", "")

        # Extract room number from agent's confirmation text
        # e.g. "Your room is 2 0 2"
        if not result.room_number:
            room = _extract_room_from_agent(agent_text)
            if room:
                result.room_number = room

        # Extract pickup time from agent's confirmation
        # e.g. "Got it, 6 PM. Your taxi will be waiting"
        if not result.pickup_time:
            pt = _extract_time_from_agent(agent_text)
            if pt:
                result.pickup_time = pt

        # Detect when agent naturally confirms booking done
        if _AGENT_BOOKING_DONE.search(agent_text):
            result.booking_confirmed = True

        # Find next user turn for Q&A matching
        next_user = next(
            (t for t in turns[i+1:] if t.get("role") == "user"),
            None
        )
        if not next_user:
            continue
        user_reply = next_user.get("text", "").strip()

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
            if _CONFIRM.search(user_reply):
                result.booking_confirmed = True
            elif _CANCEL.search(user_reply):
                result.booking_cancelled = True

    # ── Step 3: fallback scan ──────────────────────────────────────────────────
    for turn in user_turns:
        text = turn.get("text", "")

        if not result.destination:
            d = extract_destination(text)
            if d:
                result.destination = d

        if not result.guest_phone:
            p = _extract_phone(text)
            if p:
                result.guest_phone = p

        if not result.pickup_time:
            pt = extract_pickup_time(text)
            if pt and pt != "now":
                result.pickup_time = pt

        # Extract room from user turns — handles spoken digits
        if not result.room_number:
            room = _extract_room(text)
            if room:
                result.room_number = room

    # ── Step 4: intent check on first turn ────────────────────────────────────
    if not result.has_taxi_intent:
        first_intent = detect_taxi_intent(user_turns[0].get("text", ""))
        if first_intent["intent"] == "book_taxi":
            result.has_taxi_intent   = True
            result.intent_confidence = first_intent["confidence"]

    # ── Step 5: clean up destination ──────────────────────────────────────────
    # Remove false positives like "Book A Taxi" being set as destination
    taxi_false_positives = {
    "book a taxi", "taxi", "cab", "ride", "book", "a taxi",
    "book a cab", "i want to book a taxi", "want to book",   # ← comma here
    "book a taxi to the airport",
    "a taxi to the airport",
    }
    if result.destination and result.destination.lower() in taxi_false_positives:
        result.destination = None

    # ── Step 6: missing fields ─────────────────────────────────────────────────
    missing = []
    if not result.destination:  missing.append("destination")
    if not result.room_number:  missing.append("room_number")
    if not result.pickup_time:  missing.append("pickup_time")
    result.missing_fields = missing

    return result