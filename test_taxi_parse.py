from src.taxi.transcript_parser import parse_transcript

turns = [
    {"session_id": "test", "room": "personaplex-test", "role": "agent", "text": "Hello, welcome to Grand view Hotel. This is Kelly. How can I help you today?", "ts": 1.0, "turn_index": 0},
    {"session_id": "test", "room": "personaplex-test", "role": "user", "text": "I want to book a taxi.", "ts": 2.0, "turn_index": 1},
    {"session_id": "test", "room": "personaplex-test", "role": "agent", "text": "Of course. Can I get your name and room number?", "ts": 3.0, "turn_index": 2},
    {"session_id": "test", "room": "personaplex-test", "role": "user", "text": "my name is John and my zoom number is", "ts": 4.0, "turn_index": 3},
    {"session_id": "test", "room": "personaplex-test", "role": "user", "text": "2, 3, 2, 1.", "ts": 5.0, "turn_index": 4},
    {"session_id": "test", "room": "personaplex-test", "role": "agent", "text": "Alright, found it. Your room is 2 0 2. Would you like to book a taxi for today at 7:30 PM?", "ts": 6.0, "turn_index": 5},
    {"session_id": "test", "room": "personaplex-test", "role": "agent", "text": "Sure, no problem. How about 6 PM?", "ts": 7.0, "turn_index": 6},
    {"session_id": "test", "room": "personaplex-test", "role": "user", "text": "I want to book it.", "ts": 8.0, "turn_index": 7},
    {"session_id": "test", "room": "personaplex-test", "role": "agent", "text": "Got it, 6 PM. Your taxi will be waiting outside your door.", "ts": 9.0, "turn_index": 8},
]

parsed = parse_transcript(turns)
print("has_taxi_intent:", parsed.has_taxi_intent)
print("destination:    ", parsed.destination)
print("room_number:    ", parsed.room_number)
print("pickup_time:    ", parsed.pickup_time)
print("confirmed:      ", parsed.booking_confirmed)
print("cancelled:      ", parsed.booking_cancelled)
print("missing:        ", parsed.missing_fields)