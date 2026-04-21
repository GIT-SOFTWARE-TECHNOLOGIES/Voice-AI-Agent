"""
taxi_client.py
==============
Called on every user turn from TranscriptManager.
Directly calls taxi worker functions — no HTTP, no separate server.
"""

import logging
import threading

# ── Dedicated Taxi Worker Logger ───────────────────────────────────────────────
# Logs show as [TAXI] in docker logs — filter with:
#   docker logs personaplex-agent -f 2>&1 | grep "\[TAXI\]"

taxi_log = logging.getLogger("taxi_worker")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "[TAXI] %(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S"
))
taxi_log.addHandler(handler)
taxi_log.setLevel(logging.INFO)


def trigger_taxi_worker(turns: list, session_id: str):
    """
    Process transcript through taxi worker.
    Runs in background thread — never blocks the agent.
    """
    def _run():
        try:
            from src.taxi.transcript_parser import parse_transcript
            from src.taxi.hubspot_client import fetch_guest
            from src.taxi.taxi_worker import TaxiWorker, GuestData

            # Step 1 — parse transcript
            parsed = parse_transcript(turns)

            if parsed.booking_cancelled:
                taxi_log.info("Booking cancelled by guest")
                return

            if not parsed.has_taxi_intent:
                return  # not a taxi request — do nothing

            if not parsed.booking_confirmed:
                missing = parsed.missing_fields
                if missing:
                    taxi_log.info(f"Collecting — missing: {missing}")
                return

            if parsed.missing_fields:
                taxi_log.info(f"Confirmed but still missing: {parsed.missing_fields}")
                return

            # Step 2 — fetch guest from HubSpot CRM
            taxi_log.info(f"Fetching guest from HubSpot for room: {parsed.room_number}")
            crm = fetch_guest(
                room_number=parsed.room_number,
                phone=parsed.guest_phone,
            )

            if not crm.found:
                taxi_log.error(f"Guest not found in CRM for room {parsed.room_number}")
                return

            if not crm.guest_phone:
                taxi_log.error("Guest found but no phone number in CRM")
                return

            taxi_log.info(f"CRM guest found: {crm.guest_name} | Phone: {crm.guest_phone} | Email: {crm.guest_email}")

            # Step 3 — book taxi + send SMS + email
            guest = GuestData(
                guest_name      = crm.guest_name or "Guest",
                guest_phone     = crm.guest_phone,
                guest_email     = crm.guest_email,
                room_number     = crm.room_number or parsed.room_number or "N/A",
                destination     = parsed.destination or "Unknown",
                pickup_time     = parsed.pickup_time or "now",
                pickup_location = "Hotel Lobby",
            )

            taxi_log.info(f"Booking taxi — Guest: {guest.guest_name} | Room: {guest.room_number} | To: {guest.destination} | At: {guest.pickup_time}")

            result = TaxiWorker().book(guest)

            taxi_log.info(
                f"BOOKED! "
                f"Booking ID: {result.booking_id} | "
                f"Guest: {guest.guest_name} | "
                f"Room: {guest.room_number} | "
                f"SMS: {result.sms_sent} | "
                f"Email: {result.email_sent}"
            )

        except Exception as e:
            taxi_log.error(f"Worker error: {e}", exc_info=True)

    threading.Thread(target=_run, daemon=True).start()