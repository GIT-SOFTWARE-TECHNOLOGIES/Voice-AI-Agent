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
        
        # Simple noise gate
        self._noise_floor = 0.01  # Threshold for silence detection

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
        """48kHz int16 → 24kHz float32 with better quality (simple lowpass + decimate)."""
        if len(pcm_int16) == 0:
            return np.array([], dtype=np.float32)
        
        # Convert to float32 [-1, 1]
        pcm_float = pcm_int16.astype(np.float32) / 32768.0
        
        # Simple anti-aliasing: average pairs of samples (crude lowpass filter)
        # This reduces aliasing artifacts compared to naive decimation
        if len(pcm_float) % 2 != 0:
            pcm_float = pcm_float[:-1]  # Make even length
        
        # Average adjacent samples for better quality downsampling
        downsampled = (pcm_float[0::2] + pcm_float[1::2]) / 2.0
        
        return downsampled.astype(np.float32)
 
    @staticmethod
    def _upsample_to_48k(pcm_float32: np.ndarray) -> np.ndarray:
        """24kHz float32 → 48kHz int16 with linear interpolation (smoother output)."""
        if len(pcm_float32) == 0:
            return np.array([], dtype=np.int16)
        
        # Linear interpolation upsampling (smoother than just repeating samples)
        out_len = len(pcm_float32) * 2
        x_old = np.arange(len(pcm_float32), dtype=np.float32)
        x_new = np.linspace(0, len(pcm_float32) - 1, out_len)
        
        upsampled = np.interp(x_new, x_old, pcm_float32)
        
        # Soft clipping to reduce harsh distortion
        upsampled = np.tanh(upsampled * 1.2) / 1.2
        
        # Convert to int16 with proper scaling
        return (np.clip(upsampled, -1.0, 1.0) * 32767).astype(np.int16)
 
    @staticmethod
    def _apply_noise_gate(pcm: np.ndarray, threshold: float = 0.01) -> np.ndarray:
        """Simple noise gate - reduce volume when below threshold."""
        rms = np.sqrt(np.mean(pcm ** 2))
        if rms < threshold:
            # Apply gentle attenuation for quiet frames
            return pcm * 0.1
        return pcm
 
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
        """Receive mic audio from browser via LiveKit."""
        logger.info("Inbound loop: waiting for handshake...")
 
        try:
            await asyncio.wait_for(self._handshake_event.wait(), timeout=15)
            logger.info("Handshake received — starting mic stream")
        except asyncio.TimeoutError:
            logger.warning("No handshake after 15s — sending audio anyway")
 
        # Prime with silence
        logger.info("Priming Opus encoder with silence...")
        silence = np.zeros(MOSHI_FRAME_SAMPLES, dtype=np.float32)
        for _ in range(12):
            ogg = self._encode_opus(silence)
            if ogg:
                try:
                    await ws.send(bytes([MSG_AUDIO]) + ogg)
                except Exception:
                    break
            await asyncio.sleep(0.08)
        logger.info("Priming complete — ready for your voice")
 
        async def _handle_stream(stream: rtc.AudioStream, identity: str) -> None:
            logger.info("🎤 Mic stream started from: %s", identity)
            frame_count = 0
            async for frame_event in stream:
                if not self._running:
                    break
                try:
                    pcm_int16 = np.frombuffer(frame_event.frame.data, dtype=np.int16)
                    pcm_24k   = self._resample_to_24k(pcm_int16)
                    self._buffer = np.concatenate([self._buffer, pcm_24k])
 
                    # Log mic activity
                    rms = float(np.sqrt(np.mean(pcm_int16.astype(np.float32) ** 2)))
                    frame_count += 1
                    if rms > 500:
                        if not self._mic_active:
                            logger.info("🎤 Mic ACTIVE! RMS=%.0f", rms)
                            self._mic_active = True
                    elif self._mic_active and rms < 200:
                        self._mic_active = False
                except Exception as e:
                    logger.warning("Mic frame error: %s", e)
 
        def subscribe_to_track(track, participant):
            identity = getattr(participant, "identity", "unknown")
            logger.info("🎧 Subscribing to mic track from: %s", identity)
            stream = rtc.AudioStream(track, sample_rate=LIVEKIT_SAMPLE_RATE)
            asyncio.ensure_future(_handle_stream(stream, identity))
 
        @room.on("track_subscribed")
        def on_track_subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                subscribe_to_track(track, participant)
 
        # Subscribe to existing tracks
        logger.info("Checking for existing participants with mic tracks...")
        for participant in room.remote_participants.values():
            logger.info("Found participant: %s", participant.identity)
            for pub in participant.track_publications.values():
                if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track:
                    logger.info("  ✅ Subscribing to EXISTING mic track!")
                    subscribe_to_track(pub.track, participant)
 
        # Send loop
        while self._running:
            loop_start = asyncio.get_event_loop().time()
 
            if len(self._buffer) >= MOSHI_FRAME_SAMPLES:
                chunk         = self._buffer[:MOSHI_FRAME_SAMPLES]
                self._buffer  = self._buffer[MOSHI_FRAME_SAMPLES:]
            else:
                chunk = silence
 
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
 
            elapsed    = asyncio.get_event_loop().time() - loop_start
            sleep_time = max(0.0, 0.08 - elapsed)
            await asyncio.sleep(sleep_time)
 
    # ── Outbound: PersonaPlex → LiveKit speaker ───────────────────────────────
 
    async def _outbound_loop(self, ws, audio_source: rtc.AudioSource) -> None:
        """Receive Opus audio from PersonaPlex and play to browser."""
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
                    
                    # Apply light noise gate
                    pcm_24k = self._apply_noise_gate(pcm_24k, threshold=0.005)
 
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
                        logger.info("🔊 Audio flowing — %d frames", self._frames_received)
 
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
        logger.info("Bridge stopped — sent %d / received %d frames", 
                   self._frames_sent, self._frames_received)
 
    def get_stats(self) -> dict:
        return {
            "frames_sent":     self._frames_sent,
            "frames_received": self._frames_received,
            "running":         self._running,
        }