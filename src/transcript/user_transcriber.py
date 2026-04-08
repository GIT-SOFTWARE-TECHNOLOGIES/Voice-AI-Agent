"""
UserTranscriber
===============
Segments user audio from bridge._handle_stream() into utterances using
RMS-based VAD (same logic already in bridge.py), then transcribes each
utterance locally with faster-whisper — NO external STT API.

Install the one extra dependency:
    pip install faster-whisper

Model sizes vs speed on CPU (choose based on your server):
    tiny   ~39M params  — fastest, ~0.3s/utt,  rough quality
    base   ~74M params  — good balance, ~0.6s/utt  ← recommended
    small  ~244M params — better, ~1.5s/utt
    (on RunPod GPU, even 'medium' runs in real-time)
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("transcript.user")

# ── Audio constants (must match bridge.py) ─────────────────────────────────
LIVEKIT_SAMPLE_RATE = 48_000   # Hz — what LiveKit gives us
# Whisper wants 16kHz mono float32
WHISPER_SAMPLE_RATE = 16_000

# ── VAD tuning ──────────────────────────────────────────────────────────────
RMS_SPEECH_THRESHOLD = 500     # same value already used in bridge.py
SILENCE_FRAMES_CUTOFF = 12    # ~12 × 20ms LiveKit frames = ~240ms silence
                               # → end of utterance detected
MIN_SPEECH_FRAMES = 5          # ignore utterances shorter than ~100ms (noise)


class UserTranscriber:
    """
    Drop-in component that wraps faster-whisper.

    Usage (inside bridge._handle_stream):
    --------------------------------------
    transcriber = UserTranscriber(
        on_transcript=transcript_manager.add_user_turn,
        model_size="base",
        language="en",
    )
    async for frame_event in stream:
        pcm_int16 = np.frombuffer(frame_event.frame.data, dtype=np.int16)
        await transcriber.push_frame(pcm_int16)
    """

    def __init__(
        self,
        on_transcript: Callable[[str], None],
        model_size: str = "base",
        language: Optional[str] = "en",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        """
        Parameters
        ----------
        on_transcript : callback receiving the transcribed string
        model_size    : 'tiny' | 'base' | 'small' | 'medium'
        language      : ISO 639-1 code or None for auto-detect
        device        : 'cpu' | 'cuda'  (use 'cuda' on RunPod GPU)
        compute_type  : 'int8' (CPU) | 'float16' (GPU)
        """
        self._on_transcript = on_transcript
        self._language = language

        # Load Whisper model once at startup
        logger.info(
            "Loading faster-whisper model='%s' device='%s' compute='%s'",
            model_size, device, compute_type,
        )
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                model_size, device=device, compute_type=compute_type
            )
            logger.info("faster-whisper model loaded ✓")
        except ImportError:
            raise RuntimeError(
                "faster-whisper not installed. Run: pip install faster-whisper"
            )

        # ── VAD state ─────────────────────────────────────────────────────────
        self._speech_frames: list[np.ndarray] = []   # raw 48kHz int16 frames
        self._silence_count = 0
        self._in_speech = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def push_frame(self, pcm_int16: np.ndarray):
        """
        Push one LiveKit audio frame (48kHz int16 mono).
        Call this for every frame in bridge._handle_stream().
        Non-blocking — transcription runs in a thread pool executor.
        """
        rms = float(np.sqrt(np.mean(pcm_int16.astype(np.float32) ** 2)))
        is_speech = rms > RMS_SPEECH_THRESHOLD

        if is_speech:
            self._silence_count = 0
            if not self._in_speech:
                self._in_speech = True
                logger.debug("VAD: speech start  rms=%.0f", rms)
            self._speech_frames.append(pcm_int16)

        else:
            if self._in_speech:
                self._silence_count += 1
                self._speech_frames.append(pcm_int16)  # keep trailing silence

                if self._silence_count >= SILENCE_FRAMES_CUTOFF:
                    # End of utterance — transcribe
                    if len(self._speech_frames) >= MIN_SPEECH_FRAMES:
                        frames_copy = list(self._speech_frames)
                        asyncio.ensure_future(
                            self._transcribe_utterance(frames_copy)
                        )
                    self._speech_frames = []
                    self._silence_count = 0
                    self._in_speech = False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _transcribe_utterance(self, frames: list[np.ndarray]):
        """
        Runs faster-whisper in a thread-pool executor so it doesn't
        block the asyncio event loop.
        """
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._run_whisper, frames)
        if text:
            self._on_transcript(text)

    def _run_whisper(self, frames: list[np.ndarray]) -> str:
        """Synchronous — called from executor thread."""
        t0 = time.perf_counter()

        # 1. Concatenate all int16 frames
        audio_int16 = np.concatenate(frames)

        # 2. Convert 48kHz int16 → 16kHz float32 (Whisper requirement)
        audio_f32 = audio_int16.astype(np.float32) / 32768.0
        target_len = int(len(audio_f32) * WHISPER_SAMPLE_RATE / LIVEKIT_SAMPLE_RATE)
        x_old = np.linspace(0, len(audio_f32) - 1, len(audio_f32))
        x_new = np.linspace(0, len(audio_f32) - 1, target_len)
        audio_16k = np.interp(x_new, x_old, audio_f32).astype(np.float32)

        # 3. Transcribe
        segments, info = self._model.transcribe(
            audio_16k,
            language=self._language,
            beam_size=1,           # fastest
            vad_filter=True,       # built-in Silero VAD inside Whisper
            vad_parameters=dict(min_silence_duration_ms=300),
        )
        text = " ".join(s.text for s in segments).strip()

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "Whisper transcribed in %.0fms → '%s'  lang=%s",
            elapsed, text, info.language,
        )
        return text