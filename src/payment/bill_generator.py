"""
bill_generator.py — Creates itemized bills with tax calculation
"""

import logging
import sqlite3
from pathlib import Path

from .config import TAX_RATES, DB_PATH, HOTEL_NAME, HOTEL_GST_NUMBER
from .models import Bill, BillItem, ServiceRequest, PaymentStatus

logger = logging.getLogger("payu.bill_generator")


class BillGenerator:
    """
    Creates and stores hotel service bills.

    Usage:
        generator = BillGenerator()
        bill = generator.create_bill(service_request)
        print(bill.total)  # ₹530.00 (including GST)
    """

    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Create bills table if not exists."""
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bills (
                bill_id         TEXT PRIMARY KEY,
                order_id        TEXT UNIQUE NOT NULL,
                service_type    TEXT NOT NULL,
                room_number     TEXT NOT NULL,
                guest_name      TEXT NOT NULL,
                guest_phone     TEXT NOT NULL,
                guest_email     TEXT NOT NULL,
                items_json      TEXT NOT NULL,
                subtotal        REAL NOT NULL,
                tax_rate        REAL NOT NULL,
                tax_amount      REAL NOT NULL,
                total           REAL NOT NULL,
                currency        TEXT DEFAULT 'INR',
                status          TEXT DEFAULT 'pending',
                payment_link    TEXT DEFAULT '',
                payu_txn_id     TEXT DEFAULT '',
                notes           TEXT DEFAULT '',
                created_at      TEXT NOT NULL,
                paid_at         TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_bills_order_id
                ON bills(order_id);

            CREATE INDEX IF NOT EXISTS idx_bills_room
                ON bills(room_number);

            CREATE INDEX IF NOT EXISTS idx_bills_status
                ON bills(status);
        """)
        conn.commit()
        conn.close()
        logger.info("BillGenerator DB ready: %s", DB_PATH)

    def create_bill(self, request: ServiceRequest) -> Bill:
        """
        Create an itemized bill from a service request.

        Returns a Bill object with calculated subtotal, tax, and total.
        """
        # Calculate item totals
        items = []
        for item in request.items:
            bill_item = BillItem(
                name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            items.append(bill_item)

        # Calculate subtotal
        subtotal = round(sum(item.total for item in items), 2)

        # Get tax rate for this service type
        tax_rate = TAX_RATES.get(request.service_type.value, TAX_RATES["default"])
        tax_amount = round(subtotal * tax_rate, 2)
        total = round(subtotal + tax_amount, 2)

        # Create bill
        bill = Bill(
            service_type=request.service_type,
            room_number=request.room_number,
            guest_name=request.guest_name,
            guest_phone=request.guest_phone,
            guest_email=request.guest_email,
            items=items,
            subtotal=subtotal,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            total=total,
            notes=request.notes,
        )

        # Save to DB
        self._save_bill(bill)

        logger.info(
            "Bill created: %s | %s | Room %s | ₹%.2f",
            bill.bill_id, bill.service_type.value, bill.room_number, bill.total,
        )

        return bill

    def _save_bill(self, bill: Bill):
        """Persist bill to SQLite."""
        import json
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO bills
            (bill_id, order_id, service_type, room_number, guest_name,
             guest_phone, guest_email, items_json, subtotal, tax_rate,
             tax_amount, total, currency, status, payment_link,
             payu_txn_id, notes, created_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bill.bill_id, bill.order_id, bill.service_type.value,
            bill.room_number, bill.guest_name, bill.guest_phone,
            bill.guest_email,
            json.dumps([item.model_dump() for item in bill.items]),
            bill.subtotal, bill.tax_rate, bill.tax_amount, bill.total,
            bill.currency, bill.status.value, bill.payment_link,
            bill.payu_txn_id, bill.notes, bill.created_at, bill.paid_at,
        ))
        conn.commit()
        conn.close()

    def update_bill_status(self, order_id: str, status: PaymentStatus,
                           payu_txn_id: str = "", paid_at: str = ""):
        """Update payment status after PayU webhook."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            UPDATE bills SET status = ?, payu_txn_id = ?, paid_at = ?
            WHERE order_id = ?
        """, (status.value, payu_txn_id, paid_at, order_id))
        conn.commit()
        conn.close()
        logger.info("Bill %s updated → %s", order_id, status.value)

    def update_payment_link(self, order_id: str, payment_link: str):
        """Store the payment link in the bill record."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            UPDATE bills SET payment_link = ? WHERE order_id = ?
        """, (payment_link, order_id))
        conn.commit()
        conn.close()

    def get_bill_by_order_id(self, order_id: str) -> dict | None:
        """Fetch a bill by its order_id."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM bills WHERE order_id = ?", (order_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_bills_by_room(self, room_number: str) -> list[dict]:
        """Fetch all bills for a room."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bills WHERE room_number = ? ORDER BY created_at DESC",
            (room_number,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_unpaid_bills(self, room_number: str = None) -> list[dict]:
        """Fetch all unpaid bills, optionally filtered by room."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if room_number:
            rows = conn.execute(
                "SELECT * FROM bills WHERE room_number = ? AND status = 'pending' "
                "ORDER BY created_at DESC",
                (room_number,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bills WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def format_bill_text(self, bill: Bill) -> str:
        """
        Format a bill as readable text for the AI agent to read to the guest.
        """
        lines = [
            f"── {HOTEL_NAME} ──",
            f"Bill #{bill.bill_id}",
            f"Room: {bill.room_number}  |  Guest: {bill.guest_name}",
            f"Service: {bill.service_type.value.replace('_', ' ').title()}",
            "",
            "Items:",
        ]
        for item in bill.items:
            lines.append(
                f"  {item.name:<30} {item.quantity}x ₹{item.unit_price:.0f}  = ₹{item.total:.2f}"
            )
        lines.extend([
            "",
            f"  {'Subtotal':<30}            ₹{bill.subtotal:.2f}",
            f"  {'GST @':<6}{bill.tax_rate*100:.0f}%{'':<24}₹{bill.tax_amount:.2f}",
            f"  {'TOTAL':<30}            ₹{bill.total:.2f}",
            "",
            f"GST: {HOTEL_GST_NUMBER}",
        ])
        return "\n".join(lines)