"""
UserTranscriber — Deepgram STT (Fixed v2)
==========================================
Drop-in replacement for the Whisper-based UserTranscriber.
Streams LiveKit audio to Deepgram in real-time.

Key fix: dg_client.listen.asynclive (async WebSocket client) REQUIRES
async def handlers — plain def returns None which crashes the SDK with
"a coroutine was expected, got None".

Setup:
  pip install deepgram-sdk==3.10.1
  Add DEEPGRAM_API_KEY to your .env file
"""

import asyncio
import logging
import os
from typing import Callable, Optional

import numpy as np
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger("transcript.user")

# ── Audio constants ────────────────────────────────────────────────────────────
LIVEKIT_SAMPLE_RATE  = 48_000   # Hz — what LiveKit gives us
DEEPGRAM_SAMPLE_RATE = 16_000   # Hz — what Deepgram expects

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")


class UserTranscriber:
    """
    Drop-in replacement for the Whisper-based UserTranscriber.
    Same interface — push_frame() is identical.

    Uses dg_client.listen.asynclive (async WebSocket client).
    This variant requires ALL event handlers to be async def.
    """

    def __init__(
        self,
        on_transcript: Callable[[str], None],
        model_size: str = "base",       # ignored — kept for API compatibility
        language: Optional[str] = "en",
        device: str = "cpu",            # ignored — kept for API compatibility
        compute_type: str = "int8",     # ignored — kept for API compatibility
    ):
        self._on_transcript  = on_transcript
        self._language       = language or "en"
        self._dg_connection  = None
        self._connected      = False
        self._started        = False

        if not DEEPGRAM_API_KEY:
            raise RuntimeError(
                "DEEPGRAM_API_KEY not set in .env — "
                "get a free key at deepgram.com"
            )

        logger.info(
            "UserTranscriber: Deepgram STT initialised (language=%s)", self._language
        )

    # ── Called from bridge._handle_stream on every audio frame ────────────────

    async def push_frame(self, pcm_int16: np.ndarray):
        """
        Push one LiveKit audio frame (48kHz int16 mono).
        Identical interface to the Whisper version.
        """
        # Start connection on first frame (inside running event loop)
        if not self._started:
            self._started = True
            asyncio.ensure_future(self._start_deepgram())
            logger.info("Deepgram connection starting...")

        # Drop frames silently until connection is ready
        if not self._connected or self._dg_connection is None:
            return

        try:
            audio_16k = self._resample(pcm_int16)
            await self._dg_connection.send(audio_16k.tobytes())
        except Exception as e:
            logger.warning("Deepgram send error: %s", e)

    # ── Deepgram connection ────────────────────────────────────────────────────

    async def _start_deepgram(self):
        """Start Deepgram async streaming WebSocket connection."""
        try:
            from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

            dg_client = DeepgramClient(DEEPGRAM_API_KEY)

            # asynclive = async WebSocket client → handlers MUST be async def
            self._dg_connection = dg_client.listen.asynclive.v("1")

            self._dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript_event)
            self._dg_connection.on(LiveTranscriptionEvents.Error,      self._on_error_event)
            self._dg_connection.on(LiveTranscriptionEvents.Close,      self._on_close_event)

            options = LiveOptions(
                model="nova-2",
                language=self._language,
                encoding="linear16",
                sample_rate=DEEPGRAM_SAMPLE_RATE,
                channels=1,
                punctuate=True,
                smart_format=True,
                interim_results=True,       # required for utterance_end_ms to work
                utterance_end_ms="1000",    # 1s silence = end of utterance
                vad_events=True,
                endpointing=300,
            )

            started = await self._dg_connection.start(options)
            if started:
                self._connected = True
                logger.info("Deepgram streaming connected ✓")
            else:
                logger.error("Deepgram connection failed to start")

        except ImportError:
            raise RuntimeError(
                "deepgram-sdk not installed. Run: pip install deepgram-sdk==3.10.1"
            )
        except Exception as e:
            logger.error("Deepgram connection error: %s", e)

    # ── Event handlers — MUST be async def for asynclive client ───────────────

    async def _on_transcript_event(self, *args, **kwargs):
        """
        Handles Deepgram Transcript events.
        MUST be async def — asynclive client awaits these handlers.
        """
        try:
            result = kwargs.get("result") or (args[1] if len(args) > 1 else None)
            if result is None:
                return

            transcript = (
                result.channel.alternatives[0].transcript
                if result.channel and result.channel.alternatives
                else ""
            )

            # speech_final=True means end of complete utterance
            # interim results (speech_final=False) are ignored
            if result.speech_final and transcript.strip():
                logger.info("Deepgram transcript: '%s'", transcript)
                self._on_transcript(transcript.strip())

        except Exception as e:
            logger.warning("Deepgram transcript handler error: %s", e)

    async def _on_error_event(self, *args, **kwargs):
        """MUST be async def — asynclive client awaits these handlers."""
        error = kwargs.get("error") or (args[1] if len(args) > 1 else "unknown")
        logger.error("Deepgram error: %s", error)
        self._connected = False

    async def _on_close_event(self, *args, **kwargs):
        """MUST be async def — asynclive client awaits these handlers."""
        logger.info("Deepgram connection closed")
        self._connected = False

    # ── Session cleanup ────────────────────────────────────────────────────────

    async def close(self):
        """
        Close Deepgram connection gracefully.
        Called in personaplex_agent_new.py finally block
        before transcript.flush_to_db().
        """
        if self._dg_connection and self._connected:
            try:
                await self._dg_connection.finish()
                logger.info("Deepgram connection closed gracefully")
            except Exception as e:
                logger.warning("Deepgram close error: %s", e)
        self._connected = False

    # ── Audio helper ───────────────────────────────────────────────────────────

    @staticmethod
    def _resample(pcm_int16: np.ndarray) -> np.ndarray:
        """Resample 48kHz int16 → 16kHz int16 by decimation (factor of 3)."""
        if len(pcm_int16) == 0:
            return pcm_int16
        return pcm_int16[::3].astype(np.int16)