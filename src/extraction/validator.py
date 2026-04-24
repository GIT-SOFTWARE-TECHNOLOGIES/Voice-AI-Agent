VALID_SERVICE_TYPES = {"taxi", "laundry", "food_order", "maintenance"}

def validate_taxi(data):
    errors = []
    for field in ["room_number", "destination", "pickup_time", "status"]:
        if not data.get(field):
            errors.append(f"Missing or empty: '{field}'")
    return len(errors) == 0, errors

def validate_laundry(data):
    errors = []
    for field in ["room_number", "status"]:
        if not data.get(field):
            errors.append(f"Missing or empty: '{field}'")
    if not isinstance(data.get("items"), list):
        errors.append("'items' must be a list")
    if data.get("urgency") not in {"urgent", "normal"}:
        errors.append("'urgency' must be urgent or normal")
    return len(errors) == 0, errors

def validate_food_order(data):
    errors = []
    for field in ["room_number", "status"]:
        if not data.get(field):
            errors.append(f"Missing or empty: '{field}'")
    if not isinstance(data.get("items"), list):
        errors.append("'items' must be a list")
    if data.get("urgency") not in {"urgent", "normal"}:
        errors.append("'urgency' must be urgent or normal")
    return len(errors) == 0, errors

def validate_maintenance(data):
    errors = []
    for field in ["room_number", "issue_description", "status"]:
        if not data.get(field):
            errors.append(f"Missing or empty: '{field}'")
    if data.get("urgency") not in {"urgent", "normal"}:
        errors.append("'urgency' must be urgent or normal")
    return len(errors) == 0, errors

def validate(data: dict) -> tuple[bool, list[str]]:
    service_type = data.get("service_type")
    if service_type not in VALID_SERVICE_TYPES:
        return False, [f"Invalid service_type: '{service_type}'"]
    
    validators = {
        "taxi":        validate_taxi,
        "laundry":     validate_laundry,
        "food_order":  validate_food_order,
        "maintenance": validate_maintenance,
    }
    return validators[service_type](data)