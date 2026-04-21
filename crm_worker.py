"""
worker_option1_time_delay.py
----------------------------
OPTION 1 — Time Delay Approach

Worker waits for a .jsonl file to appear in unprocessed/,
then waits until the file has not been modified for QUIET_PERIOD
seconds before concluding the call has ended and processing it.

Simple but fragile — long pauses in conversation can trigger
a false "call ended" signal.

Usage:
    python worker_option1_time_delay.py
"""

import os
import json
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

POLL_INTERVAL = 2   # seconds between checks
QUIET_PERIOD  = 10  # seconds of no modification = call ended


def get_file():
    """Returns the first .jsonl file found in unprocessed/, or None."""
    files = [f for f in os.listdir(UNPROCESSED_DIR) if f.endswith(".jsonl")]
    if files:
        return os.path.join(UNPROCESSED_DIR, files[0])
    return None


def wait_for_file():
    """Blocks until a .jsonl file appears in unprocessed/."""
    print("⏳ Waiting for transcript file in transcripts/unprocessed/...")
    while True:
        path = get_file()
        if path:
            print(f"\n📄 Found file: {path}")
            return path
        time.sleep(POLL_INTERVAL)


def wait_for_call_to_end(path):
    """
    Polls the file's last-modified time every POLL_INTERVAL seconds.
    Returns when the file has not been modified for QUIET_PERIOD seconds.
    """
    print(f"⏳ Monitoring file for inactivity ({QUIET_PERIOD}s quiet period)...")
    while True:
        last_modified = os.path.getmtime(path)
        time.sleep(QUIET_PERIOD)
        if os.path.getmtime(path) == last_modified:
            print("  ✓ File has been quiet. Assuming call has ended.")
            return


def run(transcript_path: str):
    print(f"\n{'='*60}")
    print(f"Processing: {transcript_path}")
    print(f"{'='*60}")

    try:
        print("\n[1/3] Extracting from transcript...")
        data = extract_from_file(transcript_path)
        print(f"  ✓ Room: {data.get('room_number')} | "
              f"Service: {data.get('service_type')} | "
              f"Urgency: {data.get('urgency')}")

        print("\n[2/3] Validating...")
        is_valid, errors = validate(data)
        if not is_valid:
            print("  ✗ Validation failed:")
            for e in errors:
                print(f"    - {e}")
            shutil.move(transcript_path, FAILED_DIR)
            print(f"  ✗ Moved to failed/")
            return

        print("  ✓ Validation passed")

        # Print the payload here — single source, no duplication
        print("\n  Payload being pushed to HubSpot:")
        print(json.dumps(data, indent=2))

        print("\n[3/3] Pushing to HubSpot...")
        record = push_to_hubspot(data)
        print(f"  ✓ Done. HubSpot Record ID: {record.get('id')}")

        shutil.move(transcript_path, PROCESSED_DIR)
        print(f"  ✓ Moved to processed/")

    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        shutil.move(transcript_path, FAILED_DIR)
        print(f"  ✗ Moved to failed/")


if __name__ == "__main__":
    path = wait_for_file()
    wait_for_call_to_end(path)
    run(path)
    print("\n✅ Processing complete. Exiting.")