"""
payment_server.py — Serves the PayU payment page at /pay/<order_id>
and handles success/failure webhooks from PayU.

DB columns confirmed:
    bill_id, order_id, service_type, room_number, guest_name,
    guest_phone, guest_email, items_json, subtotal, tax_rate,
    tax_amount, total, currency, status, payment_link,
    payu_txn_id, notes, created_at, paid_at
"""

import hashlib
import json
import logging
import os
import sqlite3
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

# ── Make sure src/ is importable ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger("payment.server")

# ── Config from env (same as src/payment/config.py) ──────────────────────────
DB_PATH          = os.getenv("DB_PATH",           "data/payments.db")
BASE_URL         = os.getenv("BASE_URL",           "https://api.gitsoftwaretech.in")
PAYU_MODE        = os.getenv("PAYU_MODE",          "test")
HOTEL_NAME       = os.getenv("HOTEL_NAME",         "Grand Vista Hotel")
MERCHANT_KEY     = os.getenv("PAYU_MERCHANT_KEY",  "")
MERCHANT_SALT    = os.getenv("PAYU_MERCHANT_SALT", "")

PAYU_URL = (
    os.getenv("PAYU_TEST_URL", "https://test.payu.in/_payment")
    if PAYU_MODE == "test"
    else os.getenv("PAYU_PROD_URL", "https://secure.payu.in/_payment")
)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Payment Server")


# ── DB helper ─────────────────────────────────────────────────────────────────
def get_bill(order_id: str) -> dict | None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM bills WHERE order_id = ?", (order_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.error("DB read error: %s", exc)
        return None


def update_bill_status(order_id: str, status: str,
                       payu_txn_id: str = "", paid_at: str = "") -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE bills SET status=?, payu_txn_id=?, paid_at=? WHERE order_id=?",
            (status, payu_txn_id, paid_at, order_id),
        )
        conn.commit()
        conn.close()
        logger.info("Bill %s updated → status=%s", order_id, status)
    except Exception as exc:
        logger.error("DB update error: %s", exc)


# ── Hash helpers ──────────────────────────────────────────────────────────────
def generate_payu_hash(txn_id: str, amount: str, product_info: str,
                       firstname: str, email: str,
                       udf1: str = "", udf2: str = "", udf3: str = "",
                       udf4: str = "", udf5: str = "") -> str:
    raw = (
        f"{MERCHANT_KEY}|{txn_id}|{amount}|{product_info}|"
        f"{firstname}|{email}|{udf1}|{udf2}|{udf3}|{udf4}|{udf5}"
        f"||||||{MERCHANT_SALT}"
    )
    return hashlib.sha512(raw.encode()).hexdigest()


