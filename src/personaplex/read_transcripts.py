#!/usr/bin/env python3
"""
read_transcripts.py
===================
Utility to read, display, and export saved transcripts.

Usage examples:
    python read_transcripts.py --list
    python read_transcripts.py --session <session_id>
    python read_transcripts.py --session <session_id> --export txt
    python read_transcripts.py --session <session_id> --export json
    python read_transcripts.py --jsonl <session_id>
"""

import argparse
import json
import sqlite3
from pathlib import Path

TRANSCRIPTS_DIR = Path("transcripts")
DB_PATH = TRANSCRIPTS_DIR / "sessions.db"


def list_sessions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    print(f"\n{'SESSION ID':<38} {'ROOM':<20} {'TURNS':>5}  STARTED")
    print("-" * 85)
    for r in rows:
        import datetime
        started = datetime.datetime.fromtimestamp(r["started_at"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{r['session_id']:<38} {r['room_name']:<20} {r['turn_count']:>5}  {started}")
    print()


def print_session(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    turns = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()
    conn.close()

    if not turns:
        print(f"No turns found for session: {session_id}")
        return

    print(f"\n── Session: {session_id} ──")
    print(f"   Total turns: {len(turns)}\n")
    for t in turns:
        speaker = "🤖 AGENT" if t["role"] == "agent" else "🧑 USER "
        print(f"  {speaker}:  {t['text']}")
    print()


def export_txt(session_id: str):
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
    """Read directly from the JSONL file (no DB needed — useful for crashes)."""
    jsonl_path = TRANSCRIPTS_DIR / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        print(f"JSONL file not found: {jsonl_path}")
        return
    print(f"\n── JSONL: {jsonl_path} ──\n")
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            speaker = "🤖 AGENT" if t["role"] == "agent" else "🧑 USER "
            print(f"  {speaker}:  {t['text']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Read PersonaPlex transcripts")
    parser.add_argument("--list",    action="store_true", help="List all sessions")
    parser.add_argument("--session", metavar="ID",        help="Show session turns")
    parser.add_argument("--export",  choices=["txt", "json"], help="Export format")
    parser.add_argument("--jsonl",   metavar="ID",        help="Read JSONL directly")
    args = parser.parse_args()

    if args.list:
        list_sessions()
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