"""
hubspot_client.py
━━━━━━━━━━━━━━━━━
Fetches guest data from HubSpot CRM (custom Hotel Guest object).

Lookup order:
  1. Search Hotel Guest object by room_number
  2. If not found, search by phone number
  3. Returns GuestLookupResult with found=True/False

Required env vars:
  HUBSPOT_API_KEY       — your HubSpot private app token
  HUBSPOT_OBJECT_TYPE   — custom object API name (default: p245858895_hotel_guest)
  HUBSPOT_ROOM_PROPERTY — property name for room number (default: room_number)
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("HubSpotClient")

# ── Config ─────────────────────────────────────────────────────────────────────

HUBSPOT_API_KEY       = os.getenv("HUBSPOT_API_KEY", "")
HUBSPOT_BASE_URL      = "https://api.hubapi.com"
HUBSPOT_ROOM_PROPERTY = os.getenv("HUBSPOT_ROOM_PROPERTY", "room_number")
HUBSPOT_OBJECT_TYPE   = os.getenv("HUBSPOT_OBJECT_TYPE", "p245858895_hotel_guest")

# Properties to fetch from Hotel Guest custom object
FETCH_PROPERTIES = ["full_name", "email", "phone", HUBSPOT_ROOM_PROPERTY]

HEADERS = lambda: {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type":  "application/json",
}


# ── Result model ───────────────────────────────────────────────────────────────

@dataclass
class GuestLookupResult:
    found:       bool
    guest_name:  Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    room_number: Optional[str] = None
    hubspot_id:  Optional[str] = None
    error:       Optional[str] = None


# ── Internal helpers ───────────────────────────────────────────────────────────

def _parse_guest(record: dict, fallback_room: Optional[str] = None, fallback_phone: Optional[str] = None) -> GuestLookupResult:
    """Extract guest fields from a HubSpot custom object record."""
    props = record.get("properties", {})

    # full_name is the custom property name on Hotel Guest object
    name  = props.get("full_name", "") or None
    email = props.get("email", "") or None

    phone = props.get("phone", "") or fallback_phone or None
    if phone:
        phone = phone.replace("+91", "").replace("-", "").replace(" ", "").strip()
        if phone.startswith("91") and len(phone) == 12:
            phone = phone[2:]

    room = props.get(HUBSPOT_ROOM_PROPERTY, "") or fallback_room or None

    return GuestLookupResult(
        found       = True,
        guest_name  = name,
        guest_email = email,
        guest_phone = phone,
        room_number = room,
        hubspot_id  = record.get("id"),
    )


def _search_guests(filter_property: str, filter_value: str) -> Optional[dict]:
    """
    Search HubSpot custom Hotel Guest object using the CRM Search API.
    Returns the first matching record, or None.
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/{HUBSPOT_OBJECT_TYPE}/search"
    body = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": filter_property,
                        "operator":     "EQ",
                        "value":        filter_value,
                    }
                ]
            }
        ],
        "properties": FETCH_PROPERTIES,
        "limit": 1,
    }

    try:
        r = requests.post(url, json=body, headers=HEADERS(), timeout=10)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        return results[0] if results else None
    except requests.exceptions.HTTPError as e:
        log.error(f"HubSpot search HTTP error ({filter_property}={filter_value}): {e} | {e.response.text if e.response else ''}")
        return None
    except Exception as e:
        log.error(f"HubSpot search failed ({filter_property}={filter_value}): {e}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_guest_by_room(room_number: str) -> GuestLookupResult:
    """Look up a guest by their room number in Hotel Guest custom object."""
    if not HUBSPOT_API_KEY:
        log.warning("HUBSPOT_API_KEY not set — returning not found")
        return GuestLookupResult(found=False, error="HUBSPOT_API_KEY not configured")

    log.info(f"HubSpot: searching Hotel Guest by room_number={room_number}")
    record = _search_guests(HUBSPOT_ROOM_PROPERTY, room_number)

    if record:
        result = _parse_guest(record, fallback_room=room_number)
        log.info(f"HubSpot: found guest '{result.guest_name}' for room {room_number}")
        return result

    log.warning(f"HubSpot: no guest found for room {room_number}")
    return GuestLookupResult(found=False, room_number=room_number)


def fetch_guest_by_phone(phone: str) -> GuestLookupResult:
    """Look up a guest by phone number in Hotel Guest custom object."""
    if not HUBSPOT_API_KEY:
        return GuestLookupResult(found=False, error="HUBSPOT_API_KEY not configured")

    normalized = phone.replace("+91", "").replace("-", "").replace(" ", "").strip()
    if normalized.startswith("91") and len(normalized) == 12:
        normalized = normalized[2:]

    log.info(f"HubSpot: searching Hotel Guest by phone={normalized}")

    record = _search_guests("phone", normalized)
    if not record:
        record = _search_guests("phone", f"+91{normalized}")

    if record:
        result = _parse_guest(record, fallback_phone=normalized)
        log.info(f"HubSpot: found guest '{result.guest_name}' by phone {normalized}")
        return result

    log.warning(f"HubSpot: no guest found for phone {normalized}")
    return GuestLookupResult(found=False, guest_phone=normalized)


def fetch_guest(room_number: Optional[str] = None, phone: Optional[str] = None) -> GuestLookupResult:
    """
    Fetch guest from HubSpot Hotel Guest object.
    Tries room_number first, then phone as fallback.
    """
    result = GuestLookupResult(found=False)

    if room_number:
        result = fetch_guest_by_room(room_number)

    if not result.found and phone:
        result = fetch_guest_by_phone(phone)

    return result