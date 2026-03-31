import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit import api as livekit_api
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from src.personaplex.bridge import PersonaPlexBridge

load_dotenv()

# ── Logger setup ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("personaplex_agent")

# Suppress noisy logs
logging.getLogger("livekit").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

# ── Config from .env ──────────────────────────────────────────────────────────
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
PERSONAPLEX_WS_URL = os.getenv("PERSONAPLEX_WS_URL", "")

# How often (seconds) the dispatch loop polls for new rooms
POLL_INTERVAL = float(os.getenv("AGENT_POLL_INTERVAL", "2"))

if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    raise ValueError("LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET must be set in .env")

if not PERSONAPLEX_WS_URL:
    raise ValueError("PERSONAPLEX_WS_URL is not set in .env")


# ── HTTP URL derived from WebSocket URL ───────────────────────────────────────
def _livekit_http_url(ws_url: str) -> str:
    """Convert ws:// or wss:// to http:// or https:// for the REST API."""
    return ws_url.replace("wss://", "https://").replace("ws://", "http://")


class PersonaPlexAgent:
    """PersonaPlex agent that connects to a LiveKit room."""

    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room: rtc.Room = None
        self.bridge: PersonaPlexBridge = None

    async def run(self):
        """Run the agent — connect to the room and start the bridge."""
        token = (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity("personaplex-agent")
            .with_name("PersonaPlex Agent")
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
        )

        self.room = rtc.Room()

        # ── Room event handlers ───────────────────────────────────────────────
        @self.room.on("participant_connected")
        def on_participant_connected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant joined: {participant.identity}")

        @self.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant left: {participant.identity}")
            # If the room is now empty, stop the bridge so the agent exits
            # cleanly and the dispatch loop can reuse the slot.
            if not self.room.remote_participants and self.bridge:
                logger.info("Room is empty — stopping bridge")
                self.bridge.stop()

        @self.room.on("disconnected")
        def on_disconnected():
            logger.info("Disconnected from room")

        logger.info(f"Connecting to LiveKit room: {self.room_name}")

        try:
            await self.room.connect(LIVEKIT_URL, token.to_jwt())
            logger.info(f"Connected to room: {self.room.name}")

            for participant in self.room.remote_participants.values():
                logger.info(f"Found existing participant: {participant.identity}")

            logger.info(f"PersonaPlex URL: {PERSONAPLEX_WS_URL[:50]}...")

            def on_text(text: str):
                logger.info(f"[PersonaPlex] {text}")

            def on_state(state: str):
                logger.info(f"[Bridge] {state}")

            logger.info("Starting audio bridge...")
            self.bridge = PersonaPlexBridge(
                ws_url=PERSONAPLEX_WS_URL,
                on_text_callback=on_text,
                on_state_callback=on_state,
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
            if self.room:
                await self.room.disconnect()
                logger.info("Room disconnected")


# ── Dispatch loop ─────────────────────────────────────────────────────────────

# Tracks rooms that already have an agent so we don't spawn duplicates.
_active_rooms: set[str] = set()


async def _agent_task(room_name: str) -> None:
    """Wrapper that removes the room from _active_rooms when the agent exits."""
    try:
        agent = PersonaPlexAgent(room_name)
        await agent.run()
    finally:
        _active_rooms.discard(room_name)
        logger.info(f"Agent slot freed for room: {room_name}")


async def dispatch_loop() -> None:
    """
    Poll LiveKit every POLL_INTERVAL seconds.
    For every room that has at least one human participant but no agent yet,
    spawn a PersonaPlexAgent task.
    """
    lk_api = livekit_api.LiveKitAPI(
        url=_livekit_http_url(LIVEKIT_URL),
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )

    logger.info(
        "Dispatch loop started — polling every %.1fs for new rooms", POLL_INTERVAL
    )

    try:
        while True:
            try:
                rooms_resp = await lk_api.room.list_rooms(livekit_api.ListRoomsRequest())
                for room_info in rooms_resp.rooms:
                    room_name = room_info.name

                    # Skip rooms where we've already spawned an agent
                    if room_name in _active_rooms:
                        continue

                    # Check whether there are human participants (not our agent)
                    participants_resp = await lk_api.room.list_participants(
                        livekit_api.ListParticipantsRequest(room=room_name)
                    )
                    human_participants = [
                        p
                        for p in participants_resp.participants
                        if p.identity != "personaplex-agent"
                    ]

                    if human_participants:
                        logger.info(
                            "Room '%s' has %d human participant(s) — spawning agent",
                            room_name,
                            len(human_participants),
                        )
                        _active_rooms.add(room_name)
                        asyncio.ensure_future(_agent_task(room_name))

            except Exception as e:
                logger.warning(f"Dispatch poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await lk_api.aclose()


async def run_agent(room_name: str):
    """Run a single agent in the specified room (--room mode)."""
    agent = PersonaPlexAgent(room_name)
    await agent.run()


def main():
    parser = argparse.ArgumentParser(description="PersonaPlex LiveKit Agent")
    parser.add_argument(
        "--room",
        default=None,
        help=(
            "Room name to join directly. "
            "Omit to run in dispatch mode (auto-joins any room with participants)."
        ),
    )
    args = parser.parse_args()

    if args.room:
        # Legacy single-room mode — useful for testing
        asyncio.run(run_agent(args.room))
    else:
        # Auto-dispatch mode: watch all rooms and join when humans arrive
        asyncio.run(dispatch_loop())


if __name__ == "__main__":
    main()