from taxi_client import trigger_taxi_worker
import time

turns = [
    {"session_id": "test-001", "room": "test-room", "role": "agent",
     "text": "Hello, welcome to Grand View Hotel. How can I help?", "ts": 1.0, "turn_index": 0},

    {"session_id": "test-001", "room": "test-room", "role": "user",
     "text": "I want to book a taxi to the airport.", "ts": 2.0, "turn_index": 1},

    {"session_id": "test-001", "room": "test-room", "role": "agent",
     "text": "Sure! What is your room number?", "ts": 3.0, "turn_index": 2},

    {"session_id": "test-001", "room": "test-room", "role": "user",
     "text": "My room number is 202.", "ts": 4.0, "turn_index": 3},

    {"session_id": "test-001", "room": "test-room", "role": "agent",
     "text": "What time would you like the taxi?", "ts": 5.0, "turn_index": 4},

    {"session_id": "test-001", "room": "test-room", "role": "user",
     "text": "At 6 PM please.", "ts": 6.0, "turn_index": 5},

    {"session_id": "test-001", "room": "test-room", "role": "agent",
     "text": "Shall I confirm your booking — taxi to Airport at 6 PM from room 202?",
     "ts": 7.0, "turn_index": 6},

    {"session_id": "test-001", "room": "test-room", "role": "user",
     "text": "Yes, confirm.", "ts": 8.0, "turn_index": 7},

    {"session_id": "test-001", "room": "test-room", "role": "agent",
     "text": "Your taxi is confirmed! Driver will be waiting at Hotel Lobby.",
     "ts": 9.0, "turn_index": 8},
]

trigger_taxi_worker(turns=turns, session_id="test-001")

# Wait for background thread to finish
time.sleep(5)
print("Done.")