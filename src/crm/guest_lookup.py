"""
guest_lookup.py
---------------
Utility to look up a hotel guest from HubSpot by room number.
Used by the taxi/SMS worker to get the guest's phone number
before sending a confirmation SMS.

Usage (as a module):
    from src.crm.guest_lookup import get_guest_by_room

Usage (standalone test):
    python guest_lookup.py 408
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

HUBSPOT_BASE_URL = "https://api.hubapi.com"


def get_headers() -> dict:
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise EnvironmentError("HUBSPOT_ACCESS_TOKEN is not set.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_object_type() -> str:
    object_type = os.environ.get("HUBSPOT_GUEST_OBJECT_TYPE")
    if not object_type:
        raise EnvironmentError(
            "HUBSPOT_GUEST_OBJECT_TYPE is not set in .env.\n"
            "Run: python guest_seeder.py --setup to create the schema first."
        )
    return object_type


def get_guest_by_room(room_number: str) -> dict | None:
    """
    Searches HubSpot for a guest record matching the given room number.

    Returns a dict with guest details if found, or None if no match.

    Example return value:
    {
        "id": "12345",
        "room_number": "408",
        "full_name": "Emily Hartmann",
        "phone": "+14155550408",
        "email": "emily.hartmann@email.com",
        "check_in": "2026-04-17",
        "check_out": "2026-04-22"
    }
    """
    headers     = get_headers()
    object_type = get_object_type()
    endpoint    = f"{HUBSPOT_BASE_URL}/crm/v3/objects/{object_type}/search"

    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "room_number",
                        "operator": "EQ",
                        "value": str(room_number),
                    }
                ]
            }
        ],
        "properties": ["room_number", "full_name", "phone", "email", "check_in", "check_out"],
        "limit": 1,
    }

    response = requests.post(endpoint, headers=headers, json=payload)

    if not response.ok:
        raise ConnectionError(
            f"HubSpot search failed with {response.status_code}.\n"
            f"Response: {response.text}"
        )

    results = response.json().get("results", [])

    if not results:
        return None

    record = results[0]
    props  = record.get("properties", {})

    return {
        "id":          record.get("id"),
        "room_number": props.get("room_number"),
        "full_name":   props.get("full_name"),
        "phone":       props.get("phone"),
        "email":       props.get("email"),
        "check_in":    props.get("check_in"),
        "check_out":   props.get("check_out"),
    }


def get_phone_by_room(room_number: str) -> str:
    """
    Convenience wrapper — returns just the phone number for a room.
    Raises ValueError if the room is not found or has no phone on record.
    """
    guest = get_guest_by_room(room_number)

    if not guest:
        raise ValueError(f"No guest found for room {room_number}.")

    phone = guest.get("phone")
    if not phone:
        raise ValueError(f"Guest in room {room_number} has no phone number on record.")

    return phone


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    room = sys.argv[1] if len(sys.argv) > 1 else "408"

    print(f"Looking up guest for room {room}...\n")

    try:
        guest = get_guest_by_room(room)
        if guest:
            print("Guest found:")
            print(json.dumps(guest, indent=2))
        else:
            print(f"No guest found for room {room}.")
    except Exception as e:
        print(f"Error: {e}")