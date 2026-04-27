"""
run_hubspot_payment_poller.py
─────────────────────────────
Standalone poller that:
  1. Fetches pending Food Orders from HubSpot CRM every 30 seconds
  2. Creates a PayU payment bill for each
  3. Updates HubSpot with the payment link
  4. Polls PayU and marks the HubSpot record as paid when payment succeeds

Run:
    python run_hubspot_payment_poller.py

Or add to docker-compose as a service (see below).
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hubspot_payment_poller")

from src.payment.payment_bridge import HubSpotPaymentBridge

POLL_SECS = float(os.getenv("HUBSPOT_POLL_SECS", "30"))


def on_payment_ready(payment_link: str, bill_text: str, room_number: str):
    logger.info("PAYMENT LINK READY — room=%s link=%s", room_number, payment_link)
    logger.info("Bill:\n%s", bill_text)


def on_payment_confirmed(txn_id: str, amount: str, room_number: str):
    logger.info(
        "PAYMENT CONFIRMED — room=%s txn=%s amount=Rs%s",
        room_number, txn_id, amount,
    )


async def main():
    logger.info("HubSpot Payment Poller starting — poll every %.0fs", POLL_SECS)
    bridge = HubSpotPaymentBridge(
        on_payment_ready=on_payment_ready,
        on_payment_confirmed=on_payment_confirmed,
        poll_secs=POLL_SECS,
    )
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())