def verify_webhook_hash(data: dict) -> bool:
    """Verify PayU reverse hash on webhook response."""
    received = data.get("hash", "")
    raw = (
        f"{MERCHANT_SALT}|{data.get('status','')}|||||"
        f"{data.get('udf5','')}|{data.get('udf4','')}|"
        f"{data.get('udf3','')}|{data.get('udf2','')}|"
        f"{data.get('udf1','')}|{data.get('email','')}|"
        f"{data.get('firstname','')}|{data.get('productinfo','')}|"
        f"{data.get('amount','')}|{data.get('txnid','')}|{MERCHANT_KEY}"
    )
    expected = hashlib.sha512(raw.encode()).hexdigest()
    return received == expected


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": HOTEL_NAME, "version": "1.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/pay/{order_id}", response_class=HTMLResponse)
async def payment_page(order_id: str):
    """
    Serve payment page for the given order_id.
    Reads bill from SQLite, generates PayU hash, renders auto-submit form.
    """
    bill = get_bill(order_id)

    if not bill:
        return HTMLResponse(
            _error_page("Payment link not found or expired.",
                        "Please contact the front desk."),
            status_code=404,
        )

    if bill["status"] in ("success", "paid"):
        return HTMLResponse(
            _success_page(bill["order_id"], str(bill["total"]))
        )

    # Build PayU parameters directly from DB row
    txn_id       = bill["order_id"]
    amount       = f"{float(bill['total']):.2f}"
    product_info = f"{bill['service_type']} Room {bill['room_number']}"
    firstname    = bill["guest_name"]
    email        = bill["guest_email"]
    phone        = bill["guest_phone"]
    udf1         = bill["bill_id"]
    udf2         = bill["room_number"]
    udf3         = bill["service_type"]

    pay_hash = generate_payu_hash(
        txn_id, amount, product_info,
        firstname, email, udf1, udf2, udf3,
    )

    # Parse items for display
    try:
        items = json.loads(bill["items_json"])
    except Exception:
        items = []

    items_html = "".join(
        f"""<tr>
              <td>{i.get('name','')}</td>
              <td style="text-align:center">{i.get('quantity',1)}</td>
              <td style="text-align:right">₹{float(i.get('unit_price',0)):.2f}</td>
              <td style="text-align:right">₹{float(i.get('total', float(i.get('unit_price',0))*int(i.get('quantity',1)))):.2f}</td>
            </tr>"""
        for i in items
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pay — {HOTEL_NAME}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',Arial,sans-serif;background:linear-gradient(135deg,#1A263D 0%,#2D3B55 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}}
    .card{{background:#fff;border-radius:20px;padding:32px;max-width:460px;width:100%;box-shadow:0 24px 64px rgba(0,0,0,0.35)}}
    .hotel{{display:flex;align-items:center;gap:12px;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #f0ede6}}
    .logo{{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#D4A017,#E8B923);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;color:#fff;flex-shrink:0}}
    .hotel-name{{font-size:18px;font-weight:700;color:#1A263D}}
    .hotel-sub{{font-size:12px;color:#9C8F79;letter-spacing:.05em;text-transform:uppercase}}
    .row{{display:flex;justify-content:space-between;padding:8px 0;font-size:14px;border-bottom:1px solid #f5f3ef}}
    .row .label{{color:#9C8F79}}
    .row .val{{font-weight:600;color:#1A120B}}
    table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:13px}}
    thead tr{{background:#f8f4ee}}
    th{{padding:8px;text-align:left;font-weight:600;color:#6B5A44;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
    td{{padding:8px;border-bottom:1px solid #f0ede6;color:#1A120B}}
    .totals{{margin-top:4px}}
    .totals .row{{font-size:13px}}
    .totals .total-row{{font-size:16px;font-weight:700;border-top:2px solid #E5E0D9;padding-top:12px;margin-top:4px}}
    .total-row .label{{color:#1A120B}}
    .total-row .val{{color:#D4A017;font-size:20px}}
    .btn{{display:block;width:100%;background:linear-gradient(135deg,#D4A017,#E8B923);color:#fff;border:none;padding:16px;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:24px;letter-spacing:.02em;transition:opacity .2s}}
    .btn:hover{{opacity:.9}}
    .secure{{text-align:center;font-size:11px;color:#BFAF92;margin-top:12px}}
    .badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:#F8E8B8;color:#D4A017;margin-left:8px}}
  </style>
</head>
<body>
<div class="card">
  <div class="hotel">
    <div class="logo">G</div>
    <div>
      <div class="hotel-name">{HOTEL_NAME}</div>
      <div class="hotel-sub">Secure Payment</div>
    </div>
  </div>

  <div class="row"><span class="label">Order ID</span><span class="val">{txn_id}</span></div>
  <div class="row"><span class="label">Room</span><span class="val">{bill['room_number']}</span></div>
  <div class="row"><span class="label">Guest</span><span class="val">{firstname}</span></div>
  <div class="row"><span class="label">Service</span><span class="val">{bill['service_type'].replace('_',' ').title()}<span class="badge">India GST</span></span></div>

  <table>
    <thead><tr><th>Item</th><th style="text-align:center">Qty</th><th style="text-align:right">Rate</th><th style="text-align:right">Amount</th></tr></thead>
    <tbody>{items_html}</tbody>
  </table>

  <div class="totals">
    <div class="row"><span class="label">Subtotal</span><span class="val">₹{float(bill['subtotal']):.2f}</span></div>
    <div class="row"><span class="label">GST ({int(float(bill['tax_rate'])*100)}%)</span><span class="val">₹{float(bill['tax_amount']):.2f}</span></div>
    <div class="row total-row"><span class="label">Total Payable</span><span class="val">₹{float(bill['total']):.2f}</span></div>
  </div>

  <form method="POST" action="{PAYU_URL}" id="payuForm">
    <input type="hidden" name="key"         value="{MERCHANT_KEY}">
    <input type="hidden" name="txnid"       value="{txn_id}">
    <input type="hidden" name="amount"      value="{amount}">
    <input type="hidden" name="productinfo" value="{product_info}">
    <input type="hidden" name="firstname"   value="{firstname}">
    <input type="hidden" name="email"       value="{email}">
    <input type="hidden" name="phone"       value="{phone}">
    <input type="hidden" name="surl"        value="{BASE_URL}/payment/success">
    <input type="hidden" name="furl"        value="{BASE_URL}/payment/failure">
    <input type="hidden" name="hash"        value="{pay_hash}">
    <input type="hidden" name="udf1"        value="{udf1}">
    <input type="hidden" name="udf2"        value="{udf2}">
    <input type="hidden" name="udf3"        value="{udf3}">
    <button type="submit" class="btn">Pay Now &nbsp;₹{float(bill['total']):.2f}</button>
  </form>
  <p class="secure">🔒 256-bit SSL · Secured by PayU Payment Gateway</p>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.post("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    """PayU POSTs here after successful payment."""
    form = await request.form()
    data = dict(form)
    logger.info("Payment SUCCESS webhook: txnid=%s mihpayid=%s amount=%s",
                data.get("txnid"), data.get("mihpayid"), data.get("amount"))

    if verify_webhook_hash(data):
        update_bill_status(
            order_id=data.get("txnid", ""),
            status="success",
            payu_txn_id=data.get("mihpayid", ""),
            paid_at=data.get("addedon", ""),
        )
    else:
        logger.warning("Hash verification FAILED for txnid=%s", data.get("txnid"))

    return HTMLResponse(_success_page(
        data.get("txnid", ""), data.get("amount", "")
    ))


@app.post("/payment/failure", response_class=HTMLResponse)
async def payment_failure(request: Request):
    """PayU POSTs here after failed/cancelled payment."""
    form = await request.form()
    data = dict(form)
    logger.info("Payment FAILED webhook: txnid=%s status=%s",
                data.get("txnid"), data.get("status"))

    update_bill_status(
        order_id=data.get("txnid", ""),
        status="failed",
    )

    return HTMLResponse(_error_page(
        "Payment Failed or Cancelled",
        "Please try again or contact the front desk.",
        show_retry=True,
        order_id=data.get("txnid", ""),
    ))


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _success_page(order_id: str, amount: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Payment Successful</title>
  <style>
    body{{font-family:'Segoe UI',Arial,sans-serif;background:linear-gradient(135deg,#1A263D,#2D3B55);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}}
    .card{{background:#fff;border-radius:20px;padding:40px;max-width:400px;width:100%;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,0.35)}}
    .icon{{font-size:64px;margin-bottom:16px}}
    h2{{color:#2A7F5B;font-size:24px;margin-bottom:8px}}
    p{{color:#6B5A44;font-size:15px;line-height:1.6}}
    .order{{background:#f8f4ee;border-radius:10px;padding:12px 16px;margin:20px 0;font-size:13px;color:#9C8F79}}
    .order strong{{color:#1A120B;display:block;font-size:15px}}
  </style>
</head>
<body>
<div class="card">
  <div class="icon">✅</div>
  <h2>Payment Successful!</h2>
  <p>Thank you! Your order has been confirmed and is being processed.</p>
  <div class="order">
    Order ID<br><strong>{order_id}</strong>
    {"<br><br>Amount Paid<br><strong>₹" + amount + "</strong>" if amount else ""}
  </div>
  <p style="font-size:13px;color:#BFAF92">You may close this window.</p>
</div>
</body>
</html>"""


def _error_page(title: str, message: str,
                show_retry: bool = False, order_id: str = "") -> str:
    retry_btn = (
        f'<a href="/pay/{order_id}" style="display:inline-block;margin-top:20px;'
        f'background:linear-gradient(135deg,#D4A017,#E8B923);color:#fff;'
        f'padding:12px 28px;border-radius:12px;text-decoration:none;font-weight:700">Try Again</a>'
        if show_retry and order_id else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Payment Failed</title>
  <style>
    body{{font-family:'Segoe UI',Arial,sans-serif;background:linear-gradient(135deg,#1A263D,#2D3B55);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}}
    .card{{background:#fff;border-radius:20px;padding:40px;max-width:400px;width:100%;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,0.35)}}
    .icon{{font-size:64px;margin-bottom:16px}}
    h2{{color:#B91C1C;font-size:22px;margin-bottom:8px}}
    p{{color:#6B5A44;font-size:15px;line-height:1.6}}
  </style>
</head>
<body>
<div class="card">
  <div class="icon">❌</div>
  <h2>{title}</h2>
  <p>{message}</p>
  {retry_btn}
</div>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "9000"))
    logger.info("Starting payment server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")