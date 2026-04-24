"""
test_poller_direct.py
=====================
Tests the full taxi booking flow WITHOUT HubSpot Taxi object.
Simulates a fake taxi request record directly.

Flow tested:
  fake taxi record (room+destination+time)
        ↓
  fetch_guest(room_number)  ← real HubSpot call
        ↓
  TaxiWorker.book()         ← real SMS + Email
"""

import logging
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s — %(message)s",
    datefmt="%H:%M:%S"
)

from src.taxi.hubspot_client import fetch_guest
from src.taxi.taxi_worker import TaxiWorker, GuestData

def test_booking(room_number, destination, pickup_time):
    print(f"\n{'='*50}")
    print(f"Testing: Room={room_number} | To={destination} | At={pickup_time}")
    print(f"{'='*50}")

    # Step 1 — fetch guest from HubSpot by room number
    print("\n[STEP 1] Fetching guest from HubSpot...")
    crm = fetch_guest(room_number=room_number)

    if not crm.found:
        print(f"❌ Guest not found for room {room_number}")
        return

    print(f"✅ Guest found: {crm.guest_name} | Phone: {crm.guest_phone} | Email: {crm.guest_email}")

    if not crm.guest_phone:
        print("❌ No phone number — cannot send SMS")
        return

    # Step 2 — build guest data
    print("\n[STEP 2] Building booking details...")
    guest = GuestData(
        guest_name      = crm.guest_name  or "Guest",
        guest_phone     = crm.guest_phone,
        guest_email     = crm.guest_email,
        room_number     = crm.room_number or room_number,
        destination     = destination,
        pickup_time     = pickup_time,
        pickup_location = "Hotel Lobby",
    )
    print(f"✅ Guest: {guest.guest_name} | Room: {guest.room_number} | To: {guest.destination} | At: {guest.pickup_time}")

    # Step 3 — book taxi
    print("\n[STEP 3] Booking taxi...")
    worker = TaxiWorker()
    result = worker.book(guest)

    # Step 4 — results
    print(f"\n{'='*50}")
    if result.success:
        print(f"✅ BOOKED! Booking ID : {result.booking_id}")
        print(f"   Driver            : {result.driver['name']} | {result.driver['vehicle']}")
        print(f"   SMS sent          : {result.sms_sent}")
        print(f"   Email sent        : {result.email_sent}")
    else:
        print(f"❌ Booking failed")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    # ── Test 1 — your existing guest room 202
    test_booking(
        room_number = "699",
        destination = "Airport",
        pickup_time = "6 PM"
    )

    # ── Test 2 — different destination
    test_booking(
        room_number = "202",
        destination = "Brigade Road",
        pickup_time = "8:30 AM"
    )