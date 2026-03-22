import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv
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

if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    raise ValueError("LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET must be set in .env")

if not PERSONAPLEX_WS_URL:
    raise ValueError("PERSONAPLEX_WS_URL is not set in .env")


class PersonaPlexAgent:
    """PersonaPlex agent that connects to a LiveKit room."""

    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room: rtc.Room = None
        self.bridge: PersonaPlexBridge = None

    async def run(self):
        """Run the agent."""
        # Generate agent token
        token = AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity("personaplex-agent") \
            .with_name("PersonaPlex Agent") \
            .with_grants(VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=True,
            ))

        # Create room
        self.room = rtc.Room()

        # Set up event handlers
        @self.room.on("participant_connected")
        def on_participant_connected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant joined: {participant.identity}")

        @self.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant left: {participant.identity}")

        @self.room.on("disconnected")
        def on_disconnected():
            logger.info("Disconnected from room")

        logger.info(f"Connecting to LiveKit room: {self.room_name}")

        try:
            await self.room.connect(LIVEKIT_URL, token.to_jwt())
            logger.info(f"Connected to room: {self.room.name}")

            # Log existing participants (use remote_participants, not participants)
            for participant in self.room.remote_participants.values():
                logger.info(f"Found participant: {participant.identity}")

            logger.info(f"PersonaPlex URL: {PERSONAPLEX_WS_URL[:50]}...")

            # Create bridge with callbacks
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

            # Run the bridge
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


async def run_agent(room_name: str):
    """Run the PersonaPlex agent in the specified room."""
    agent = PersonaPlexAgent(room_name)
    await agent.run()


def main():
    parser = argparse.ArgumentParser(description="PersonaPlex LiveKit Agent")
    parser.add_argument("--room", default="personaplex-test", help="Room name to join")
    args = parser.parse_args()

    asyncio.run(run_agent(args.room))


if __name__ == "__main__":
    main()