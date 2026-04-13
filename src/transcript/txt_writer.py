"""
txt_writer.py
=============
Writes a live, human-readable plain-text transcript file for every call session.

One file is created per session:
    transcripts/txt/<YYYY-MM-DD>/<session_id>.txt

Each line is formatted as:
    [HH:MM:SS]  AGENT : Hello, how can I help you today?
    [HH:MM:SS]  USER  : I'd like to know about your pricing.

The file is written (appended) after every single turn so it is always
up-to-date even if the process crashes mid-call.

A header and footer are also written:
    ── Session Start ──────────────────────────────────
    Session : <session_id>
    Room    : <room_name>
    Started : 2024-11-15 14:32:07 UTC
    ───────────────────────────────────────────────────

    ... turns ...

    ── Session End ────────────────────────────────────
    Duration  : 3m 42s
    Turns     : 18  (agent: 9  user: 9)
    ───────────────────────────────────────────────────

Usage (already wired into TranscriptManager — no manual setup needed):
    The manager creates and owns one TxtTranscriptWriter instance.
    Call writer.write_turn(role, text, ts) from _add_turn().
    Call writer.write_footer(duration_s, agent_turns, user_turns) on end.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("transcript.txt_writer")

# Root directory that holds all .txt files.
# Kept inside the same top-level "transcripts/" folder used by the manager.
_TXT_SUBDIR = "txt"

# Column widths for pretty alignment
_SPEAKER_WIDTH = 5   # "AGENT" or "USER "


def _fmt_time(ts: float) -> str:
    """Unix timestamp → 'HH:MM:SS' in local time."""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _fmt_datetime(ts: float) -> str:
    """Unix timestamp → 'YYYY-MM-DD HH:MM:SS UTC'."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_duration(seconds: float) -> str:
    """Seconds → 'Xm Ys' or 'Xs'."""
    s = int(seconds)
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


class TxtTranscriptWriter:
    """
    Writes one plain-text file per call session.

    Created and owned by TranscriptManager — you do not need to
    instantiate this directly.
    """

    def __init__(
        self,
        transcripts_dir: Path,
        session_id: str,
        room_name: str,
        started_at: float,          # unix timestamp
    ):
        self._session_id = session_id
        self._room_name = room_name
        self._started_at = started_at

        # Build directory:  transcripts/txt/YYYY-MM-DD/
        date_str = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d")
        txt_dir = transcripts_dir / _TXT_SUBDIR / date_str
        txt_dir.mkdir(parents=True, exist_ok=True)

        self._path = txt_dir / f"{session_id}.txt"
        self._write_header()

        logger.info("TxtTranscriptWriter ready → %s", self._path)

    # ── Public API ────────────────────────────────────────────────────────────

    def write_turn(self, role: str, text: str, ts: float):
        """
        Append one conversation turn to the file.

        Parameters
        ----------
        role : 'agent' | 'user'
        text : transcribed / generated text
        ts   : unix timestamp of this turn
        """
        speaker = "AGENT" if role == "agent" else "USER "
        line = f"[{_fmt_time(ts)}]  {speaker} : {text}\n"
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.error("Failed to write turn to txt transcript: %s", e)

    def write_footer(
        self,
        duration_s: float,
        agent_turns: int,
        user_turns: int,
    ):
        """
        Append a session-end summary block.

        Call this once when the session finishes (in TranscriptManager.flush_to_db).
        """
        total = agent_turns + user_turns
        footer = (
            "\n"
            "── Session End " + "─" * 52 + "\n"
            f"  Duration  : {_fmt_duration(duration_s)}\n"
            f"  Turns     : {total}  (agent: {agent_turns}  user: {user_turns})\n"
            "─" * 66 + "\n"
        )
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(footer)
            logger.info("Txt transcript finalised → %s", self._path)
        except OSError as e:
            logger.error("Failed to write txt transcript footer: %s", e)

    @property
    def path(self) -> Path:
        """Absolute path to the .txt file (useful for logging)."""
        return self._path

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write_header(self):
        """Write the session header block when the file is first created."""
        header = (
            "── Session Start " + "─" * 49 + "\n"
            f"  Session : {self._session_id}\n"
            f"  Room    : {self._room_name}\n"
            f"  Started : {_fmt_datetime(self._started_at)}\n"
            "─" * 66 + "\n\n"
        )
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(header)
        except OSError as e:
            logger.error("Failed to write txt transcript header: %s", e)
