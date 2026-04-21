"""
validator.py
------------
Validates that extracted JSON has the required fields before
it gets pushed to any CRM. Stops bad data at the gate.
"""

REQUIRED_FIELDS = ["room_number", "service_type"]

EXPECTED_FIELDS = [
    "room_number",
    "service_type",
    "items",
    "pickup_time",
    "delivery_deadline",
    "special_notes",
    "urgency",
    "status",
    "confidence",
    "session_id",   
    "room_name",    
]

VALID_SERVICE_TYPES = {"laundry", "room_service", "food_and_beverages", "maintenance", "concierge"}
VALID_URGENCY      = {"urgent", "normal"}


def validate(data: dict) -> tuple[bool, list[str]]:
    """
    Validates extracted data.

    Returns:
        (True, [])               — if valid, with no errors
        (False, ["error", ...])  — if invalid, with a list of error messages
    """
    errors = []

    # 1. Check all expected fields are present in the dict
    for field in EXPECTED_FIELDS:
        if field not in data:
            errors.append(f"Missing field: '{field}'")

    # 2. Check required fields are non-null and non-empty
    for field in REQUIRED_FIELDS:
        value = data.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            errors.append(f"Required field '{field}' is null or empty")

    # 3. Check service_type is one of the 4 recognised values
    if data.get("service_type") not in VALID_SERVICE_TYPES:
        errors.append(
            f"Field 'service_type' must be one of {VALID_SERVICE_TYPES}, "
            f"got: {data.get('service_type')!r}"
        )

    # 4. Check items is a list (can be empty, but must be a list)
    if "items" in data and not isinstance(data["items"], list):
        errors.append("Field 'items' must be a list")

    # 5. Check urgency is valid
    if data.get("urgency") not in VALID_URGENCY:
        errors.append(
            f"Field 'urgency' must be one of {VALID_URGENCY}, "
            f"got: {data.get('urgency')!r}"
        )

    # 6. Check status is 'pending'
    if data.get("status") != "pending":
        errors.append(f"Field 'status' must be 'pending', got: {data.get('status')!r}")

    # 7. Check confidence is a recognised value
    valid_confidence = {"high", "medium", "low"}
    if data.get("confidence") not in valid_confidence:
        errors.append(
            f"Field 'confidence' must be one of {valid_confidence}, "
            f"got: {data.get('confidence')!r}"
        )

    is_valid = len(errors) == 0
    return is_valid, errors


# ── Quick test when run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    good = {
        "room_number": "302",
        "service_type": "laundry",
        "items": [{"name": "shirt", "quantity": 2}],
        "pickup_time": "within the hour",
        "delivery_deadline": "tomorrow before 10am",
        "special_notes": None,
        "urgency": "normal",
        "status": "pending",
        "confidence": "high",
    }

    bad = {
        "room_number": None,
        "service_type": "spa",          # not a valid service type
        "items": "not a list",
        "pickup_time": None,
        "delivery_deadline": None,
        "special_notes": None,
        "urgency": "maybe",             # invalid
        "status": "pending",
        "confidence": "unknown",
    }

    for label, record in [("GOOD", good), ("BAD", bad)]:
        is_valid, errors = validate(record)
        print(f"\n── {label} record ──")
        print(f"Valid: {is_valid}")
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
        else:
            print("  ✓ All checks passed")