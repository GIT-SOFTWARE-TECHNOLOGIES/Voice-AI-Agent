"""
taxi_worker.py — Hotel Taxi Worker v4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stateless booking worker.
Sends SMS via MSG91 OTP API and confirmation email via SendGrid.

Environment variables (.env):
  MSG91_AUTH_KEY          - MSG91 auth key
  MSG91_SENDER_ID         - Sender ID (e.g. ASTRJY)
  MSG91_TEMPLATE_ID_GUEST - MSG91 OTP template ID
  SENDGRID_API_KEY        - SendGrid API key (starts with SG.)
  SENDGRID_FROM_EMAIL     - Verified sender email in SendGrid
"""

import os
import uuid
import logging
from dataclasses import dataclass
from typing import Optional, List

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("TaxiWorker")

# ── Config ─────────────────────────────────────────────────────────────────────

MSG91_AUTH_KEY      = os.getenv("MSG91_AUTH_KEY", "")
MSG91_SENDER_ID     = os.getenv("MSG91_SENDER_ID", "")
MSG91_TMPL_GUEST    = os.getenv("MSG91_TEMPLATE_ID_GUEST", "")

SENDGRID_API_KEY    = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "")

# ── Driver pool ────────────────────────────────────────────────────────────────

DRIVER_POOL: List[dict] = [
    {"name": "Rajesh Kumar", "phone": "9123456789", "vehicle": "KA 01 AB 1234"},
    {"name": "Suresh Patil", "phone": "9234567890", "vehicle": "KA 02 CD 5678"},
    {"name": "Mohan Das",    "phone": "9345678901", "vehicle": "KA 03 EF 9012"},
]


# ── Guest data model ───────────────────────────────────────────────────────────

@dataclass
class GuestData:
    guest_name:      str
    guest_phone:     str
    room_number:     str
    destination:     str
    guest_email:     Optional[str] = None
    pickup_time:     str           = "now"
    pickup_location: str           = "Hotel Lobby"


# ── Booking result ─────────────────────────────────────────────────────────────

@dataclass
class BookingResult:
    success:     bool
    booking_id:  Optional[str]  = None
    driver:      Optional[dict] = None
    sms_sent:    bool           = False
    email_sent:  bool           = False
    message:     str            = ""


# ── MSG91 OTP SMS ──────────────────────────────────────────────────────────────

def send_confirmation_sms(booking_id: str, guest: GuestData, driver: dict) -> bool:
    """Send SMS via MSG91 OTP API."""
    import random
    if not MSG91_AUTH_KEY or not MSG91_TMPL_GUEST:
        log.warning("MSG91 credentials not set — skipping SMS")
        return False

    # Normalize phone — remove any existing country code
    phone = guest.guest_phone.replace("+91", "").replace(" ", "").strip()
    if phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]

    # MSG91 OTP must be numeric only — generate 6 digit numeric code for SMS
    numeric_otp = str(random.randint(100000, 999999))

    # Per MSG91 docs: template_id, mobile, authkey go in URL params
    # OTP variable goes in JSON body as ##otp## param
    url = f"https://control.msg91.com/api/v5/otp?template_id={MSG91_TMPL_GUEST}&mobile=91{phone}&authkey={MSG91_AUTH_KEY}"
    headers = {
        "content-type": "application/json",
        "Content-Type": "application/JSON",
    }
    payload = {
        "otp": numeric_otp,
    }

    try:
        r    = requests.post(url, json=payload, headers=headers, timeout=10)
        data = r.json()
        log.info(f"MSG91 response: {data}")
        log.info(f"MSG91 OTP sent: mobile=91{phone} | otp={numeric_otp}")
        if data.get("type") == "success":
            log.info(f"SMS sent → {phone} | Booking {booking_id}")
            return True
        log.error(f"MSG91 error: {data}")
        return False
    except Exception as e:
        log.error(f"MSG91 failed: {e}")
        return False


# ── SendGrid Email ─────────────────────────────────────────────────────────────

def send_confirmation_email(booking_id: str, guest: GuestData, driver: dict) -> bool:
    """Send booking confirmation email via SendGrid."""
    if not SENDGRID_API_KEY:
        log.warning("SENDGRID_API_KEY not set — skipping email")
        return False

    if not guest.guest_email:
        log.warning(f"No email for guest {guest.guest_name} — skipping email")
        return False

    if not SENDGRID_FROM_EMAIL:
        log.warning("SENDGRID_FROM_EMAIL not set — skipping email")
        return False

    url     = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type":  "application/json",
    }

    subject = f"Taxi Booking Confirmed — {booking_id}"
    body    = f"""Dear {guest.guest_name},

Your taxi booking is confirmed!

Booking Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Booking ID     : {booking_id}
Room Number    : {guest.room_number}
Destination    : {guest.destination}
Pickup From    : {guest.pickup_location}
Pickup Time    : {guest.pickup_time}

Driver Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Driver Name    : {driver['name']}
Driver Phone   : {driver['phone']}
Vehicle Number : {driver['vehicle']}

Please be ready at {guest.pickup_location} at {guest.pickup_time}.

Have a safe journey!
Grand View Hotel
"""

    payload = {
        "personalizations": [
            {
                "to":      [{"email": guest.guest_email, "name": guest.guest_name}],
                "subject": subject,
            }
        ],
        "from":    {"email": SENDGRID_FROM_EMAIL, "name": "Grand View Hotel"},
        "content": [{"type": "text/plain", "value": body}],
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code == 202:
            log.info(f"Email sent → {guest.guest_email} | Booking {booking_id}")
            return True
        log.error(f"SendGrid error: {r.status_code} | {r.text}")
        return False
    except Exception as e:
        log.error(f"SendGrid failed: {e}")
        return False


# ── TaxiWorker ─────────────────────────────────────────────────────────────────

class TaxiWorker:
    """Stateless worker. Sends SMS + Email on booking."""

    def book(self, guest: GuestData) -> BookingResult:
        booking_id = str(uuid.uuid4())[:8].upper()
        driver     = DRIVER_POOL[0]

        log.info(
            f"[{booking_id}] "
            f"Guest: {guest.guest_name} | Room: {guest.room_number} | "
            f"Phone: {guest.guest_phone} | Email: {guest.guest_email} | "
            f"To: {guest.destination} | At: {guest.pickup_time} | "
            f"Driver: {driver['name']}"
        )

        sms_ok   = send_confirmation_sms(booking_id, guest, driver)
        email_ok = send_confirmation_email(booking_id, guest, driver)

        notifications = []
        if sms_ok:   notifications.append(f"SMS to {guest.guest_phone}")
        if email_ok: notifications.append(f"email to {guest.guest_email}")
        notif_text = " and ".join(notifications) if notifications else "no notifications sent"

        return BookingResult(
            success    = True,
            booking_id = booking_id,
            driver     = driver,
            sms_sent   = sms_ok,
            email_sent = email_ok,
            message    = (
                f"Your taxi is confirmed! "
                f"Driver {driver['name']} will pick you up from "
                f"{guest.pickup_location} at {guest.pickup_time}. "
                f"Vehicle: {driver['vehicle']}. "
                f"Driver's contact: {driver['phone']}. "
                f"Booking ID: {booking_id}. "
                f"Confirmation sent via {notif_text}. "
                f"Have a safe journey, {guest.guest_name}!"
            )
        )