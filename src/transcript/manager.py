"""
TranscriptManager
=================
Captures BOTH agent and user turns for a PersonaPlex session.

Agent turns  -> come from MSG_TEXT frames via on_text_callback (already wired)
User turns   -> come from local Whisper (faster-whisper) running on the raw
               PCM already present in _handle_stream inside bridge.py

Storage:
  * JSONL  -- one file per session, one JSON object per line (crash-safe)
  * SQLite -- all sessions in one DB for querying / analytics
  * TXT    -- human-readable plain text file per session

Directory layout produced:
  transcripts/
    sessions.db          <- SQLite, all sessions
    <session_id>.jsonl   <- per-session append log
    txt/<date>/<session_id>.txt  <- plain text
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, Callable

from src.transcript.txt_writer import TxtTranscriptWriter

logger = logging.getLogger("transcript.manager")

TRANSCRIPTS_DIR   = Path("transcripts")
DB_PATH           = TRANSCRIPTS_DIR / "sessions.db"
UNPROCESSED_DIR   = TRANSCRIPTS_DIR / "unprocessed"   # new JSONs land here
PROCESSED_DIR     = TRANSCRIPTS_DIR / "processed"     # CRM worker moves here
FAILED_DIR        = TRANSCRIPTS_DIR / "failed"        # failed processing goes here

# ── Agent text cleanup ─────────────────────────────────────────────────────────

def _cleanup_agent_text(text: str) -> str:
    """
    Fix common subword fragment artifacts produced by PersonaPlex (Moshi).

    PersonaPlex is a speech model — it streams phoneme/subword fragments
    as MSG_TEXT tokens. After joining with spaces these leave artifacts like:
      "What' s"  -> "What's"
      "Al right" -> "Alright"
      "re serv ation" -> still imperfect (no context to fix all cases)

    This function applies safe, conservative regex fixes.
    """
    # Fix split contractions: "What' s" -> "What's", "I' m" -> "I'm"
    text = re.sub(r"'\s+([a-z]{1,3})\b", r"'\1", text)

    # Fix space before punctuation
    text = re.sub(r'\s+([.,?!:;])', r'\1', text)

    # Fix common PersonaPlex word splits
    replacements = [
        (r'\bAl right\b',   'Alright'),
        (r'\bal right\b',   'alright'),
        (r'\bcheck in s\b', 'check-ins'),
        (r'\bres erv ation\b', 'reservation'),
        (r'\breserv ation\b',  'reservation'),
        (r'\bre serv ation\b', 'reservation'),
        (r'\bserv ation\b',    'servation'),   # partial — better than nothing
        (r'\bcon firm ation\b', 'confirmation'),
        (r'\bin form ation\b',  'information'),
        (r'\bappointment\b',    'appointment'),  # already fine, keep
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    # Fix multiple spaces
    text = re.sub(r'  +', ' ', text)

    return text.strip()


class TranscriptManager:
    """
    Thread-safe (asyncio-compatible) transcript store.
    """

    def __init__(
        self,
        room_name: str,
        session_id: Optional[str] = None,
        on_turn_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.room_name = room_name
        self.session_id = session_id or str(uuid.uuid4())
        self._on_turn_callback = on_turn_callback

        self._turns: list[dict] = []
        self._turn_index = 0
        self._session_start = time.time()
        self._lock = asyncio.Lock()

        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        UNPROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        FAILED_DIR.mkdir(parents=True, exist_ok=True)

        # JSONL saved to unprocessed/ so CRM worker can pick it up
        self._jsonl_path = UNPROCESSED_DIR / f"{self.session_id}.jsonl"

        self._txt_writer = TxtTranscriptWriter(
            transcripts_dir=TRANSCRIPTS_DIR,
            session_id=self.session_id,
            room_name=room_name,
            started_at=self._session_start,
        )

        self._init_db()
        logger.info(
            "TranscriptManager ready — session=%s  room=%s  file=%s  txt=%s",
            self.session_id, room_name, self._jsonl_path, self._txt_writer.path,
        )

    # ── DB bootstrap ──────────────────────────────────────────────────────────

    def _init_db(self):
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
                role         TEXT    NOT NULL,
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
        Call this after flushing the agent word buffer in bridge.py.
        Runs cleanup to fix subword fragment artifacts before storing.
        """
        cleaned = _cleanup_agent_text(text)
        if cleaned:
            self._add_turn(role="agent", text=cleaned)

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

        # 1. Write to JSONL immediately (crash-safe)
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

        # 2. Write to plain-text .txt file
        self._txt_writer.write_turn(role=role, text=text, ts=turn["ts"])

        # 3. Fire optional live callback
        if self._on_turn_callback:
            try:
                self._on_turn_callback(turn)
            except Exception as e:
                logger.warning("on_turn_callback error: %s", e)

        label = "AGENT" if role == "agent" else "USER "
        logger.info("[TRANSCRIPT] %s: %s", label, text)

    def flush_to_db(self):
        """Write all buffered turns to SQLite. Call in the agent's finally block."""
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
            "Flushed %d turns -> SQLite  (session=%s)",
            len(self._turns), self.session_id,
        )

        duration_s = time.time() - self._session_start
        agent_turns = sum(1 for t in self._turns if t["role"] == "agent")
        user_turns  = sum(1 for t in self._turns if t["role"] == "user")
        self._txt_writer.write_footer(
            duration_s=duration_s,
            agent_turns=agent_turns,
            user_turns=user_turns,
        )
        logger.info("Txt transcript finalised -> %s", self._txt_writer.path)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_full_transcript(self) -> str:
        lines = []
        for t in self._turns:
            speaker = "AGENT" if t["role"] == "agent" else "USER"
            lines.append(f"[{speaker}] {t['text']}")
        return "\n".join(lines)

    def get_turns(self) -> list[dict]:
        return list(self._turns)

    @property
    def turn_count(self) -> int:
        return self._turn_index

    @staticmethod
    def load_session(session_id: str) -> list[dict]:
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
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── CRM pipeline helpers ──────────────────────────────────────────────────

    @staticmethod
    def mark_processed(session_id: str) -> bool:
        """
        Move a session JSONL from unprocessed/ -> processed/.
        Call this from crm_worker.py after successful CRM push.
        Returns True if the file was moved, False if not found.
        """
        import shutil
        src = UNPROCESSED_DIR / f"{session_id}.jsonl"
        dst = PROCESSED_DIR   / f"{session_id}.jsonl"
        if src.exists():
            shutil.move(str(src), str(dst))
            logger.info("Marked processed: %s", session_id)
            return True
        logger.warning("mark_processed: file not found for %s", session_id)
        return False

    @staticmethod
    def mark_failed(session_id: str, reason: str = "") -> bool:
        """
        Move a session JSONL from unprocessed/ -> failed/.
        Call this from crm_worker.py when CRM push fails.
        Returns True if the file was moved, False if not found.
        """
        import shutil
        src = UNPROCESSED_DIR / f"{session_id}.jsonl"
        dst = FAILED_DIR      / f"{session_id}.jsonl"
        if src.exists():
            shutil.move(str(src), str(dst))
            logger.info("Marked failed (%s): %s", reason, session_id)
            return True
        logger.warning("mark_failed: file not found for %s", session_id)
        return False

    @staticmethod
    def list_unprocessed() -> list[Path]:
        """Return all JSONL files waiting in unprocessed/ folder."""
        return sorted(UNPROCESSED_DIR.glob("*.jsonl"))