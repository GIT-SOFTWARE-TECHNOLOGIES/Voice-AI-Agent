"""
hubspot_extractor.py — Fetches Food Orders from HubSpot CRM and maps
them to PayU BillItem objects so the payment bridge can create bills.

HubSpot Object: Food Orders (type: 2-228700855)
Items field format:
    [
        {"name": "cheese pizza", "quantity": 2, "price": 350, "subtotal": 700},
        {"name": "burger",       "quantity": 1, "price": 199, "subtotal": 199}
    ]

Usage:
    extractor = HubSpotExtractor()

    # Fetch all pending food orders
    orders = await extractor.get_pending_orders()

    # Mark order as paid after PayU confirms
    await extractor.mark_order_paid(record_id="12345", txn_id="ORD-XXXX", amount=1256.0)
"""

import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("payment.hubspot")

HUBSPOT_ACCESS_TOKEN    = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_FOOD_OBJECT_TYPE = os.getenv("HUBSPOT_FOOD_OBJECT_TYPE", "2-228700855")
HUBSPOT_API_BASE        = "https://api.hubapi.com"

# ── Your actual menu ──────────────────────────────────────────────────────────
MENU = {
    "cheese pizza":  349.0,
    "burger":        199.0,
    "french fries":  199.0,
    "sandwich":      149.0,
    "cold coffee":   149.0,
    # existing items from service_catalog
    "butter chicken": 450.0,
    "paneer tikka":   350.0,
    "dal makhani":    280.0,
    "biryani":        380.0,
    "naan":            60.0,
    "roti":            40.0,
    "rice":           120.0,
    "raita":           80.0,
    "soup":           180.0,
    "salad":          220.0,
    "coke":            80.0,
    "pepsi":           80.0,
    "water bottle":    40.0,
    "fresh juice":    150.0,
    "tea":             60.0,
    "coffee":         100.0,
    "beer":           350.0,
    "gulab jamun":    120.0,
    "ice cream":      180.0,
    "brownie":        200.0,
}


def _parse_items(items_raw) -> list[dict]:
    """
    Parse the items field from HubSpot. It can be:
    - A JSON string:  '[{"name": "burger", "quantity": 1, ...}]'
    - Already a list: [{"name": "burger", ...}]
    - None / empty
    Returns a list of dicts with keys: name, quantity, unit_price, subtotal
    """
    if not items_raw:
        return []

    if isinstance(items_raw, str):
        try:
            items_raw = json.loads(items_raw)
        except json.JSONDecodeError:
            logger.warning("Could not parse items JSON: %s", items_raw[:100])
            return []

    if not isinstance(items_raw, list):
        return []

    result = []
    for item in items_raw:
        name     = str(item.get("name", "")).lower().strip()
        quantity = int(item.get("quantity", 1))
        # Use price from HubSpot if present, otherwise look up from MENU
        price    = float(item.get("price", 0)) or MENU.get(name, 0.0)
        subtotal = float(item.get("subtotal", 0)) or round(price * quantity, 2)

        if name:
            result.append({
                "name":       name,
                "quantity":   quantity,
                "unit_price": price,
                "subtotal":   subtotal,
            })

    return result


