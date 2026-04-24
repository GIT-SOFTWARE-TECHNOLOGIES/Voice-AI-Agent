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


def get_object_type(service_type: str) -> str:
    env_map = {
        "taxi":        "HUBSPOT_TAXI_OBJECT_TYPE",
        "laundry":     "HUBSPOT_LAUNDRY_OBJECT_TYPE",
        "food_order":  "HUBSPOT_FOOD_OBJECT_TYPE",
        "maintenance": "HUBSPOT_MAINTENANCE_OBJECT_TYPE",
        "payment":     "HUBSPOT_PAYMENT_OBJECT_TYPE",   
    }
    env_key = env_map.get(service_type)
    if not env_key:
        raise ValueError(f"Unknown service_type: '{service_type}'")
    value = os.environ.get(env_key)
    if not value:
        raise EnvironmentError(f"{env_key} is not set in .env")
    return value


def build_taxi_payload(data):
    return {"properties": {
        "room_number":  data.get("room_number"),
        "destination":  data.get("destination"),
        "pickup_time":  data.get("pickup_time"),
        "status":       data.get("status", "pending"),
    }}

def build_laundry_payload(data):
    return {"properties": {
        "room_number":       data.get("room_number"),
        "items":             json.dumps(data.get("items", [])),
        "pickup_time":       data.get("pickup_time"),
        "delivery_deadline": data.get("delivery_deadline"),
        "special_notes":     data.get("special_notes"),
        "urgency":           data.get("urgency", "normal"),
        "status":            data.get("status", "pending"),
    }}

def build_food_payload(data):
    return {"properties": {
        "room_number":       data.get("room_number"),
        "items":             json.dumps(data.get("items", [])),
        "delivery_deadline": data.get("delivery_deadline"),
        "special_notes":     data.get("special_notes"),
        "urgency":           data.get("urgency", "normal"),
        "status":            data.get("status", "pending"),
    }}

def build_payment_payload(data):
    return {"properties": {
        "room_number":    data.get("room_number"),
        "amount":         data.get("amount"),
        "payment_method": data.get("payment_method"),
        "payment_status": data.get("payment_status"),
        "status":         data.get("status", "pending"),
    }}

def build_maintenance_payload(data):
    return {"properties": {
        "room_number":       data.get("room_number"),
        "issue_description": data.get("issue_description"),
        "urgency":           data.get("urgency", "normal"),
        "pickup_time":       data.get("pickup_time"),
        "status":            data.get("status", "pending"),
    }}


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

PAYLOAD_BUILDERS = {
    "taxi":        build_taxi_payload,
    "laundry":     build_laundry_payload,
    "food_order":  build_food_payload,
    "maintenance": build_maintenance_payload,
    "payment":     build_payment_payload,
}

def push(data: dict) -> dict:
    service_type = data.get("service_type")
    object_type  = get_object_type(service_type)
    endpoint     = f"{HUBSPOT_BASE_URL}/crm/v3/objects/{object_type}"
    payload      = PAYLOAD_BUILDERS[service_type](data)

    response = requests.post(endpoint, headers=get_headers(), json=payload)
    if not response.ok:
        raise ConnectionError(
            f"HubSpot API returned {response.status_code}.\n"
            f"Response: {response.text}"
        )
    created_record = response.json()
    print(f"  ✓ {service_type} record created. ID: {created_record.get('id')}")
    return created_record


# ── One-time schema setup ─────────────────────────────────────────────────────

