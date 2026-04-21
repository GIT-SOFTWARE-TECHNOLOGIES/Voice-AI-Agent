"""
main.py
-------
Orchestrates the full pipeline:
Transcript → Extract → Validate → Push to HubSpot
"""

import sys
import json
import os
import time
import shutil
from dotenv import load_dotenv
from src.extraction.extractor import extract_from_file
from src.extraction.validator import validate
from src.crm.hubspot_connector import push as push_to_hubspot

load_dotenv()

UNPROCESSED_DIR = os.path.join("transcripts", "unprocessed")
PROCESSED_DIR   = os.path.join("transcripts", "processed")
FAILED_DIR      = os.path.join("transcripts", "failed")


def run(transcript_path: str):
    print(f"\n{'='*60}")
    print(f"Processing: {transcript_path}")
    print(f"{'='*60}")

    print("\n[1/3] Extracting from transcript...")
    data = extract_from_file(transcript_path)
    print(f"  ✓ Room: {data.get('room_number')} | "
          f"Service: {data.get('service_type')} | "
          f"Urgency: {data.get('urgency')}")

    print("\n[2/3] Validating...")
    is_valid, errors = validate(data)
    if not is_valid:
        print(f"  ✗ Validation failed:")
        for e in errors:
            print(f"    - {e}")
        shutil.move(transcript_path, FAILED_DIR)
        return
    print(f"  ✓ Validation passed")

    # Print the payload here — single source, no duplication
    print("\n  Payload being pushed to HubSpot:")
    print(json.dumps(data, indent=2))


    print("\n[3/3] Pushing to HubSpot...")
    record = push_to_hubspot(data)
    print(f"  ✓ Done. HubSpot Record ID: {record.get('id')}")
    shutil.move(transcript_path, PROCESSED_DIR)



def wait_for_single_file():
    print("⏳ Waiting for transcript file in transcripts/unprocessed/...")

    # Step 1 — wait for a file to appear
    while True:
        files = [
            os.path.join(UNPROCESSED_DIR, f)
            for f in os.listdir(UNPROCESSED_DIR)
            if f.endswith(".jsonl")
        ]
        if files:
            path = files[0]
            print(f"\n📄 Found file: {path}. Waiting for call to finish...")
            break
        time.sleep(2)

    # Step 2 — wait for the file to go quiet (call ended)
    while True:
        last_modified = os.path.getmtime(path)
        time.sleep(10)
        if os.path.getmtime(path) == last_modified:
            print(f"  ✓ File stable. Call has ended.")
            return path


if __name__ == "__main__":
    file_path = wait_for_single_file()
    run(file_path)

    print("\n✅ Processing complete. Exiting.")