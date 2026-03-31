import asyncio
import logging
from typing import Callable, Optional
import numpy as np
import websockets
from livekit import rtc
import sphn
logger = logging.getLogger("personaplex.bridge")
LIVEKIT_SAMPLE_RATE  = 48_000
MOSHI_SAMPLE_RATE    = 24_000
MOSHI_FRAME_SAMPLES  = 1_920   # 80ms at 24kHz
MSG_HANDSHAKE = 0x00
MSG_AUDIO     = 0x01
MSG_TEXT      = 0x02

class PersonaPlexBridge:
    def __init__(
        self,
        ws_url: str,
        on_text_callback: Optional[Callable[[str], None]] = None,
        on_state_callback: Optional[Callable[[str], None]] = None,
    ):
        self.ws_url              = ws_url
        self._running            = False
        self._handshake_event    = asyncio.Event()
        self._on_text_callback   = on_text_callback
        self._on_state_callback  = on_state_callback
        # Opus codec via sphn
        self._opus_encoder = sphn.OpusStreamWriter(MOSHI_SAMPLE_RATE)
        self._opus_decoder = sphn.OpusStreamReader(MOSHI_SAMPLE_RATE)
        # Audio buffer and stats
        self._buffer           = np.array([], dtype=np.float32)
        self._frames_sent      = 0
        self._frames_received  = 0
        self._mic_active       = False
 
    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _emit_state(self, state: str):
        logger.info("[STATE] %s", state)
        if self._on_state_callback:
            try:
                self._on_state_callback(state)
            except Exception:
                pass
    def _emit_text(self, text: str):
        logger.info("[AI] %s", text)
        if self._on_text_callback:
            try:
                self._on_text_callback(text)
            except Exception:
                pass
    # ── Audio helpers ─────────────────────────────────────────────────────────
    def _encode_opus(self, pcm_float32: np.ndarray) -> bytes:
        """Encode float32 PCM to Opus bytes via sphn."""
        self._opus_encoder.append_pcm(pcm_float32)
        chunks = []
        while True:
            data = self._opus_encoder.read_bytes()
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)
    def _decode_opus(self, ogg_bytes: bytes) -> Optional[np.ndarray]:
        """Decode Opus bytes to float32 PCM via sphn."""
        if not ogg_bytes:
            return None
        self._opus_decoder.append_bytes(ogg_bytes)
        return self._opus_decoder.read_pcm()
    @staticmethod
    def _resample_to_24k(pcm_int16: np.ndarray) -> np.ndarray:
        """48kHz int16 → 24kHz float32"""
        if len(pcm_int16) == 0:
            return np.array([], dtype=np.float32)
        f = pcm_int16.astype(np.float32) / 32768.0
        out_len = len(f) // 2
        if out_len == 0:
            return np.array([], dtype=np.float32)
        x_old = np.linspace(0, len(f) - 1, len(f))
        x_new = np.linspace(0, len(f) - 1, out_len)
        return np.interp(x_new, x_old, f).astype(np.float32)
    @staticmethod
    def _upsample_to_48k(pcm_float32: np.ndarray) -> np.ndarray:
        """24kHz float32 → 48kHz int16"""
        if len(pcm_float32) == 0:
            return np.array([], dtype=np.int16)
        out_len   = len(pcm_float32) * 2
        x_old     = np.linspace(0, len(pcm_float32) - 1, len(pcm_float32))
        x_new     = np.linspace(0, len(pcm_float32) - 1, out_len)
        resampled = np.interp(x_new, x_old, pcm_float32)
        return (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16)
    # ── Main entry point ──────────────────────────────────────────────────────
    async def run(self, room: rtc.Room, local_participant: rtc.LocalParticipant):
        logger.info("Connecting to PersonaPlex at %s...", self.ws_url[:80])
        self._emit_state("connecting")
        try:
            async with websockets.connect(
                self.ws_url,
                additional_headers={"User-Agent": "moshi-client/1.0"},
                max_size=10 * 1024 * 1024,
                ping_interval=None,
                ping_timeout=None,
                open_timeout=30,
            ) as ws:
                self._running = True
                self._emit_state("connected")
                logger.info("PersonaPlex WebSocket connected")
                # Publish audio track to LiveKit so browser hears PersonaPlex
                audio_source = rtc.AudioSource(
                    sample_rate=LIVEKIT_SAMPLE_RATE,
                    num_channels=1,
                )
                track = rtc.LocalAudioTrack.create_audio_track(
                    "personaplex-audio", audio_source
                )
                await local_participant.publish_track(track)
                logger.info("Audio track published to LiveKit room")
                # Run both loops concurrently
                await asyncio.gather(
                    self._inbound_loop(room, ws),
                    self._outbound_loop(ws, audio_source),
                )
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error("WebSocket rejected HTTP %d", e.status_code)
            self._emit_state("error")
        except websockets.exceptions.ConnectionClosedError as e:
            logger.error("WebSocket closed: %s", e)
            self._emit_state("disconnected")
        except TimeoutError:
            logger.error("WebSocket timed out — is RunPod running?")
            self._emit_state("timeout")
        except Exception as e:
            logger.error("Bridge error: %s", e, exc_info=True)
            self._emit_state("error")
        finally:
            self._running = False
            self._emit_state("stopped")
            logger.info(
                "Bridge stopped — sent %d frames, received %d frames",
                self._frames_sent, self._frames_received,
            )
    # ── Inbound: LiveKit mic → PersonaPlex ────────────────────────────────────
    async def _inbound_loop(self, room: rtc.Room, ws) -> None:
        """
        Receive mic audio from browser via LiveKit.
        Resample to 24kHz, Opus-encode, send to PersonaPlex.

        FIX: We no longer prime with silence frames before a real track
        arrives.  Sending silence immediately after the handshake caused
        PersonaPlex to trigger its greeting / system-prompt response before
        the user had a chance to speak.  Instead we wait for the first real
        mic track, then start the 80ms send loop (which will naturally send
        silence-padding only while the buffer is empty, NOT before a track
        is connected).
        """
        logger.info("Inbound loop: waiting for handshake...")
        # Wait for PersonaPlex handshake before sending audio
        try:
            await asyncio.wait_for(self._handshake_event.wait(), timeout=15)
            logger.info("Handshake received — waiting for mic track")
        except asyncio.TimeoutError:
            logger.warning("No handshake after 15s — will proceed once mic arrives")

        silence = np.zeros(MOSHI_FRAME_SAMPLES, dtype=np.float32)

        # ── Subscribe to browser mic track ────────────────────────────────────
        # Gate: the send loop only starts after at least one mic track arrives.
        self._mic_track_ready = asyncio.Event()

        async def _handle_stream(stream: rtc.AudioStream, identity: str) -> None:
            logger.info("🎤 Mic stream started from: %s", identity)
            # Signal that a real track is now connected so the send loop begins.
            self._mic_track_ready.set()
            async for frame_event in stream:
                if not self._running:
                    break
                try:
                    pcm_int16 = np.frombuffer(frame_event.frame.data, dtype=np.int16)
                    pcm_24k   = self._resample_to_24k(pcm_int16)
                    self._buffer = np.concatenate([self._buffer, pcm_24k])
                    # Log mic activity
                    rms = float(np.sqrt(np.mean(pcm_int16.astype(np.float32) ** 2)))
                    if rms > 500:
                        if not self._mic_active:
                            logger.info("🎤 Mic ACTIVE! RMS=%.0f", rms)
                            self._mic_active = True
                except Exception as e:
                    logger.warning("Mic frame error: %s", e)

        def subscribe_to_track(track, participant):
            """Subscribe to an audio track and start reading."""
            identity = getattr(participant, "identity", "unknown")
            logger.info("🎧 Subscribing to mic track from: %s", identity)
            stream = rtc.AudioStream(track, sample_rate=LIVEKIT_SAMPLE_RATE)
            asyncio.ensure_future(_handle_stream(stream, identity))

        # Subscribe to NEW tracks
        @room.on("track_subscribed")
        def on_track_subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                subscribe_to_track(track, participant)

        # Also subscribe to EXISTING tracks from already-connected participants
        logger.info("Checking for existing participants with mic tracks...")
        for participant in room.remote_participants.values():
            logger.info("Found participant: %s", participant.identity)
            for pub in participant.track_publications.values():
                logger.info("  Track: %s, kind=%s, subscribed=%s",
                            pub.sid, pub.kind, pub.subscribed)
                if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track:
                    logger.info("  ✅ Subscribing to EXISTING mic track!")
                    subscribe_to_track(pub.track, participant)

        # ── Wait for a real mic track before starting the send loop ──────────
        # This is the key fix: we do NOT send any audio (not even silence) to
        # PersonaPlex until the browser's microphone track has connected.
        # Without this gate, PersonaPlex received silence frames immediately
        # after the handshake and responded with its opening greeting, which
        # appeared as the system-prompt leaking into the conversation.
        logger.info("Waiting for browser mic track before starting send loop...")
        try:
            await asyncio.wait_for(self._mic_track_ready.wait(), timeout=60)
            logger.info("Mic track ready — starting send loop")
        except asyncio.TimeoutError:
            logger.warning("No mic track after 60s — starting send loop anyway")

        # ── Send loop: 80ms real-time pacing ─────────────────────────────────
        while self._running:
            loop_start = asyncio.get_event_loop().time()
            # Use real audio if available, else send silence
            if len(self._buffer) >= MOSHI_FRAME_SAMPLES:
                chunk         = self._buffer[:MOSHI_FRAME_SAMPLES]
                self._buffer  = self._buffer[MOSHI_FRAME_SAMPLES:]
                if self._mic_active:
                    logger.debug("Sending REAL audio frame")
            else:
                chunk = silence
            # Encode and send
            ogg = self._encode_opus(chunk)
            if ogg:
                try:
                    await ws.send(bytes([MSG_AUDIO]) + ogg)
                    self._frames_sent += 1
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WS closed during send")
                    self._running = False
                    break
                except Exception as e:
                    logger.error("Send error: %s", e)
                    break
            # Maintain precise 80ms cadence
            elapsed    = asyncio.get_event_loop().time() - loop_start
            sleep_time = max(0.0, 0.08 - elapsed)
            await asyncio.sleep(sleep_time)
    # ── Outbound: PersonaPlex → LiveKit speaker ───────────────────────────────
    async def _outbound_loop(self, ws, audio_source: rtc.AudioSource) -> None:
        """
        Receive Opus audio from PersonaPlex.
        Decode to PCM and publish to LiveKit so browser hears the response.
        """
        logger.info("Outbound loop started (PersonaPlex → LiveKit)")
        async for message in ws:
            if not self._running:
                break
            if not isinstance(message, bytes) or len(message) < 1:
                continue
            msg_type = message[0]
            payload  = message[1:]
            if msg_type == MSG_HANDSHAKE:
                logger.info("Handshake received from PersonaPlex")
                self._handshake_event.set()
            elif msg_type == MSG_AUDIO:
                try:
                    pcm_24k = self._decode_opus(payload)
                    if pcm_24k is None or len(pcm_24k) == 0:
                        continue
                    pcm_48k = self._upsample_to_48k(pcm_24k)
                    if len(pcm_48k) == 0:
                        continue
                    await audio_source.capture_frame(
                        rtc.AudioFrame(
                            data=pcm_48k.tobytes(),
                            sample_rate=LIVEKIT_SAMPLE_RATE,
                            num_channels=1,
                            samples_per_channel=len(pcm_48k),
                        )
                    )
                    self._frames_received += 1
                    if self._frames_received == 1:
                        logger.info("🔊 First audio frame received from PersonaPlex!")
                    elif self._frames_received % 100 == 0:
                        logger.info(
                            "🔊 Audio flowing — %d frames from PersonaPlex",
                            self._frames_received,
                        )
                except Exception as e:
                    logger.warning("Outbound frame error: %s", e)
            elif msg_type == MSG_TEXT:
                try:
                    text = payload.decode("utf-8").strip()
                    if text:
                        self._emit_text(text)
                except UnicodeDecodeError:
                    pass
    def stop(self) -> None:
        self._running = False
        logger.info(
            "Bridge stop requested — sent %d / received %d frames",
            self._frames_sent, self._frames_received,
        )
    def get_stats(self) -> dict:
        return {
            "frames_sent":     self._frames_sent,
            "frames_received": self._frames_received,
            "running":         self._running,
        }