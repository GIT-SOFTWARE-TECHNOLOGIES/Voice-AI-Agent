"""
payu_worker.py — PayU payment hash generation and payment operations
─────────────────────────────────────────────────────────────────────
PayU Hash Formula:
    hash = SHA512(key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||SALT)

Reverse Hash (for verification):
    hash = SHA512(salt|status||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import (
    PAYU_MERCHANT_KEY,
    PAYU_MERCHANT_SALT,
    PAYU_BASE_URL,
    PAYU_VERIFY_URL,
    BASE_URL,
)
from .models import Bill, PayUPaymentData, PaymentStatus

logger = logging.getLogger("payu.worker")


class PayUWorker:

    def __init__(self):
        if not PAYU_MERCHANT_KEY or not PAYU_MERCHANT_SALT:
            raise ValueError(
                "PAYU_MERCHANT_KEY and PAYU_MERCHANT_SALT must be set in .env\n"
                "Get test credentials from: https://devguide.payu.in/"
            )
        self.merchant_key = PAYU_MERCHANT_KEY
        self.merchant_salt = PAYU_MERCHANT_SALT
        logger.info(
            "PayUWorker initialized — mode=%s key=%s...",
            "TEST" if "test" in PAYU_BASE_URL else "PROD",
            self.merchant_key[:6],
        )

    # ── Hash Generation ───────────────────────────────────────────────────────

    def _generate_hash(
        self,
        txn_id: str,
        amount: str,
        product_info: str,
        firstname: str,
        email: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
    ) -> str:
        """
        SHA512(key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||SALT)
        The 6 pipes after udf5 represent 6 unused empty fields before SALT.
        """
        hash_string = (
            f"{self.merchant_key}"
            f"|{txn_id}"
            f"|{amount}"
            f"|{product_info}"
            f"|{firstname}"
            f"|{email}"
            f"|{udf1}"
            f"|{udf2}"
            f"|{udf3}"
            f"|{udf4}"
            f"|{udf5}"
            f"||||||"
            f"{self.merchant_salt}"
        )
        # Log the FULL hash string so you can verify it exactly
        logger.info("HASH INPUT STRING: %s", hash_string)
        hash_value = hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()
        logger.info("HASH OUTPUT: %s", hash_value)
        return hash_value

    def _generate_reverse_hash(
        self,
        txn_id: str,
        amount: str,
        product_info: str,
        firstname: str,
        email: str,
        status: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
        additional_charges: str = "",
    ) -> str:
        """
        SHA512(salt|status||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)
        With additional_charges:
        SHA512(additional_charges|salt|status||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)
        """
        if additional_charges:
            hash_string = (
                f"{additional_charges}"
                f"|{self.merchant_salt}"
                f"|{status}"
                f"||||||"
                f"{udf5}"
                f"|{udf4}"
                f"|{udf3}"
                f"|{udf2}"
                f"|{udf1}"
                f"|{email}"
                f"|{firstname}"
                f"|{product_info}"
                f"|{amount}"
                f"|{txn_id}"
                f"|{self.merchant_key}"
            )
        else:
            hash_string = (
                f"{self.merchant_salt}"
                f"|{status}"
                f"||||||"
                f"{udf5}"
                f"|{udf4}"
                f"|{udf3}"
                f"|{udf2}"
                f"|{udf1}"
                f"|{email}"
                f"|{firstname}"
                f"|{product_info}"
                f"|{amount}"
                f"|{txn_id}"
                f"|{self.merchant_key}"
            )
        logger.info("REVERSE HASH INPUT: %s", hash_string)
        return hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()

    # ── Payment Creation ──────────────────────────────────────────────────────

    def create_payment(self, bill: Bill) -> PayUPaymentData:
        """
        Create PayU payment data from a bill.
        Returns PayUPaymentData ready to be POSTed to PayU.
        """
        txn_id = bill.order_id
        amount = f"{bill.total:.2f}"

        # IMPORTANT: No pipe character allowed in product_info.
        # Pipe is PayU's field delimiter — using it inside a value corrupts the hash.
        product_info = f"{bill.service_type.value} Room {bill.room_number}"

        logger.info("create_payment called — txn=%s product_info=%r", txn_id, product_info)

        payment_hash = self._generate_hash(
            txn_id=txn_id,
            amount=amount,
            product_info=product_info,
            firstname=bill.guest_name,
            email=bill.guest_email,
            udf1=bill.bill_id,
            udf2=bill.room_number,
            udf3=bill.service_type.value,
            udf4="",
            udf5="",
        )

        payment_data = PayUPaymentData(
            merchant_key=self.merchant_key,
            txn_id=txn_id,
            amount=amount,
            product_info=product_info,
            firstname=bill.guest_name,
            email=bill.guest_email,
            phone=bill.guest_phone,
            surl=f"{BASE_URL}/payment/success",
            furl=f"{BASE_URL}/payment/failure",
            hash=payment_hash,
            udf1=bill.bill_id,
            udf2=bill.room_number,
            udf3=bill.service_type.value,
        )

        logger.info(
            "Payment created: txn=%s amount=%s hash=%s...",
            txn_id, amount, payment_hash[:16],
        )

        return payment_data

    def get_payment_url(self) -> str:
        """Return the PayU gateway URL (test or prod)."""
        return PAYU_BASE_URL

    def get_payment_page_url(self, bill: Bill) -> str:
        """Return the URL for our local payment page."""
        return f"{BASE_URL}/pay/{bill.order_id}"

    # ── Webhook Verification ──────────────────────────────────────────────────

    def verify_webhook_hash(
        self,
        txn_id: str,
        amount: str,
        product_info: str,
        firstname: str,
        email: str,
        status: str,
        received_hash: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
        additional_charges: str = "",
    ) -> bool:
        """
        Verify the hash received from PayU webhook/redirect.
        Returns True if the hash is valid (payment is genuine).
        """
        expected_hash = self._generate_reverse_hash(
            txn_id=txn_id,
            amount=amount,
            product_info=product_info,
            firstname=firstname,
            email=email,
            status=status,
            udf1=udf1,
            udf2=udf2,
            udf3=udf3,
            udf4=udf4,
            udf5=udf5,
            additional_charges=additional_charges,
        )

        is_valid = expected_hash == received_hash
        if not is_valid:
            logger.warning(
                "Hash mismatch! txn=%s expected=%s... received=%s...",
                txn_id, expected_hash[:16], received_hash[:16],
            )
        else:
            logger.info("Hash verified for txn=%s", txn_id)

        return is_valid

    # ── Payment Status Check (API) ────────────────────────────────────────────

    async def check_payment_status(self, txn_id: str) -> dict:
        """Query PayU API to check the status of a transaction."""
        command = "verify_payment"
        hash_string = f"{self.merchant_key}|{command}|{txn_id}|{self.merchant_salt}"
        command_hash = hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()

        payload = {
            "key": self.merchant_key,
            "command": command,
            "var1": txn_id,
            "hash": command_hash,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(PAYU_VERIFY_URL, data=payload)
            result = response.json()

        logger.info("Payment status for %s: %s", txn_id, result.get("status"))
        return result

    # ── Refund ────────────────────────────────────────────────────────────────

    async def initiate_refund(
        self,
        payu_txn_id: str,
        txn_id: str,
        amount: float,
    ) -> dict:
        """
        Initiate a refund via PayU API.

        Parameters:
            payu_txn_id : PayU's transaction ID (mihpayid from webhook)
            txn_id      : Your order_id
            amount      : Amount to refund
        """
        command = "cancel_refund_transaction"
        hash_string = (
            f"{self.merchant_key}|{command}|{payu_txn_id}|{self.merchant_salt}"
        )
        command_hash = hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()

        payload = {
            "key": self.merchant_key,
            "command": command,
            "var1": payu_txn_id,
            "var2": txn_id,
            "var3": f"{amount:.2f}",
            "hash": command_hash,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(PAYU_VERIFY_URL, data=payload)
            result = response.json()

        logger.info("Refund result for %s: %s", txn_id, result)
        return result