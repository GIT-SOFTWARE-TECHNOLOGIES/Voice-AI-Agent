"""
webhook_handler.py — Handles PayU payment callbacks
────────────────────────────────────────────────────────────────
PayU sends POST requests to surl (success) and furl (failure)
after the guest completes/cancels payment.
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import PaymentWebhookData, PaymentStatus
from payu_worker import PayUWorker
from bill_generator import BillGenerator

logger = logging.getLogger("payu.webhook")


class WebhookHandler:
    """
    Processes PayU payment webhooks.

    Usage:
        handler = WebhookHandler(
            payu_worker=payu_worker,
            bill_generator=bill_generator,
            on_payment_success=notify_agent,  # callback to tell AI agent
        )
        result = handler.process_webhook(form_data)
    """

    def __init__(
        self,
        payu_worker: PayUWorker,
        bill_generator: BillGenerator,
        on_payment_success: Optional[Callable[[dict], None]] = None,
        on_payment_failure: Optional[Callable[[dict], None]] = None,
    ):
        self.payu_worker = payu_worker
        self.bill_generator = bill_generator
        self._on_success = on_payment_success
        self._on_failure = on_payment_failure

    def process_success(self, data: dict) -> dict:
        """
        Process a successful payment webhook from PayU.

        Returns a result dict with status and bill info.
        """
        logger.info("Processing success webhook: txn=%s", data.get("txnid"))

        # Extract fields
        txn_id = data.get("txnid", "")
        mihpayid = data.get("mihpayid", "")
        status = data.get("status", "")
        amount = data.get("amount", "")
        product_info = data.get("productinfo", "")
        firstname = data.get("firstname", "")
        email = data.get("email", "")
        phone = data.get("phone", "")
        received_hash = data.get("hash", "")
        udf1 = data.get("udf1", "")  # bill_id
        udf2 = data.get("udf2", "")  # room_number
        udf3 = data.get("udf3", "")  # service_type
        udf4 = data.get("udf4", "")
        udf5 = data.get("udf5", "")
        additional_charges = data.get("additionalCharges", "") or data.get("additional_charges", "")

        # ── Step 1: Verify hash ──────────────────────────────────────────────
        is_valid = self.payu_worker.verify_webhook_hash(
            txn_id=txn_id,
            amount=amount,
            product_info=product_info,
            firstname=firstname,
            email=email,
            status=status,
            received_hash=received_hash,
            udf1=udf1,
            udf2=udf2,
            udf3=udf3,
            udf4=udf4,
            udf5=udf5,
            additional_charges=additional_charges,
        )

        if not is_valid:
            logger.error("HASH VERIFICATION FAILED for txn=%s — possible tampering!", txn_id)
            return {
                "success": False,
                "error": "Hash verification failed",
                "txn_id": txn_id,
            }

        # ── Step 2: Update bill in DB ────────────────────────────────────────
        paid_at = datetime.now(timezone.utc).isoformat()
        self.bill_generator.update_bill_status(
            order_id=txn_id,
            status=PaymentStatus.SUCCESS,
            payu_txn_id=mihpayid,
            paid_at=paid_at,
        )

        result = {
            "success": True,
            "txn_id": txn_id,
            "mihpayid": mihpayid,
            "amount": amount,
            "bill_id": udf1,
            "room_number": udf2,
            "service_type": udf3,
            "paid_at": paid_at,
        }

        logger.info(
            "✅ Payment SUCCESS — txn=%s amount=₹%s room=%s service=%s",
            txn_id, amount, udf2, udf3,
        )

        # ── Step 3: Notify AI agent ──────────────────────────────────────────
        if self._on_success:
            try:
                self._on_success(result)
            except Exception as e:
                logger.error("on_payment_success callback error: %s", e)

        return result

    def process_failure(self, data: dict) -> dict:
        """Process a failed/cancelled payment webhook."""
        txn_id = data.get("txnid", "")
        error_msg = data.get("error_Message", "Payment failed")

        logger.warning(
            "❌ Payment FAILED — txn=%s error=%s",
            txn_id, error_msg,
        )

        # Update bill status
        self.bill_generator.update_bill_status(
            order_id=txn_id,
            status=PaymentStatus.FAILED,
        )

        result = {
            "success": False,
            "txn_id": txn_id,
            "error": error_msg,
            "bill_id": data.get("udf1", ""),
            "room_number": data.get("udf2", ""),
        }

        if self._on_failure:
            try:
                self._on_failure(result)
            except Exception as e:
                logger.error("on_payment_failure callback error: %s", e)

        return result