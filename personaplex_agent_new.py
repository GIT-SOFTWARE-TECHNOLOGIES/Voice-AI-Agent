"""
personaplex_agent_new.py  — with full transcript + PayU payment support
========================================================================
CHANGES FROM ORIGINAL (marked with  # ← PAYU):
  1. Import PaymentBridge
  2. Create PaymentBridge in PersonaPlexAgent.run()
  3. Hook on_payment_ready  → feeds payment link into transcript
  4. Hook on_payment_confirmed → logs and records payment confirmation
  5. Forward every transcript turn to payment_bridge.notify_turn()
  6. Call payment_bridge.stop() in the finally block
"""

import argparse
import asyncio
import logging
import os
import re as _re

from dotenv import load_dotenv
from livekit import api as livekit_api
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from src.personaplex.bridge import PersonaPlexBridge
from src.transcript.manager import TranscriptManager
from src.transcript.user_transcriber import UserTranscriber
from crm_extractor import extract_crm

# ← PAYU
from src.payment.payment_bridge import PaymentBridge

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

WHISPER_MODEL   = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANG    = os.getenv("WHISPER_LANG", "en")

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
        self.payment_bridge: PaymentBridge = None  # ← PAYU

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

        # ── Transcript objects ────────────────────────────────────────────────
        transcript = TranscriptManager(room_name=self.room_name)

        user_transcriber = UserTranscriber(
            on_transcript=transcript.add_user_turn,
            model_size=WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
            language=WHISPER_LANG,
        )

        # ── PAYU: Create PaymentBridge ────────────────────────────────────────
        room_num_match = _re.search(r"(\d{2,4})", self.room_name)
        initial_room_number = room_num_match.group(1) if room_num_match else ""

        def on_payment_ready(payment_link: str, bill_text: str, room_number: str):
            logger.info("PAYMENT LINK READY — room=%s link=%s", room_number, payment_link)
            # Record in transcript so the session log captures it
            transcript.add_agent_turn(
                f"I've created your bill. Please pay here: {payment_link}"
            )
            if self.bridge and self.bridge._on_text_callback:
                try:
                    self.bridge._on_text_callback(
                        f"[PayU] Payment link: {payment_link}"
                    )
                except Exception:
                    pass

        def on_payment_confirmed(txn_id: str, amount: str, room_number: str):
            logger.info(
                "PAYMENT CONFIRMED — txn=%s amount=%s room=%s",
                txn_id, amount, room_number,
            )
            transcript.add_agent_turn(
                f"Payment of Rs {amount} confirmed for order {txn_id}. Thank you!"
            )
            if self.bridge and self.bridge._on_text_callback:
                try:
                    self.bridge._on_text_callback(
                        f"[PayU] Payment confirmed Rs {amount} txn={txn_id}"
                    )
                except Exception:
                    pass

        self.payment_bridge = PaymentBridge(
            on_payment_ready=on_payment_ready,
            on_payment_confirmed=on_payment_confirmed,
            room_number=initial_room_number,
        )

        # ── Patch TranscriptManager to also feed PaymentBridge ────────────────
        _orig_user  = transcript.add_user_turn
        _orig_agent = transcript.add_agent_turn

        def _patched_user(text: str):
            _orig_user(text)
            self.payment_bridge.notify_turn("user", text)

        def _patched_agent(text: str):
            _orig_agent(text)
            self.payment_bridge.notify_turn("agent", text)

        transcript.add_user_turn  = _patched_user   # type: ignore[method-assign]
        transcript.add_agent_turn = _patched_agent  # type: ignore[method-assign]

        # Also point UserTranscriber at the patched version
        user_transcriber._on_transcript = _patched_user
        # ─────────────────────────────────────────────────────────────────────

        try:
            await self.room.connect(LIVEKIT_URL, token.to_jwt())
            logger.info(f"Connected to room: {self.room.name}")

            def on_text(text: str):
                logger.info(f"[PersonaPlex] {text}")

            def on_state(state: str):
                logger.info(f"[Bridge] {state}")

            self.bridge = PersonaPlexBridge(
                ws_url=PERSONAPLEX_WS_URL,
                on_text_callback=on_text,
                on_state_callback=on_state,
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
            await user_transcriber.close()
            transcript.flush_to_db()
            logger.info(
                "Session saved. ID=%s  turns=%d",
                transcript.session_id, transcript.turn_count,
            )
            extract_crm(
                session_id=transcript.session_id,
                room_name=transcript.room_name,
                turns=transcript.get_turns(),
            )
            # ← PAYU: cancel background polling
            if self.payment_bridge:
                self.payment_bridge.stop()

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