def create_taxi_schema() -> str:
    headers  = get_headers()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/schemas"
    schema = {
        "name": "taxi_request",
        "labels": {"singular": "Taxi Request", "plural": "Taxi Requests"},
        "primaryDisplayProperty": "room_number",
        "properties": [
            {"name": "room_number",  "label": "Room Number",  "type": "string", "fieldType": "text"},
            {"name": "destination",  "label": "Destination",  "type": "string", "fieldType": "text"},
            {"name": "pickup_time",  "label": "Pickup Time",  "type": "string", "fieldType": "text"},
            {"name": "status",       "label": "Status",       "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }
    return _post_schema(schema, "HUBSPOT_TAXI_OBJECT_TYPE")


def create_payment_schema() -> str:
    schema = {
        "name": "payment_request",
        "labels": {"singular": "Payment Request", "plural": "Payment Requests"},
        "primaryDisplayProperty": "room_number",
        "properties": [
            {"name": "room_number",     "label": "Room Number",     "type": "string", "fieldType": "text"},
            {"name": "amount",          "label": "Amount",          "type": "string", "fieldType": "text"},
            {"name": "payment_method",  "label": "Payment Method",  "type": "string", "fieldType": "text"},
            {"name": "payment_status",  "label": "Payment Status",  "type": "string", "fieldType": "text"},
            {"name": "status",          "label": "Status",          "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }
    return _post_schema(schema, "HUBSPOT_PAYMENT_OBJECT_TYPE")


def create_laundry_schema() -> str:
    headers  = get_headers()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/schemas"
    schema = {
        "name": "laundry_request",
        "labels": {"singular": "Laundry Request", "plural": "Laundry Requests"},
        "primaryDisplayProperty": "room_number",
        "properties": [
            {"name": "room_number",       "label": "Room Number",       "type": "string", "fieldType": "text"},
            {"name": "items",             "label": "Items",             "type": "string", "fieldType": "text"},
            {"name": "pickup_time",       "label": "Pickup Time",       "type": "string", "fieldType": "text"},
            {"name": "delivery_deadline", "label": "Delivery Deadline", "type": "string", "fieldType": "text"},
            {"name": "special_notes",     "label": "Special Notes",     "type": "string", "fieldType": "text"},
            {"name": "urgency",           "label": "Urgency",           "type": "string", "fieldType": "text"},
            {"name": "status",            "label": "Status",            "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }
    return _post_schema(schema, "HUBSPOT_LAUNDRY_OBJECT_TYPE")


def create_food_schema() -> str:
    headers  = get_headers()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/schemas"
    schema = {
        "name": "food_order",
        "labels": {"singular": "Food Order", "plural": "Food Orders"},
        "primaryDisplayProperty": "room_number",
        "properties": [
            {"name": "room_number",       "label": "Room Number",       "type": "string", "fieldType": "text"},
            {"name": "items",             "label": "Items",             "type": "string", "fieldType": "text"},
            {"name": "delivery_deadline", "label": "Delivery Deadline", "type": "string", "fieldType": "text"},
            {"name": "special_notes",     "label": "Special Notes",     "type": "string", "fieldType": "text"},
            {"name": "urgency",           "label": "Urgency",           "type": "string", "fieldType": "text"},
            {"name": "status",            "label": "Status",            "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }
    return _post_schema(schema, "HUBSPOT_FOOD_OBJECT_TYPE")


def create_maintenance_schema() -> str:
    headers  = get_headers()
    endpoint = f"{HUBSPOT_BASE_URL}/crm/v3/schemas"
    schema = {
        "name": "maintenance_request",
        "labels": {"singular": "Maintenance Request", "plural": "Maintenance Requests"},
        "primaryDisplayProperty": "room_number",
        "properties": [
            {"name": "room_number",       "label": "Room Number",       "type": "string", "fieldType": "text"},
            {"name": "issue_description", "label": "Issue Description", "type": "string", "fieldType": "text"},
            {"name": "urgency",           "label": "Urgency",           "type": "string", "fieldType": "text"},
            {"name": "pickup_time",       "label": "Pickup Time",       "type": "string", "fieldType": "text"},
            {"name": "status",            "label": "Status",            "type": "string", "fieldType": "text"},
        ],
        "associatedObjects": [],
    }
    return _post_schema(schema, "HUBSPOT_MAINTENANCE_OBJECT_TYPE")


def _post_schema(schema: dict, env_key: str) -> str:
    """Shared logic for posting any schema and printing the env variable to save."""
    response = requests.post(
        f"{HUBSPOT_BASE_URL}/crm/v3/schemas",
        headers=get_headers(),
        json=schema
    )
    name = schema["name"]
    if response.status_code == 201:
        result      = response.json()
        object_type = result.get("objectTypeId") or result.get("name")
        print(f"✓ '{name}' schema created.")
        print(f"  Add to .env: {env_key}={object_type}")
        return object_type
    elif response.status_code == 409:
        print(f"✗ '{name}' schema already exists.")
        return ""
    else:
        raise ConnectionError(f"'{name}' failed {response.status_code}: {response.text}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    if "--setup-taxi"        in sys.argv: create_taxi_schema()
    if "--setup-laundry"     in sys.argv: create_laundry_schema()
    if "--setup-food"        in sys.argv: create_food_schema()
    if "--setup-maintenance" in sys.argv: create_maintenance_schema()
    if "--setup-payment"     in sys.argv: create_payment_schema()