"""
payment_bridge.py — Wires the PersonaPlex voice agent directly to PayU worker
==============================================================================

Now uses direct imports from the same src/payment/ folder instead of HTTP calls.

Flow:
    Guest speaks
        → Whisper transcribes
            → notify_turn() called
                → detects service + items from transcript
                    → BillGenerator.create_bill()        (creates bill + saves to DB)
                        → PayUWorker.create_payment()    (generates PayU hash)
                            → on_payment_ready callback  (agent speaks the link)
                                → PayUWorker.check_payment_status() polls PayU API
                                    → on_payment_confirmed callback
"""

import asyncio
import logging
import os
import re
from typing import Callable, Optional

# ── Direct imports from the same src/payment/ folder ─────────────────────────
from .bill_generator import BillGenerator
from .payu_worker import PayUWorker
from .service_catalog import get_catalog
from .models import ServiceRequest, ServiceType, BillItem, PaymentStatus
from .config import BASE_URL

logger = logging.getLogger("payment.bridge")

PAYMENT_POLL_SECS = float(os.getenv("PAYMENT_POLL_SECS", "10"))

# ── Service type keyword detection ────────────────────────────────────────────
_SERVICE_KEYWORDS: dict[str, list[str]] = {
    "food_order":         ["food", "eat", "order", "hungry", "meal", "dinner",
                           "lunch", "breakfast", "menu", "dish", "snack",
                           "chicken", "naan", "biryani", "pizza", "burger",
                           "coffee", "tea", "juice", "beer", "coke", "pepsi",
                           "butter", "paneer", "dal", "rice", "roti"],
    "room_cleaning":      ["clean", "housekeeping", "tidy", "maid", "towel",
                           "sweep", "vacuum", "bed", "linen", "minibar",
                           "pillow", "blanket"],
    "cab_booking":        ["cab", "taxi", "ride", "airport", "pickup", "drop",
                           "car", "transport", "station", "railway"],
    "laundry":            ["laundry", "wash", "iron", "press", "dry clean",
                           "clothes", "shirt", "trouser", "suit"],
    "spa":                ["spa", "massage", "facial", "manicure", "pedicure",
                           "relax", "therapy", "beauty"],
    "restaurant_booking": ["restaurant", "reserve", "table", "booking",
                           "dining", "birthday", "anniversary", "cake"],
}

_NUMWORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a": 1, "an": 1,
}

_CONFIRMATION_PHRASES = [
    "i'll place", "placing your order", "ordering", "i'll arrange",
    "i'll book", "booking", "i'll send", "sending", "creating your bill",
    "let me", "right away", "certainly", "of course", "sure",
    "noted", "confirm", "arranged", "scheduled", "booked",
    "i will", "i'll get", "preparing",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_service_type(text: str) -> Optional[ServiceType]:
    lower = text.lower()
    scores: dict[str, int] = {}
    for svc, keywords in _SERVICE_KEYWORDS.items():
        scores[svc] = sum(1 for kw in keywords if kw in lower)
    best, count = max(scores.items(), key=lambda x: x[1])
    if count == 0:
        return None
    try:
        return ServiceType(best)
    except ValueError:
        return None


def _extract_items(text: str, service_type: ServiceType) -> list[BillItem]:
    """
    Scan transcript for catalog item names.
    Uses the real get_catalog() from service_catalog.py — same source
    of truth as the PayU worker itself.
    """
    catalog = get_catalog(service_type)   # dict[str, float]
    lower   = text.lower()
    found   = []
    seen    = set()

    for item_name, price in catalog.items():
        if item_name not in lower or item_name in seen:
            continue
        pattern = (
            r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an)"
            r"\s+" + re.escape(item_name)
        )
        m = re.search(pattern, lower)
        qty = int(m.group(1)) if m and m.group(1).isdigit() \
              else _NUMWORDS.get(m.group(1), 1) if m else 1
        found.append(BillItem(name=item_name, quantity=qty, unit_price=price))
        seen.add(item_name)

    # Fallback: add first catalog item if nothing detected
    if not found and catalog:
        default_name, default_price = next(iter(catalog.items()))
        found.append(BillItem(name=default_name, quantity=1, unit_price=default_price))

    return found


