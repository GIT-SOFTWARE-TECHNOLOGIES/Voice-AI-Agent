"""
TranscriptManager
=================
Captures BOTH agent and user turns for a PersonaPlex session.

Agent turns  → come from MSG_TEXT frames via on_text_callback (already wired)
User turns   → come from local Whisper (faster-whisper) running on the raw
               PCM already present in _handle_stream inside bridge.py

Storage:
  • JSONL  — one file per session, one JSON object per line (crash-safe)
  • SQLite — all sessions in one DB for querying / analytics

Directory layout produced:
  transcripts/
    sessions.db          ← SQLite, all sessions
    <session_id>.jsonl   ← per-session append log
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("transcript.manager")

TRANSCRIPTS_DIR = Path("transcripts")
DB_PATH = TRANSCRIPTS_DIR / "sessions.db"


class TranscriptManager:
    """
    Thread-safe (asyncio-compatible) transcript store.

    Usage
    -----
    # In PersonaPlexAgent.run():
    transcript = TranscriptManager(room_name=self.room_name)

    def on_text(text: str):
        transcript.add_agent_turn(text)          # agent words

    # Inside bridge._handle_stream():
    transcript.add_user_turn(text)               # whisper result

    # On session end (finally block):
    transcript.flush_to_db()
    """

    def __init__(
        self,
        room_name: str,
        session_id: Optional[str] = None,
        on_turn_callback: Optional[Callable[[dict], None]] = None,
    ):
        """
        Parameters
        ----------
        room_name        : LiveKit room name — used as label in DB
        session_id       : UUID string; auto-generated if not supplied
        on_turn_callback : optional hook called on every new turn (for
                           webhooks, CRM push, live UI streaming, etc.)
        """
        self.room_name = room_name
        self.session_id = session_id or str(uuid.uuid4())
        self._on_turn_callback = on_turn_callback

        self._turns: list[dict] = []
        self._turn_index = 0
        self._session_start = time.time()
        self._lock = asyncio.Lock()

        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = TRANSCRIPTS_DIR / f"{self.session_id}.jsonl"

        self._init_db()
        logger.info(
            "TranscriptManager ready — session=%s  room=%s  file=%s",
            self.session_id, room_name, self._jsonl_path,
        )

    # ── DB bootstrap ──────────────────────────────────────────────────────────

    def _init_db(self):
        """Create the SQLite schema if it doesn't exist yet."""
        conn = sqlite3.connect(DB_PATH)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                room_name    TEXT NOT NULL,
                started_at   REAL NOT NULL,
                ended_at     REAL,
                turn_count   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS turns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT    NOT NULL,
                room_name    TEXT    NOT NULL,
                role         TEXT    NOT NULL,   -- 'agent' | 'user'
                text         TEXT    NOT NULL,
                ts           REAL    NOT NULL,
                turn_index   INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session
                ON turns(session_id);

            CREATE INDEX IF NOT EXISTS idx_turns_role
                ON turns(role);
        """)

        # Register this session
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, room_name, started_at) "
            "VALUES (?, ?, ?)",
            (self.session_id, self.room_name, self._session_start),
        )
        conn.commit()
        conn.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def add_agent_turn(self, text: str):
        """
        Call this from on_text_callback in personaplex_agent_new.py.
        MSG_TEXT frames from PersonaPlex → agent words.
        """
        self._add_turn(role="agent", text=text)

    def add_user_turn(self, text: str):
        """
        Call this from bridge._handle_stream() after Whisper transcribes
        a completed user utterance.
        """
        self._add_turn(role="user", text=text)

    def _add_turn(self, role: str, text: str):
        text = text.strip()
        if not text:
            return

        turn = {
            "session_id": self.session_id,
            "room":       self.room_name,
            "role":       role,
            "text":       text,
            "ts":         time.time(),
            "turn_index": self._turn_index,
        }
        self._turns.append(turn)
        self._turn_index += 1

        # ── 1. Write to JSONL immediately (crash-safe, no DB needed) ──────────
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

        # ── 2. Fire optional live callback (webhook, UI push, CRM) ───────────
        if self._on_turn_callback:
            try:
                self._on_turn_callback(turn)
            except Exception as e:
                logger.warning("on_turn_callback error: %s", e)

        label = "🤖 AGENT" if role == "agent" else "🧑 USER"
        logger.info("[TRANSCRIPT] %s: %s", label, text)

    def flush_to_db(self):
        """
        Write all buffered turns to SQLite.
        Call this once in the agent's finally block when the session ends.
        This is a synchronous call — safe to call from a finally block.
        """
        if not self._turns:
            logger.info("No turns to flush for session %s", self.session_id)
            return

        conn = sqlite3.connect(DB_PATH)
        conn.executemany(
            """INSERT INTO turns
               (session_id, room_name, role, text, ts, turn_index)
               VALUES (:session_id, :room, :role, :text, :ts, :turn_index)""",
            self._turns,
        )
        conn.execute(
            """UPDATE sessions
               SET ended_at = ?, turn_count = ?
               WHERE session_id = ?""",
            (time.time(), len(self._turns), self.session_id),
        )
        conn.commit()
        conn.close()

        logger.info(
            "Flushed %d turns → SQLite  (session=%s)",
            len(self._turns), self.session_id,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_full_transcript(self) -> str:
        """Return the session as a human-readable string."""
        lines = []
        for t in self._turns:
            speaker = "AGENT" if t["role"] == "agent" else "USER"
            lines.append(f"[{speaker}] {t['text']}")
        return "\n".join(lines)

    def get_turns(self) -> list[dict]:
        """Return a copy of all turns so far."""
        return list(self._turns)

    @property
    def turn_count(self) -> int:
        return self._turn_index

    @staticmethod
    def load_session(session_id: str) -> list[dict]:
        """Load all turns for a past session from SQLite."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def list_sessions() -> list[dict]:
        """List all recorded sessions (most recent first)."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]