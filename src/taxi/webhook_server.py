"""
webhook_server.py — Hotel Taxi Worker v4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Endpoints:
  POST /transcript  ← NEW: your voice agent posts full transcript every user turn
  POST /intent      ← legacy: single-turn intent check (still works)
  POST /book        ← legacy: direct booking with all data supplied
  GET  /health      ← health check

Run:
  uvicorn webhook_server:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from typing import Optional, List, Any

from fastapi import FastAPI
from pydantic import BaseModel

from intent_detector   import detect_taxi_intent, extract_pickup_time, extract_destination
from taxi_worker       import TaxiWorker, GuestData
from transcript_parser import parse_transcript
from hubspot_client    import fetch_guest

log = logging.getLogger("WebhookServer")
app = FastAPI(title="Hotel Taxi Worker", version="4.0")

worker = TaxiWorker()


# ══════════════════════════════════════════════════════════════════════════════
# POST /transcript  ← MAIN endpoint your voice agent uses
# ══════════════════════════════════════════════════════════════════════════════

class TranscriptTurn(BaseModel):
    session_id:  Optional[str] = None
    room:        Optional[str] = None
    role:        str
    text:        str
    ts:          Optional[float] = None
    turn_index:  Optional[int]   = None


class TranscriptRequest(BaseModel):
    turns: List[TranscriptTurn]


class TranscriptResponse(BaseModel):
    status: str  # "no_intent"|"collecting"|"ready_to_book"|"booked"|"cancelled"|"error"
    has_taxi_intent:    bool = False
    intent_confidence:  Optional[str] = None
    destination:  Optional[str] = None
    pickup_time:  Optional[str] = None
    room_number:  Optional[str] = None
    guest_name:   Optional[str] = None
    guest_phone:  Optional[str] = None
    missing_fields: List[str] = []
    booking_id:   Optional[str] = None
    sms_sent:     bool = False
    email_sent:   bool = False
    driver:       Optional[Any] = None
    message:      Optional[str] = None
    crm_found:    bool = False
    error:        Optional[str] = None


@app.post("/transcript", response_model=TranscriptResponse)
async def handle_transcript(req: TranscriptRequest):
    turns = [t.model_dump() for t in req.turns]
    parsed = parse_transcript(turns)

    if parsed.booking_cancelled:
        return TranscriptResponse(
            status  = "cancelled",
            message = "Okay, I've cancelled the taxi request. Is there anything else I can help you with?",
        )

    if not parsed.has_taxi_intent:
        return TranscriptResponse(status="no_intent")

    base = TranscriptResponse(
        status             = "collecting",
        has_taxi_intent    = True,
        intent_confidence  = parsed.intent_confidence,
        destination        = parsed.destination,
        pickup_time        = parsed.pickup_time,
        room_number        = parsed.room_number,
        guest_name         = parsed.guest_name,
        guest_phone        = parsed.guest_phone,
        missing_fields     = parsed.missing_fields,
    )

    if not parsed.booking_confirmed:
        return base

    if parsed.missing_fields:
        base.message = f"Still need: {', '.join(parsed.missing_fields)}"
        return base

    # All confirmed — fetch HubSpot (CRM is single source of truth for guest details)
    crm = fetch_guest(room_number=parsed.room_number, phone=parsed.guest_phone)

    if not crm.found:
        return TranscriptResponse(
            status="error",
            error="Guest not found in CRM. Cannot proceed with booking.",
            has_taxi_intent=True,
            missing_fields=[],
        )

    final_name  = crm.guest_name  or "Guest"
    final_phone = crm.guest_phone
    final_room  = crm.room_number or parsed.room_number or "N/A"

    if not final_phone:
        return TranscriptResponse(
            status="error",
            error="Guest found in CRM but no phone number on record — cannot send SMS.",
            has_taxi_intent=True,
            missing_fields=["guest_phone"],
        )

    guest = GuestData(
        guest_name      = final_name,
        guest_phone     = final_phone,
        guest_email     = crm.guest_email,
        room_number     = final_room,
        destination     = parsed.destination or "Unknown",
        pickup_time     = parsed.pickup_time  or "now",
        pickup_location = "Hotel Lobby",
    )

    result = worker.book(guest)

    return TranscriptResponse(
        status            = "booked",
        has_taxi_intent   = True,
        intent_confidence = parsed.intent_confidence,
        destination       = parsed.destination,
        pickup_time       = parsed.pickup_time,
        room_number       = final_room,
        guest_name        = final_name,
        guest_phone       = final_phone,
        booking_id        = result.booking_id,
        sms_sent          = result.sms_sent,
        email_sent        = result.email_sent,
        driver            = result.driver,
        message           = result.message,
        crm_found         = crm.found,
        missing_fields    = [],
    )


# ── /intent (legacy) ──────────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    text:       str
    session_id: Optional[str] = None

class IntentResponse(BaseModel):
    intent:      str
    confidence:  Optional[str]
    destination: Optional[str]
    pickup_time: Optional[str]

@app.post("/intent", response_model=IntentResponse)
async def check_intent(req: IntentRequest):
    result      = detect_taxi_intent(req.text)
    destination = extract_destination(req.text)
    pickup_time = extract_pickup_time(req.text) if result["intent"] == "book_taxi" else None
    return IntentResponse(
        intent=result["intent"], confidence=result["confidence"],
        destination=destination, pickup_time=pickup_time,
    )


# ── /book (legacy) ────────────────────────────────────────────────────────────

class BookRequest(BaseModel):
    guest_name:      str
    guest_phone:     str
    room_number:     str
    destination:     str
    pickup_time:     Optional[str] = "now"
    pickup_location: Optional[str] = "Hotel Lobby"
    session_id:      Optional[str] = None

@app.post("/book")
async def book_taxi(req: BookRequest):
    guest = GuestData(
        guest_name=req.guest_name, guest_phone=req.guest_phone,
        room_number=req.room_number, destination=req.destination,
        pickup_time=req.pickup_time or "now",
        pickup_location=req.pickup_location or "Hotel Lobby",
    )
    result = worker.book(guest)
    return {
        "success": result.success, "booking_id": result.booking_id,
        "sms_sent": result.sms_sent, "message": result.message,
        "driver": result.driver,
    }


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "4.0"}