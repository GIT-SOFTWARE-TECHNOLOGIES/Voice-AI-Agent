"""
transcript.py
─────────────────────────────────────────────────────────────────────────────
Saves PersonaPlex agent transcript (AI text messages) permanently.

Storage:
  1. SQLite database  →  /app/transcripts/transcripts.db
       - All sessions and messages in one queryable file
       - Survives container restarts (mounted as Docker volume)

  2. JSON file (one per call)  →  /app/transcripts/YYYY-MM-DD/<session_id>.json
       - Human readable
       - Easy to share / export individual calls

Usage in personaplex_agent_new.py:
    store = TranscriptStore(room_name=room_name, caller_number=caller_number)
    store.start_session()
    store.add_message("Hello, how can I help you?")   # call on every on_text
    store.end_session(frames_sent=100, frames_received=100)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("personaplex.transcript")

# ── Storage location ──────────────────────────────────────────────────────────
# This folder is mounted as a Docker volume so data persists across restarts.
TRANSCRIPTS_DIR = Path(os.getenv("TRANSCRIPTS_DIR", "/app/transcripts"))


class TranscriptStore:
    """
    Stores the AI agent transcript for one call session.

    One instance is created per call in personaplex_agent_new.py.
    Call flow:
        store = TranscriptStore(room_name, caller_number)
        store.start_session()
        store.add_message("text from PersonaPlex...")   ← called on every MSG_TEXT
        store.end_session(frames_sent, frames_received)
    """

    def __init__(self, room_name: str, caller_number: str = "unknown"):
        self.room_name     = room_name
        self.caller_number = caller_number
        self.started_at    = datetime.now(timezone.utc)
        self.messages: list[dict] = []

        # Build a unique session ID:  room_name + timestamp
        ts = self.started_at.strftime("%Y%m%d-%H%M%S")
        safe_room = room_name.replace("+", "").replace(" ", "-")
        self.session_id = f"{safe_room}-{ts}"

        # Ensure directories exist
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        date_dir = TRANSCRIPTS_DIR / self.started_at.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        self._json_path = date_dir / f"{self.session_id}.json"

        # Init SQLite
        self._db_path = TRANSCRIPTS_DIR / "transcripts.db"
        self._init_db()

    # ── Database setup ────────────────────────────────────────────────────────

    def _init_db(self):
        """Create tables if they don't exist yet."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id       TEXT PRIMARY KEY,
                    room_name        TEXT,
                    caller_number    TEXT,
                    started_at       TEXT,
                    ended_at         TEXT,
                    duration_seconds INTEGER,
                    total_messages   INTEGER DEFAULT 0,
                    frames_sent      INTEGER DEFAULT 0,
                    frames_received  INTEGER DEFAULT 0,
                    json_path        TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT,
                    timestamp   TEXT,
                    speaker     TEXT,
                    text        TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            conn.commit()
        logger.info("SQLite DB ready: %s", self._db_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def start_session(self):
        """Call this when the agent joins the room."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO sessions
                    (session_id, room_name, caller_number, started_at, json_path)
                VALUES (?, ?, ?, ?, ?)
            """, (
                self.session_id,
                self.room_name,
                self.caller_number,
                self.started_at.isoformat(),
                str(self._json_path),
            ))
            conn.commit()

        # Write initial JSON file
        self._write_json()
        logger.info("Transcript session started: %s", self.session_id)

    def add_message(self, text: str):
        """
        Call this every time PersonaPlex sends a MSG_TEXT message.
        This is the main method — plug it into on_text_callback.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "speaker":   "agent",
            "text":      text,
        }
        self.messages.append(entry)

        # Save to SQLite immediately (don't wait for end of call)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO messages (session_id, timestamp, speaker, text)
                VALUES (?, ?, ?, ?)
            """, (self.session_id, timestamp, "agent", text))
            conn.execute("""
                UPDATE sessions SET total_messages = ? WHERE session_id = ?
            """, (len(self.messages), self.session_id))
            conn.commit()

        # Update JSON file after every message so it's always up to date
        self._write_json()
        logger.info("[TRANSCRIPT] Agent: %s", text[:80])

    def end_session(self, frames_sent: int = 0, frames_received: int = 0):
        """Call this when the call ends / bridge stops."""
        ended_at = datetime.now(timezone.utc)
        duration = int((ended_at - self.started_at).total_seconds())

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                UPDATE sessions SET
                    ended_at         = ?,
                    duration_seconds = ?,
                    total_messages   = ?,
                    frames_sent      = ?,
                    frames_received  = ?
                WHERE session_id = ?
            """, (
                ended_at.isoformat(),
                duration,
                len(self.messages),
                frames_sent,
                frames_received,
                self.session_id,
            ))
            conn.commit()

        # Final JSON write with complete data
        self._write_json(ended_at=ended_at, duration=duration,
                         frames_sent=frames_sent, frames_received=frames_received)

        logger.info(
            "Transcript saved — session=%s  messages=%d  duration=%ds  json=%s",
            self.session_id, len(self.messages), duration, self._json_path,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write_json(self, ended_at=None, duration=None,
                    frames_sent=0, frames_received=0):
        """Write the full transcript to a JSON file."""
        data = {
            "session_id":       self.session_id,
            "room_name":        self.room_name,
            "caller_number":    self.caller_number,
            "started_at":       self.started_at.isoformat(),
            "ended_at":         ended_at.isoformat() if ended_at else None,
            "duration_seconds": duration,
            "total_messages":   len(self.messages),
            "frames_sent":      frames_sent,
            "frames_received":  frames_received,
            "messages":         self.messages,
        }
        try:
            with open(self._json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to write JSON transcript: %s", e)