"""
intent_detector.py
━━━━━━━━━━━━━━━━━━
Detects taxi booking intent from transcript text using regex.
No LLM required — fast, free, works offline.

Your voice agent calls detect_taxi_intent() on every user turn.
If intent = "book_taxi" → fetch CRM data → call POST /book

Usage:
    from intent_detector import detect_taxi_intent
    result = detect_taxi_intent("I want to book a cab to the airport")
    # {"intent": "book_taxi", "confidence": "high"}
"""

import re
from typing import Optional

# ── Patterns ───────────────────────────────────────────────────────────────────

# High confidence — user clearly wants a taxi
HIGH_CONFIDENCE = [
    r"\b(book|call|get|need|want|order|arrange|hire)\b.{0,25}\b(cab|taxi|auto|ride|car)\b",
    r"\b(cab|taxi|auto|ride)\b.{0,25}\b(to|for|going|please|now|asap)\b",
    r"\btake me\b|\bdrop me\b|\bpick me up\b",
    r"\bi (want|need) (a |to )?(taxi|cab|ride|auto)\b",
    r"\bbook.{0,10}(taxi|cab|ride)\b",
    r"\b(taxi|cab).{0,10}(book|please|now|asap|arrange)\b",
    r"\bcan (you |i )?(get|book|arrange|have) (a )?(cab|taxi|ride|auto)\b",
]

# Medium confidence — going somewhere, likely needs taxi
MEDIUM_CONFIDENCE = [
    r"\b(going to|need to go|want to go|have to go|heading to|leaving for)\b.{0,40}\b(airport|station|mall|hospital|metro|market|bus stand)\b",
    r"\bgoing to (the )?(airport|station|railway|bus stand|metro|mall|hospital)\b",
    r"\bi('m| am) (leaving|heading|going)\b",
    r"\bneed (a )?ride\b",
]

# Cancel
CANCEL = [
    r"\b(cancel|stop|forget it|never mind|don't book|no taxi|no cab)\b",
]

_HIGH   = [re.compile(p, re.IGNORECASE) for p in HIGH_CONFIDENCE]
_MEDIUM = [re.compile(p, re.IGNORECASE) for p in MEDIUM_CONFIDENCE]
_CANCEL = [re.compile(p, re.IGNORECASE) for p in CANCEL]


def detect_taxi_intent(text: str) -> dict:
    """
    Detect intent from a single transcript turn.

    Returns:
        {"intent": "book_taxi"|"cancel_taxi"|"other", "confidence": "high"|"medium"|None}
    """
    text = text.strip()
    if not text:
        return {"intent": "other", "confidence": None}

    if any(p.search(text) for p in _CANCEL):
        return {"intent": "cancel_taxi", "confidence": "high"}

    if any(p.search(text) for p in _HIGH):
        return {"intent": "book_taxi", "confidence": "high"}

    if any(p.search(text) for p in _MEDIUM):
        return {"intent": "book_taxi", "confidence": "medium"}

    return {"intent": "other", "confidence": None}


def detect_taxi_intent_from_turns(turns: list) -> dict:
    """
    Detect intent across last 4 user turns combined.
    Use this when a user's intent spans multiple messages.

    Args:
        turns: [{"role": "user"|"agent", "text": "..."}]
    """
    user_texts = [t["text"] for t in turns if t.get("role") == "user"][-4:]
    return detect_taxi_intent(" ".join(user_texts))


def extract_pickup_time(text: str) -> str:
    """
    Extract pickup time from user message. Returns 'now' if not found.
    """
    patterns = [
        r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        r"\bin\s+(\d+\s+(?:minutes?|mins?|hours?))\b",
        r"\b(now|immediately|asap|right now|straight away)\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return "now"


def extract_destination(text: str) -> Optional[str]:
    # Strip common taxi booking prefixes before matching
    text = re.sub(
        r"^.*?\b(book|get|need|want|order|call|arrange)\b.{0,15}\b(taxi|cab|ride|auto)\b\s*",
        "", text, flags=re.IGNORECASE
    ).strip()

    m = re.search(
        r"\b(?:to|at|going to|go to|want to go to|heading to|drop (?:me )?at|take me to)\s+(?:the\s+)?([a-zA-Z0-9][a-zA-Z0-9\s]{2,30}?)(?:\s*(?:please|now|asap|at\s+\d|\.|,|!).*)?$",

        text, re.IGNORECASE
    )
    if m:
        destination = m.group(1).strip()
        skip = {"taxi", "cab", "ride", "auto", "car", "book", "me", "us", "a"}
        if destination.lower() not in skip and len(destination) > 2:
            return destination.title()

    keywords = ["airport", "station", "railway station", "bus stand", "bus stop",
                "mall", "hospital", "metro", "market", "hotel"]
    for kw in keywords:
        if kw in text.lower():
            return kw.title()

    return None