class HubSpotExtractor:
    """
    Fetches Food Order records from HubSpot and maps them
    to the format expected by PaymentBridge / BillGenerator.
    """

    def __init__(self):
        if not HUBSPOT_ACCESS_TOKEN:
            raise ValueError(
                "HUBSPOT_ACCESS_TOKEN is not set in .env\n"
                "Get it from HubSpot → Settings → Integrations → Private Apps"
            )
        self._headers = {
            "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
            "Content-Type":  "application/json",
        }
        logger.info(
            "HubSpotExtractor ready — object_type=%s", HUBSPOT_FOOD_OBJECT_TYPE
        )

    # ── Fetch orders ──────────────────────────────────────────────────────────

    async def get_pending_orders(self) -> list[dict]:
        """
        Fetch all Food Order records from HubSpot that are pending payment.
        Returns list of order dicts ready to pass to PaymentBridge.
        """
        url = (
            f"{HUBSPOT_API_BASE}/crm/v3/objects/"
            f"{HUBSPOT_FOOD_OBJECT_TYPE}"
            f"?limit=50&properties=items,room_number,guest_name,"
            f"guest_phone,guest_email,status,hs_object_id"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("HubSpot fetch error: %s", exc)
            return []

        orders = []
        for record in data.get("results", []):
            props = record.get("properties", {})
            payment_status = str(props.get("status", "")).lower()

            # Skip already paid orders
            if payment_status in ("paid", "success", "completed"):
                continue

            items_raw = props.get("items", "")
            items     = _parse_items(items_raw)
            if not items:
                continue

            orders.append({
                "record_id":   record.get("id", ""),
                "room_number": str(props.get("room_number", "000")),
                "guest_name":  str(props.get("guest_name",  "Guest")),
                "guest_phone": str(props.get("guest_phone", "9999999999")),
                "guest_email": str(props.get("guest_email", "guest@hotel.com")),
                "items":       items,
                "raw":         props,
            })

        logger.info("Found %d pending food orders in HubSpot", len(orders))
        return orders

    async def get_order_by_id(self, record_id: str) -> Optional[dict]:
        """Fetch a single Food Order record by its HubSpot record ID."""
        url = (
            f"{HUBSPOT_API_BASE}/crm/v3/objects/"
            f"{HUBSPOT_FOOD_OBJECT_TYPE}/{record_id}"
            f"?properties=items,room_number,guest_name,"
            f"guest_phone,guest_email,status"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                record = resp.json()
        except Exception as exc:
            logger.error("HubSpot get_order_by_id error: %s", exc)
            return None

        props = record.get("properties", {})
        items = _parse_items(props.get("items", ""))
        if not items:
            return None

        return {
            "record_id":   record_id,
            "room_number": str(props.get("room_number", "000")),
            "guest_name":  str(props.get("guest_name",  "Guest")),
            "guest_phone": str(props.get("guest_phone", "9999999999")),
            "guest_email": str(props.get("guest_email", "guest@hotel.com")),
            "items":       items,
        }

    # ── Update order status ───────────────────────────────────────────────────

    async def mark_order_paid(
        self,
        record_id: str,
        txn_id: str,
        amount: float,
    ) -> bool:
        """
        Update the Food Order record in HubSpot after payment is confirmed.
        Sets payment_status = 'paid', payu_txn_id, and amount_paid.
        """
        url = (
            f"{HUBSPOT_API_BASE}/crm/v3/objects/"
            f"{HUBSPOT_FOOD_OBJECT_TYPE}/{record_id}"
        )
        payload = {
            "properties": {
                "status": "paid",
                "special_notes":  f"PayU txn: {txn_id} | Amount: Rs{amount}",
                
            }
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.patch(url, json=payload, headers=self._headers)
                resp.raise_for_status()
            logger.info(
                "HubSpot order %s marked as paid — txn=%s amount=%.2f",
                record_id, txn_id, amount,
            )
            return True
        except Exception as exc:
            logger.error("HubSpot mark_order_paid error: %s", exc)
            return False

    async def mark_order_payment_link(
        self,
        record_id: str,
        payment_link: str,
        order_id: str,
    ) -> bool:
        """
        Store the PayU payment link on the HubSpot record
        so hotel staff can see/share it.
        """
        url = (
            f"{HUBSPOT_API_BASE}/crm/v3/objects/"
            f"{HUBSPOT_FOOD_OBJECT_TYPE}/{record_id}"
        )
        payload = {
            "properties": {
                "status": "link_sent",
                "special_notes":  f"Payment link: {payment_link} | Order: {order_id}",
                
            }
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.patch(url, json=payload, headers=self._headers)
                resp.raise_for_status()
            logger.info(
                "HubSpot order %s payment link updated — link=%s",
                record_id, payment_link,
            )
            return True
        except Exception as exc:
            logger.error("HubSpot mark_order_payment_link error: %s", exc)
            return False


# ── Standalone helper to convert HubSpot order → BillItem list ───────────────

def hubspot_items_to_bill_items(items: list[dict]):
    """
    Convert HubSpot items list to BillItem objects for BillGenerator.
    Import BillItem lazily to avoid circular imports.
    """
    from .models import BillItem
    result = []
    for item in items:
        name     = item["name"]
        quantity = item["quantity"]
        # Prefer price from HubSpot, fall back to MENU lookup
        price    = item.get("unit_price") or MENU.get(name, 0.0)
        result.append(BillItem(
            name=name,
            quantity=quantity,
            unit_price=price,
        ))
    return result