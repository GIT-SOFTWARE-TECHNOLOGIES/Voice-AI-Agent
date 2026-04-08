"""
personaplex_agent_new.py  — with full transcript support
=========================================================
CHANGES FROM ORIGINAL (marked with  # ← NEW):
  1. Import TranscriptManager and UserTranscriber
  2. Create both objects in PersonaPlexAgent.run()
  3. Pass them into PersonaPlexBridge
  4. flush_to_db() in the finally block
"""

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit import api as livekit_api
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from src.personaplex.bridge import PersonaPlexBridge

# ← NEW
from src.transcript.manager import TranscriptManager
from src.transcript.user_transcriber import UserTranscriber

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("personaplex_agent")
logging.getLogger("livekit").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

LIVEKIT_URL        = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
PERSONAPLEX_WS_URL = os.getenv("PERSONAPLEX_WS_URL", "")
POLL_INTERVAL      = float(os.getenv("AGENT_POLL_INTERVAL", "2"))

# ← NEW — Whisper settings from .env (sensible defaults)
WHISPER_MODEL   = os.getenv("WHISPER_MODEL", "base")   # tiny | base | small
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE", "cpu")   # cpu | cuda
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8") # int8 (cpu) | float16 (cuda)
WHISPER_LANG    = os.getenv("WHISPER_LANG", "en")      # language code

if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    raise ValueError("LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET must be set")
if not PERSONAPLEX_WS_URL:
    raise ValueError("PERSONAPLEX_WS_URL is not set")


def _livekit_http_url(ws_url: str) -> str:
    return ws_url.replace("wss://", "https://").replace("ws://", "http://")


class PersonaPlexAgent:

    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room: rtc.Room = None
        self.bridge: PersonaPlexBridge = None

    async def run(self):
        token = (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity("personaplex-agent")
            .with_name("PersonaPlex Agent")
            .with_grants(VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=True,
            ))
        )

        self.room = rtc.Room()

        @self.room.on("participant_connected")
        def on_participant_connected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant joined: {participant.identity}")

        @self.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant left: {participant.identity}")
            if not self.room.remote_participants and self.bridge:
                self.bridge.stop()

        @self.room.on("disconnected")
        def on_disconnected():
            logger.info("Disconnected from room")

        logger.info(f"Connecting to LiveKit room: {self.room_name}")

        # ── ← NEW — create transcript objects ────────────────────────────────

        transcript = TranscriptManager(room_name=self.room_name)

        # UserTranscriber loads Whisper once here (takes ~2-5s on first call)
        user_transcriber = UserTranscriber(
            on_transcript=transcript.add_user_turn,
            model_size=WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
            language=WHISPER_LANG,
        )

        # ── ─────────────────────────────────────────────────────────────────

        try:
            await self.room.connect(LIVEKIT_URL, token.to_jwt())
            logger.info(f"Connected to room: {self.room.name}")

            def on_text(text: str):
                # note: add_agent_turn is now called inside bridge._emit_text
                # this callback is still here for any extra processing you want
                logger.info(f"[PersonaPlex] {text}")

            def on_state(state: str):
                logger.info(f"[Bridge] {state}")

            self.bridge = PersonaPlexBridge(
                ws_url=PERSONAPLEX_WS_URL,
                on_text_callback=on_text,
                on_state_callback=on_state,
                # ← NEW — pass transcript objects into bridge
                transcript_manager=transcript,
                user_transcriber=user_transcriber,
            )

            try:
                await self.bridge.run(self.room, self.room.local_participant)
            except Exception as e:
                logger.error(f"Bridge error: {e}", exc_info=True)
            finally:
                self.bridge.stop()

        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
        finally:
            logger.info("Agent stopped")
            # ← NEW — save everything to SQLite on session end
            transcript.flush_to_db()
            logger.info(
                "Session saved. ID=%s  turns=%d",
                transcript.session_id, transcript.turn_count,
            )
            if self.room:
                await self.room.disconnect()


# ── Dispatch loop (unchanged) ──────────────────────────────────────────────

_active_rooms: set[str] = set()


async def _agent_task(room_name: str) -> None:
    try:
        agent = PersonaPlexAgent(room_name)
        await agent.run()
    finally:
        _active_rooms.discard(room_name)


async def dispatch_loop() -> None:
    lk_api = livekit_api.LiveKitAPI(
        url=_livekit_http_url(LIVEKIT_URL),
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )
    logger.info("Dispatch loop started — polling every %.1fs", POLL_INTERVAL)
    try:
        while True:
            try:
                rooms_resp = await lk_api.room.list_rooms(
                    livekit_api.ListRoomsRequest()
                )
                for room_info in rooms_resp.rooms:
                    room_name = room_info.name
                    if room_name in _active_rooms:
                        continue
                    participants_resp = await lk_api.room.list_participants(
                        livekit_api.ListParticipantsRequest(room=room_name)
                    )
                    human_participants = [
                        p for p in participants_resp.participants
                        if p.identity != "personaplex-agent"
                    ]
                    if human_participants:
                        logger.info("Room '%s' — spawning agent", room_name)
                        _active_rooms.add(room_name)
                        asyncio.ensure_future(_agent_task(room_name))
            except Exception as e:
                logger.warning(f"Dispatch poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await lk_api.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", default=None)
    args = parser.parse_args()
    if args.room:
        asyncio.run(PersonaPlexAgent(args.room).run())
    else:
        asyncio.run(dispatch_loop())


if __name__ == "__main__":
    main()