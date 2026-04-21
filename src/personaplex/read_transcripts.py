#!/usr/bin/env python3
"""
read_transcripts.py
===================
Utility to read, display, and export saved transcripts.

Usage examples:
    python read_transcripts.py --list
    python read_transcripts.py --list-files
    python read_transcripts.py --session <session_id>
    python read_transcripts.py --session <session_id> --export txt
    python read_transcripts.py --session <session_id> --export json
    python read_transcripts.py --jsonl <session_id>
"""

import argparse
import datetime
import json
import sqlite3
from pathlib import Path

TRANSCRIPTS_DIR  = Path("transcripts")
DB_PATH          = TRANSCRIPTS_DIR / "sessions.db"
UNPROCESSED_DIR  = TRANSCRIPTS_DIR / "unprocessed"
PROCESSED_DIR    = TRANSCRIPTS_DIR / "processed"
FAILED_DIR       = TRANSCRIPTS_DIR / "failed"


def _find_jsonl(session_id: str) -> Path | None:
    """Search all three folders for a session JSONL file."""
    for folder in [UNPROCESSED_DIR, PROCESSED_DIR, FAILED_DIR, TRANSCRIPTS_DIR]:
        path = folder / f"{session_id}.jsonl"
        if path.exists():
            return path
    return None


def _status_label(session_id: str) -> str:
    """Return which folder the JSONL currently lives in."""
    if (UNPROCESSED_DIR / f"{session_id}.jsonl").exists():
        return "unprocessed"
    if (PROCESSED_DIR   / f"{session_id}.jsonl").exists():
        return "processed"
    if (FAILED_DIR      / f"{session_id}.jsonl").exists():
        return "failed"
    return "no jsonl"


# ── Commands ──────────────────────────────────────────────────────────────────

def list_sessions():
    """List all sessions from SQLite DB with their pipeline status."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    print(f"\n{'SESSION ID':<38} {'ROOM':<20} {'TURNS':>5}  {'STATUS':<12}  STARTED")
    print("-" * 100)
    for r in rows:
        started = datetime.datetime.fromtimestamp(r["started_at"]).strftime("%Y-%m-%d %H:%M:%S")
        status  = _status_label(r["session_id"])
        print(f"{r['session_id']:<38} {r['room_name']:<20} {r['turn_count']:>5}  {status:<12}  {started}")
    print()


def list_files():
    """List all JSONL files in each folder with turn counts."""
    for label, folder in [
        ("UNPROCESSED", UNPROCESSED_DIR),
        ("PROCESSED",   PROCESSED_DIR),
        ("FAILED",      FAILED_DIR),
    ]:
        files = sorted(folder.glob("*.jsonl"))
        print(f"\n── {label} ({len(files)} files) {'─' * 40}")
        if not files:
            print("   (empty)")
            continue
        for f in files:
            lines = sum(1 for _ in f.open(encoding="utf-8"))
            print(f"   {f.stem}   ({lines} turns)")
    print()


def print_session(session_id: str):
    """Print session turns from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    turns = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()
    conn.close()

    if not turns:
        print(f"No turns found in DB for session: {session_id}")
        print("Tip: try --jsonl to read directly from file")
        return

    status = _status_label(session_id)
    print(f"\n── Session: {session_id} ──")
    print(f"   Status: {status}  |  Total turns: {len(turns)}\n")
    for t in turns:
        speaker = "AGENT" if t["role"] == "agent" else "USER "
        print(f"  [{speaker}]  {t['text']}")
    print()


def export_txt(session_id: str):
    """Export session from DB to a txt file."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    turns = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()
    conn.close()

    out_path = TRANSCRIPTS_DIR / f"{session_id}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for t in turns:
            speaker = "AGENT" if t["role"] == "agent" else "USER"
            f.write(f"[{speaker}] {t['text']}\n")
    print(f"Exported: {out_path}")


def export_json(session_id: str):
    """Export session from DB to a JSON file."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    turns = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()
    conn.close()

    out_path = TRANSCRIPTS_DIR / f"{session_id}_export.json"
    data = [dict(t) for t in turns]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported: {out_path}")


def read_jsonl(session_id: str):
    """Read directly from JSONL file — searches unprocessed/processed/failed."""
    jsonl_path = _find_jsonl(session_id)
    if not jsonl_path:
        print(f"JSONL not found in any folder for session: {session_id}")
        return

    print(f"\n── JSONL: {jsonl_path} ──\n")
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            speaker = "AGENT" if t["role"] == "agent" else "USER "
            print(f"  [{speaker}]  {t['text']}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Read PersonaPlex transcripts")
    parser.add_argument("--list",       action="store_true", help="List all sessions from DB with pipeline status")
    parser.add_argument("--list-files", action="store_true", help="List JSONL files in unprocessed/processed/failed folders")
    parser.add_argument("--session",    metavar="ID",        help="Show session turns from DB")
    parser.add_argument("--export",     choices=["txt", "json"], help="Export format (use with --session)")
    parser.add_argument("--jsonl",      metavar="ID",        help="Read JSONL file directly (no DB needed)")
    args = parser.parse_args()

    if args.list:
        list_sessions()
    elif args.list_files:
        list_files()
    elif args.session:
        if args.export == "txt":
            export_txt(args.session)
        elif args.export == "json":
            export_json(args.session)
        else:
            print_session(args.session)
    elif args.jsonl:
        read_jsonl(args.jsonl)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()