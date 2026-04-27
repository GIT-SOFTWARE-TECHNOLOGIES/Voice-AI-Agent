"""
hubspot_taxi_poller.py
━━━━━━━━━━━━━━━━━━━━━━
Polls HubSpot Taxi Request object every N seconds.
For each pending request:
  1. Fetch guest details from Hotel Guest object by room_number
  2. Book taxi via TaxiWorker
  3. Update status → booked / failed in HubSpot

Run:
  python run_taxi_poller.py
"""

import logging
import time
import os
from dotenv import load_dotenv

load_dotenv()

from src.taxi.hubspot_client import (
    fetch_pending_taxi_requests,
    update_taxi_status,
    fetch_guest,
)
from src.taxi.taxi_worker import TaxiWorker, GuestData

log           = logging.getLogger("HubSpotTaxiPoller")
POLL_INTERVAL = int(os.getenv("HUBSPOT_TAXI_POLL_INTERVAL", "30"))


class HubSpotTaxiPoller:

    def __init__(self):
        self.worker       = TaxiWorker()
        self._seen_ids    = set()   # avoid double-booking in same session

    def process_one(self, taxi_req) -> None:
        """Process a single pending taxi request."""

        hubspot_id = taxi_req.hubspot_id

        # Skip if already processed in this session
        if hubspot_id in self._seen_ids:
            return

        log.info(
            f"Processing taxi request {hubspot_id} | "
            f"Room: {taxi_req.room_number} | "
            f"To: {taxi_req.destination} | "
            f"At: {taxi_req.pickup_time}"
        )

        # Mark as processing immediately — prevents other pollers picking it up
        update_taxi_status(hubspot_id, "processing")
        self._seen_ids.add(hubspot_id)

        # Validate required fields
        if not taxi_req.room_number:
            log.error(f"Taxi request {hubspot_id} missing room_number — marking failed")
            update_taxi_status(hubspot_id, "failed")
            return

        # Fetch guest from Hotel Guest object by room number
        crm = fetch_guest(room_number=taxi_req.room_number)

        if not crm.found:
            log.error(f"Guest not found for room {taxi_req.room_number} — marking failed")
            update_taxi_status(hubspot_id, "failed")
            return

        if not crm.guest_phone:
            log.error(f"Guest found but no phone for room {taxi_req.room_number} — marking failed")
            update_taxi_status(hubspot_id, "failed")
            return

        # Build guest data
        guest = GuestData(
            guest_name      = crm.guest_name  or "Guest",
            guest_phone     = crm.guest_phone,
            guest_email     = crm.guest_email,
            room_number     = crm.room_number or taxi_req.room_number,
            destination     = taxi_req.destination or "Unknown",
            pickup_time     = taxi_req.pickup_time  or "now",
            pickup_location = "Hotel Lobby",
        )

        # Book taxi
        result = self.worker.book(guest)

        if result.success:
            log.info(
                f"BOOKED! ID: {result.booking_id} | "
                f"Guest: {guest.guest_name} | "
                f"SMS: {result.sms_sent} | "
                f"Email: {result.email_sent}"
            )
            update_taxi_status(hubspot_id, "booked")
        else:
            log.error(f"Booking failed for taxi request {hubspot_id}")
            update_taxi_status(hubspot_id, "failed")

    def poll_once(self) -> None:
        """Single poll cycle — fetch and process all pending requests."""
        pending = fetch_pending_taxi_requests()
        if not pending:
            log.debug("No pending taxi requests")
            return
        for taxi_req in pending:
            try:
                self.process_one(taxi_req)
            except Exception as e:
                log.error(f"Error processing {taxi_req.hubspot_id}: {e}", exc_info=True)

    def run_forever(self) -> None:
        """Poll HubSpot in a loop forever."""
        log.info(f"HubSpot Taxi Poller started — polling every {POLL_INTERVAL}s")
        while True:
            try:
                self.poll_once()
            except Exception as e:
                log.error(f"Poll cycle error: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL)