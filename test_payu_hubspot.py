"""
test_payu_hubspot.py — Standalone test script
===============================================
Tests:
  1. Fetch pending Food Orders from HubSpot
  2. Create a PayU bill from the first order
  3. Update HubSpot record with payment link

Run from Voice-AI-Agent-main/:
    python test_payu_hubspot.py
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level="INFO",
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")

# ── Add src to path ───────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.payment.hubspot_extractor import HubSpotExtractor, hubspot_items_to_bill_items
from src.payment.bill_generator import BillGenerator
from src.payment.payu_worker import PayUWorker
from src.payment.models import ServiceRequest, ServiceType


async def main():
    print("\n" + "="*60)
    print("  PayU + HubSpot Worker Test")
    print("="*60 + "\n")

    # ── STEP 1: Fetch from HubSpot ────────────────────────────────────────────
    print("STEP 1 — Fetching pending Food Orders from HubSpot...")
    try:
        hs = HubSpotExtractor()
        orders = await hs.get_pending_orders()
    except Exception as e:
        print(f"  ❌ HubSpot fetch failed: {e}")
        return

    if not orders:
        print("  ⚠️  No pending orders found in HubSpot Food Orders object.")
        print("     Make sure there is at least 1 record with items filled in.")
        print("     Trying with a DUMMY order instead...\n")
        orders = [{
            "record_id":   "TEST-001",
            "room_number": "301",
            "guest_name":  "Test Guest",
            "guest_phone": "9876543210",
            "guest_email": "test@hotel.com",
            "items": [
                {"name": "cheese pizza",  "quantity": 2, "unit_price": 349.0},
                {"name": "burger",        "quantity": 1, "unit_price": 199.0},
                {"name": "french fries",  "quantity": 1, "unit_price": 199.0},
                {"name": "cold coffee",   "quantity": 2, "unit_price": 149.0},
                {"name": "cheese musroom",   "quantity": 2, "unit_price": 249.0},
            ]
        }]
    else:
        print(f"  ✅ Found {len(orders)} pending order(s)\n")
        for o in orders:
            print(f"     Record ID : {o['record_id']}")
            print(f"     Room      : {o['room_number']}")
            print(f"     Guest     : {o['guest_name']}")
            print(f"     Items     : {json.dumps(o['items'], indent=6)}")
            print()

    # Use first order for the test
    order = orders[0]

    # ── STEP 2: Create Bill ───────────────────────────────────────────────────
    print("STEP 2 — Creating PayU bill...")
    try:
        bill_items = hubspot_items_to_bill_items(order["items"])
        request = ServiceRequest(
            service_type=ServiceType.FOOD_ORDER,
            room_number=order["room_number"],
            guest_name=order["guest_name"],
            guest_phone=order["guest_phone"],
            guest_email=order["guest_email"],
            items=bill_items,
            notes=f"Test order for record {order['record_id']}",
        )

        gen  = BillGenerator()
        bill = gen.create_bill(request)

        print(f"  ✅ Bill created!")
        print(f"     Bill ID   : {bill.bill_id}")
        print(f"     Order ID  : {bill.order_id}")
        print(f"     Subtotal  : Rs{bill.subtotal:.2f}")
        print(f"     GST       : Rs{bill.tax_amount:.2f} ({bill.tax_rate*100:.0f}%)")
        print(f"     TOTAL     : Rs{bill.total:.2f}\n")
        print(f"     Items breakdown:")
        for item in bill.items:
            print(f"       {item.name:<25} x{item.quantity}  Rs{item.unit_price:.0f}  = Rs{item.total:.2f}")
        print()
    except Exception as e:
        print(f"  ❌ Bill creation failed: {e}")
        import traceback; traceback.print_exc()
        return

    # ── STEP 3: Generate PayU payment link ────────────────────────────────────
    print("STEP 3 — Generating PayU payment link...")
    try:
        payu         = PayUWorker()
        pay_data     = payu.create_payment(bill)
        payment_link = payu.get_payment_page_url(bill)

        gen.update_payment_link(bill.order_id, payment_link)
        bill_text = gen.format_bill_text(bill)

        print(f"  ✅ Payment link generated!")
        print(f"     Link: {payment_link}")
        print(f"\n  Bill text (what agent reads to guest):")
        print("  " + "\n  ".join(bill_text.split("\n")))
        print()
    except Exception as e:
        print(f"  ❌ PayU payment creation failed: {e}")
        print("     Check PAYU_MERCHANT_KEY and PAYU_MERCHANT_SALT in .env")
        import traceback; traceback.print_exc()
        return

    # ── STEP 4: Update HubSpot with payment link ──────────────────────────────
    if order["record_id"] == "TEST-001":
        print("STEP 4 — Skipping HubSpot update (dummy order).")
        print("         In real flow, HubSpot would be updated with:")
        print(f"         payment_status = 'link_sent'")
        print(f"         payment_link   = {payment_link}")
    else:
        print("STEP 4 — Updating HubSpot record with payment link...")
        try:
            success = await hs.mark_order_payment_link(
                record_id=order["record_id"],
                payment_link=payment_link,
                order_id=bill.order_id,
            )
            if success:
                print(f"  ✅ HubSpot record {order['record_id']} updated!")
                print(f"     payment_status = link_sent")
                print(f"     payment_link   = {payment_link}")
            else:
                print(f"  ❌ HubSpot update failed — check token and field names")
        except Exception as e:
            print(f"  ❌ HubSpot update error: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "="*60)
    print("  Test complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())