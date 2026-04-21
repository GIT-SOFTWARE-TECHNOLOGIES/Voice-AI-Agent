"""
hubspot_connector.py
--------------------
Takes the validated JSON from the extraction layer and creates
a Hotel Service Request record in HubSpot via its REST API.

Supports all 4 service types:
  - laundry
  - room_service
  - food_and_beverages
  - maintenance
"""

import os
import json
import requests


# Once you run the schema setup script (see bottom of this file),
# HubSpot assigns your custom object a unique type ID like:
# "p12345678_hotel_service_request"
# Paste that value in your .env as HUBSPOT_OBJECT_TYPE.
# Until then, the connector will raise a clear error telling you what to do.

HUBSPOT_BASE_URL = "https://api.hubapi.com"


def get_headers() -> dict:
    """
    Builds auth headers for every HubSpot API request.
    HubSpot uses Bearer token auth via Private Apps —
    more secure than the old API key system they deprecated in 2022.
    """
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise EnvironmentError(
            "HUBSPOT_ACCESS_TOKEN is not set. Add it to your .env file.\n"
            "Get it from: HubSpot → Settings → Integrations → Private Apps."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_object_type() -> str:
    """
    Returns the custom object type string HubSpot assigned after schema creation.
    This value is unique per HubSpot account — you get it by running
    create_schema() once and copying the returned object type.
    """
    object_type = os.environ.get("HUBSPOT_OBJECT_TYPE")
    if not object_type:
        raise EnvironmentError(
            "HUBSPOT_OBJECT_TYPE is not set.\n"
            "Run: python -m src.crm.hubspot_connector --setup\n"
            "Then copy the object type from the output and add it to your .env."
        )
    return object_type


def build_payload(data: dict) -> dict:
    """
    Translates our CRM-agnostic JSON into HubSpot's expected payload format.

    HubSpot wraps all field values inside a "properties" key.
    Field names must exactly match the property names defined in the schema.
    Items (a list) is serialised as a JSON string since HubSpot
    text fields don't support nested structures natively.
    """
    return {
        "properties": {
            "room_number":       data.get("room_number"),
            "service_type":      data.get("service_type"),
            "items":             json.dumps(data.get("items", [])),
            "pickup_time":       data.get("pickup_time"),
            "delivery_deadline": data.get("delivery_deadline"),
            "special_notes":     data.get("special_notes"),
            "urgency":           data.get("urgency", "normal"),
            "status":            data.get("status", "pending"),
            "confidence":        data.get("confidence"),
            "session_id":        data.get("session_id"),   # ← new
            "room_name":         data.get("room_name"),
        }
    }


def update_schema():
    """Add session_id and room_name fields to existing schema."""
    headers  = get_headers()
    object_type = get_object_type()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/properties/{object_type}"

    new_properties = [
        {"name": "session_id", "label": "Session ID", "type": "string", "fieldType": "text", "groupName": "hotel_service_request_information"},
        {"name": "room_name",  "label": "Room Name",  "type": "string", "fieldType": "text", "groupName": "hotel_service_request_information"},
    ]

    for prop in new_properties:
        response = requests.post(endpoint, headers=headers, json=prop)
        if response.ok:
            print(f"  ✓ Added property: {prop['name']}")
        else:
            print(f"  ✗ Failed: {prop['name']} — {response.text}")

def push(data: dict) -> dict:
    """
    Main function — creates a Hotel Service Request record in HubSpot.
    Returns the created record as returned by HubSpot's API.
    """
    object_type = get_object_type()
    endpoint    = f"{HUBSPOT_BASE_URL}/crm/v3/objects/{object_type}"
    headers     = get_headers()
    payload     = build_payload(data)

    response = requests.post(endpoint, headers=headers, json=payload)

    if not response.ok:
        raise ConnectionError(
            f"HubSpot API returned {response.status_code}.\n"
            f"Response: {response.text}"
        )

    created_record = response.json()
    print(f"  ✓ Record created in HubSpot. ID: {created_record.get('id')}")
    return created_record


# ── One-time schema setup ─────────────────────────────────────────────────────

def create_schema() -> str:
    """
    Registers the Hotel Service Request custom object schema in HubSpot.
    Run this ONCE before using push() for the first time.

    Returns the object type string you need to save in .env as HUBSPOT_OBJECT_TYPE.
    """
    headers  = get_headers()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/schemas"

    schema = {
        "name": "hotel_service_request",
        "labels": {
            "singular": "Hotel Service Request",
            "plural":   "Hotel Service Requests",
        },
        "primaryDisplayProperty": "room_number",
        "properties": [
            # Core identification
            {"name": "room_number",       "label": "Room Number",       "type": "string", "fieldType": "text"},
            {"name": "service_type",      "label": "Service Type",      "type": "string", "fieldType": "text"},

            # Request details
            {"name": "items",             "label": "Items",             "type": "string", "fieldType": "text"},
            {"name": "pickup_time",       "label": "Pickup Time",       "type": "string", "fieldType": "text"},
            {"name": "delivery_deadline", "label": "Delivery Deadline", "type": "string", "fieldType": "text"},
            {"name": "special_notes",     "label": "Special Notes",     "type": "string", "fieldType": "text"},

            # Status fields
            {"name": "urgency",           "label": "Urgency",           "type": "string", "fieldType": "text"},
            {"name": "status",            "label": "Status",            "type": "string", "fieldType": "text"},
            {"name": "confidence",        "label": "Confidence",        "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }

    print("Creating Hotel Service Request schema in HubSpot...")
    response = requests.post(endpoint, headers=headers, json=schema)

    if response.status_code == 201:
        result      = response.json()
        object_type = result.get("objectTypeId") or result.get("name")
        print(f"\n✓ Schema created successfully!")
        print(f"\nAdd this to your .env file:")
        print(f"  HUBSPOT_OBJECT_TYPE={object_type}")
        return object_type

    elif response.status_code == 409:
        print("Schema already exists — no action needed.")
        print("If you don't have HUBSPOT_OBJECT_TYPE in your .env, check HubSpot")
        print("under Settings → Data Model → Custom Objects for the object type ID.")
        return ""

    else:
        raise ConnectionError(
            f"Schema creation failed with {response.status_code}.\n"
            f"Response: {response.text}"
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()


    if "--update-schema" in sys.argv:
        update_schema()

    # Run with --setup flag to create the schema first
    # Run without flags to test pushing a record
    if "--setup" in sys.argv:
        create_schema()

    else:
        # Test each of the 4 service types to make sure all work
        test_cases = [
            {
                "label": "Laundry",
                "data": {
                    "room_number": "302",
                    "service_type": "laundry",
                    "items": [{"name": "shirt", "quantity": 2}, {"name": "trousers", "quantity": 1}],
                    "pickup_time": "within the hour",
                    "delivery_deadline": "tomorrow before 10am",
                    "special_notes": None,
                    "urgency": "normal",
                    "status": "pending",
                    "confidence": "high",
                }
            },
            {
                "label": "Room Service",
                "data": {
                    "room_number": "215",
                    "service_type": "room_service",
                    "items": [{"name": "bath towel", "quantity": 2}, {"name": "pillow", "quantity": 2}],
                    "pickup_time": "after 11am",
                    "delivery_deadline": None,
                    "special_notes": "Also needs toiletry replacement — shampoo and body wash",
                    "urgency": "normal",
                    "status": "pending",
                    "confidence": "high",
                }
            },
            {
                "label": "Food & Beverages",
                "data": {
                    "room_number": "408",
                    "service_type": "food_and_beverages",
                    "items": [
                        {"name": "club sandwich", "quantity": 1},
                        {"name": "tomato soup", "quantity": 1},
                        {"name": "still water (large)", "quantity": 1},
                        {"name": "chocolate cake", "quantity": 1},
                    ],
                    "pickup_time": None,
                    "delivery_deadline": "within 30 minutes",
                    "special_notes": "Nut allergy — all items must be completely nut-free. Charge to room.",
                    "urgency": "normal",
                    "status": "pending",
                    "confidence": "high",
                }
            },
            {
                "label": "Maintenance",
                "data": {
                    "room_number": "517",
                    "service_type": "maintenance",
                    "items": [
                        {"name": "AC not cooling", "quantity": 1},
                        {"name": "bathroom light out", "quantity": 1},
                    ],
                    "pickup_time": "as soon as possible",
                    "delivery_deadline": "within 20 minutes",
                    "special_notes": "Guest will be in room for next 2 hours. AC blowing warm air only.",
                    "urgency": "urgent",
                    "status": "pending",
                    "confidence": "high",
                }
            },
        ]

        print(f"Testing HubSpot connector with all 4 service types...\n")
        for case in test_cases:
            print(f"── {case['label']} ──")
            try:
                record = push(case["data"])
                print(f"  Done. Record ID: {record.get('id')}\n")
            except Exception as e:
                print(f"  ✗ Failed: {e}\n")