def _extract_room_number(text: str) -> str:
    m = re.search(r"room\s*(?:number\s*)?(\d{2,4})", text, re.IGNORECASE)
    return m.group(1) if m else "000"


def _extract_guest_info(turns: list[tuple[str, str]]) -> dict:
    full_text = " ".join(t for _, t in turns)
    info = {
        "guest_name":  "Guest",
        "guest_phone": "9999999999",
        "guest_email": "guest@hotel.com",
    }
    name_m = re.search(
        r"(?:my name is|i am|this is|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        full_text, re.IGNORECASE,
    )
    if name_m:
        info["guest_name"] = name_m.group(1).strip().title()
    phone_m = re.search(r"\b([6-9]\d{9})\b", full_text)
    if phone_m:
        info["guest_phone"] = phone_m.group(1)
    email_m = re.search(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", full_text, re.IGNORECASE)
    if email_m:
        info["guest_email"] = email_m.group(0)
    return info


# ── PaymentBridge ─────────────────────────────────────────────────────────────

class PaymentBridge:
    """
    Listens to transcript turns and triggers bill creation when a
    service request is detected.

    Parameters
    ----------
    on_payment_ready : callable(payment_link, bill_text, room_number)
        Fired when bill is created and payment link is ready.

    on_payment_confirmed : callable(txn_id, amount, room_number)
        Fired when PayU confirms payment success.

    room_number : str
        Extracted from LiveKit room name (e.g. "301" from "room-301").
    """

    def __init__(
        self,
        on_payment_ready: Optional[Callable[[str, str, str], None]] = None,
        on_payment_confirmed: Optional[Callable[[str, str, str], None]] = None,
        room_number: str = "",
    ):
        self._on_payment_ready     = on_payment_ready
        self._on_payment_confirmed = on_payment_confirmed
        self._room_number          = room_number

        self._turns: list[tuple[str, str]] = []
        self._created_keys: set[str]       = set()
        self._poll_tasks: dict[str, asyncio.Task] = {}

        # Lazily initialised so __init__ never raises if .env missing
        self._bill_generator: Optional[BillGenerator] = None
        self._payu_worker: Optional[PayUWorker]       = None

        self._min_turns = 3

    # ── Lazy init ─────────────────────────────────────────────────────────────

    def _get_bill_generator(self) -> BillGenerator:
        if self._bill_generator is None:
            self._bill_generator = BillGenerator()
        return self._bill_generator

    def _get_payu_worker(self) -> PayUWorker:
        if self._payu_worker is None:
            self._payu_worker = PayUWorker()
        return self._payu_worker

    # ── Public API ────────────────────────────────────────────────────────────

    def notify_turn(self, speaker: str, text: str) -> None:
        """Call after every transcript turn. speaker = 'user' or 'agent'"""
        self._turns.append((speaker, text))
        if speaker == "agent" and len(self._turns) >= self._min_turns:
            asyncio.ensure_future(self._maybe_create_bill())

    def set_room_number(self, room_number: str) -> None:
        self._room_number = room_number

    def stop(self) -> None:
        for task in self._poll_tasks.values():
            task.cancel()
        self._poll_tasks.clear()

    # ── Detection ─────────────────────────────────────────────────────────────

    async def _maybe_create_bill(self) -> None:
        recent   = self._turns[-6:]
        combined = " ".join(t for _, t in recent)

        # Agent must have confirmed
        agent_turns = [t for sp, t in recent if sp == "agent"]
        if not agent_turns:
            return
        last_agent = agent_turns[-1].lower()
        if not any(phrase in last_agent for phrase in _CONFIRMATION_PHRASES):
            return

        service_type = _detect_service_type(combined)
        if service_type is None:
            return

        items = _extract_items(combined, service_type)
        if not items:
            return

        room = self._room_number or _extract_room_number(combined) or "000"
        guest_info = _extract_guest_info(self._turns)

        # Deduplication
        item_key = f"{room}:{service_type.value}:{','.join(i.name for i in items)}"
        if item_key in self._created_keys:
            return
        self._created_keys.add(item_key)

        await self._create_bill_and_notify(
            service_type=service_type,
            room_number=room,
            items=items,
            guest_info=guest_info,
            notes=" ".join(t for sp, t in recent if sp == "user"),
        )

    # ── Bill creation ─────────────────────────────────────────────────────────

    async def _create_bill_and_notify(
        self,
        service_type: ServiceType,
        room_number: str,
        items: list[BillItem],
        guest_info: dict,
        notes: str = "",
    ) -> None:
        logger.info(
            "Creating bill — service=%s room=%s items=%s",
            service_type.value, room_number, [i.name for i in items],
        )
        try:
            # 1. ServiceRequest
            request = ServiceRequest(
                service_type=service_type,
                room_number=room_number,
                guest_name=guest_info["guest_name"],
                guest_phone=guest_info["guest_phone"],
                guest_email=guest_info["guest_email"],
                items=items,
                notes=notes[:200],
            )

            # 2. Generate bill (GST calculated, saved to DB)
            bill_gen = self._get_bill_generator()
            bill     = bill_gen.create_bill(request)

            # 3. Generate PayU payment hash
            payu     = self._get_payu_worker()
            pay_data = payu.create_payment(bill)

            # 4. Build the local payment page URL
            payment_link = payu.get_payment_page_url(bill)

            # 5. Save payment link to DB
            bill_gen.update_payment_link(bill.order_id, payment_link)

            # 6. Format bill as readable text for the agent to speak
            bill_text = bill_gen.format_bill_text(bill)

            logger.info(
                "Bill ready — order=%s total=Rs%.2f link=%s",
                bill.order_id, bill.total, payment_link,
            )

        except Exception as exc:
            logger.error("Failed to create bill: %s", exc, exc_info=True)
            return

        # 7. Notify agent
        if self._on_payment_ready:
            try:
                self._on_payment_ready(payment_link, bill_text, room_number)
            except Exception as exc:
                logger.warning("on_payment_ready callback error: %s", exc)

        # 8. Start polling PayU for confirmation
        task = asyncio.ensure_future(
            self._poll_for_confirmation(bill.order_id, room_number)
        )
        self._poll_tasks[bill.order_id] = task

    # ── Payment status polling ────────────────────────────────────────────────

    async def _poll_for_confirmation(self, order_id: str, room_number: str) -> None:
        """
        Polls PayU verify_payment API directly via PayUWorker.check_payment_status()
        No HTTP call to our own server — goes straight to PayU.
        """
        logger.info("Polling PayU for order=%s", order_id)
        max_attempts = int(3600 / max(PAYMENT_POLL_SECS, 5))

        try:
            payu = self._get_payu_worker()
        except Exception as exc:
            logger.error("PayUWorker init failed: %s", exc)
            return

        for attempt in range(max_attempts):
            await asyncio.sleep(PAYMENT_POLL_SECS)
            try:
                result = await payu.check_payment_status(order_id)
            except Exception as exc:
                logger.warning("Poll error (attempt %d): %s", attempt + 1, exc)
                continue

            # PayU response: { "transaction_details": { "<order_id>": { "status": "success", ... } } }
            txn_details = result.get("transaction_details", {})
            record      = txn_details.get(order_id, {})
            status      = record.get("status", "").lower()
            amount      = record.get("amt", "")

            if status == "success":
                logger.info("Payment confirmed! order=%s amount=Rs%s", order_id, amount)
                try:
                    self._get_bill_generator().update_bill_status(
                        order_id=order_id,
                        status=PaymentStatus.SUCCESS,
                        payu_txn_id=record.get("mihpayid", ""),
                        paid_at=record.get("addedon", ""),
                    )
                except Exception as exc:
                    logger.warning("DB update error: %s", exc)

                if self._on_payment_confirmed:
                    try:
                        self._on_payment_confirmed(order_id, amount, room_number)
                    except Exception as exc:
                        logger.warning("on_payment_confirmed callback error: %s", exc)
                return

            elif status in ("failure", "failed", "error"):
                logger.info("Payment failed for order=%s", order_id)
                try:
                    self._get_bill_generator().update_bill_status(
                        order_id=order_id,
                        status=PaymentStatus.FAILED,
                    )
                except Exception:
                    pass
                return

            logger.debug(
                "Still pending — order=%s attempt=%d status=%s",
                order_id, attempt + 1, status or "unknown",
            )

        logger.warning("Payment polling timed out for order=%s", order_id)


# ═══════════════════════════════════════════════════════════════════════════════
# HubSpot integration — added below PaymentBridge
# ═══════════════════════════════════════════════════════════════════════════════

class HubSpotPaymentBridge:
    """
    Polls HubSpot Food Orders → creates PayU bills → syncs status back.

    This runs as a background poller (like taxi-poller).
    Start it with: asyncio.ensure_future(bridge.run())

    It does 3 things:
    1. Fetches pending Food Orders from HubSpot every POLL_SECS seconds
    2. Creates a PayU bill + payment link for each pending order
    3. Updates HubSpot record with payment link, and later with paid status
    """

    def __init__(
        self,
        on_payment_ready: Optional[Callable[[str, str, str], None]] = None,
        on_payment_confirmed: Optional[Callable[[str, str, str], None]] = None,
        poll_secs: float = 30.0,
    ):
        self._on_payment_ready     = on_payment_ready
        self._on_payment_confirmed = on_payment_confirmed
        self._poll_secs            = poll_secs

        self._bill_generator: Optional[BillGenerator] = None
        self._payu_worker: Optional[PayUWorker]       = None
        self._hubspot = None   # lazy import

        # Track processed order IDs to avoid duplicates
        self._processed: set[str] = set()
        self._running = False

    def _get_bill_generator(self) -> BillGenerator:
        if self._bill_generator is None:
            self._bill_generator = BillGenerator()
        return self._bill_generator

    def _get_payu_worker(self) -> PayUWorker:
        if self._payu_worker is None:
            self._payu_worker = PayUWorker()
        return self._payu_worker

    def _get_hubspot(self):
        if self._hubspot is None:
            from .hubspot_extractor import HubSpotExtractor, hubspot_items_to_bill_items
            self._hubspot = HubSpotExtractor()
            self._items_converter = hubspot_items_to_bill_items
        return self._hubspot

    async def run(self):
        """Main poll loop. Run with asyncio.ensure_future()"""
        self._running = True
        logger.info("HubSpotPaymentBridge started — polling every %.0fs", self._poll_secs)
        while self._running:
            try:
                await self._process_pending_orders()
            except Exception as exc:
                logger.error("HubSpotPaymentBridge poll error: %s", exc)
            await asyncio.sleep(self._poll_secs)

    def stop(self):
        self._running = False

    async def _process_pending_orders(self):
        hs = self._get_hubspot()
        orders = await hs.get_pending_orders()

        for order in orders:
            record_id = order["record_id"]
            if record_id in self._processed:
                continue

            logger.info(
                "Processing HubSpot order record_id=%s room=%s items=%s",
                record_id, order["room_number"],
                [i["name"] for i in order["items"]],
            )

            try:
                # Convert HubSpot items → BillItem objects
                bill_items = self._items_converter(order["items"])

                # Build ServiceRequest
                request = ServiceRequest(
                    service_type=ServiceType.FOOD_ORDER,
                    room_number=order["room_number"],
                    guest_name=order["guest_name"],
                    guest_phone=order["guest_phone"],
                    guest_email=order["guest_email"],
                    items=bill_items,
                    notes=f"HubSpot record {record_id}",
                )

                # Create bill (GST calculated, saved to SQLite)
                bill_gen = self._get_bill_generator()
                bill     = bill_gen.create_bill(request)

                # Generate PayU hash
                payu         = self._get_payu_worker()
                pay_data     = payu.create_payment(bill)
                payment_link = payu.get_payment_page_url(bill)

                # Save link to SQLite
                bill_gen.update_payment_link(bill.order_id, payment_link)
                bill_text = bill_gen.format_bill_text(bill)

                logger.info(
                    "Bill created for HubSpot order %s — total=Rs%.2f link=%s",
                    record_id, bill.total, payment_link,
                )

                # Update HubSpot record with payment link
                await hs.mark_order_payment_link(
                    record_id=record_id,
                    payment_link=payment_link,
                    order_id=bill.order_id,
                )

                # Mark as processed
                self._processed.add(record_id)

                # Fire callback
                if self._on_payment_ready:
                    try:
                        self._on_payment_ready(payment_link, bill_text, order["room_number"])
                    except Exception as exc:
                        logger.warning("on_payment_ready callback error: %s", exc)

                # Poll PayU for confirmation in background
                asyncio.ensure_future(
                    self._poll_confirmation(bill.order_id, record_id, order["room_number"])
                )

            except Exception as exc:
                logger.error(
                    "Failed to process HubSpot order %s: %s", record_id, exc, exc_info=True
                )

    async def _poll_confirmation(self, order_id: str, record_id: str, room_number: str):
        """Poll PayU for payment confirmation and update HubSpot when paid."""
        max_attempts = int(3600 / max(PAYMENT_POLL_SECS, 5))
        try:
            payu = self._get_payu_worker()
        except Exception as exc:
            logger.error("PayUWorker init failed: %s", exc)
            return

        for attempt in range(max_attempts):
            await asyncio.sleep(PAYMENT_POLL_SECS)
            try:
                result = await payu.check_payment_status(order_id)
            except Exception as exc:
                logger.warning("Poll error attempt %d: %s", attempt + 1, exc)
                continue

            txn_details = result.get("transaction_details", {})
            record      = txn_details.get(order_id, {})
            status      = record.get("status", "").lower()
            amount      = record.get("amt", "0")

            if status == "success":
                logger.info(
                    "Payment confirmed! order=%s amount=Rs%s hubspot_record=%s",
                    order_id, amount, record_id,
                )
                # Update SQLite
                try:
                    self._get_bill_generator().update_bill_status(
                        order_id=order_id,
                        status=PaymentStatus.SUCCESS,
                        payu_txn_id=record.get("mihpayid", ""),
                        paid_at=record.get("addedon", ""),
                    )
                except Exception as exc:
                    logger.warning("SQLite update error: %s", exc)

                # Update HubSpot
                hs = self._get_hubspot()
                await hs.mark_order_paid(
                    record_id=record_id,
                    txn_id=order_id,
                    amount=float(amount),
                )

                if self._on_payment_confirmed:
                    try:
                        self._on_payment_confirmed(order_id, amount, room_number)
                    except Exception as exc:
                        logger.warning("on_payment_confirmed callback error: %s", exc)
                return

            elif status in ("failure", "failed", "error"):
                logger.info("Payment failed for order=%s", order_id)
                try:
                    self._get_bill_generator().update_bill_status(
                        order_id=order_id,
                        status=PaymentStatus.FAILED,
                    )
                except Exception:
                    pass
                return

        logger.warning("Payment polling timed out for order=%s", order_id)