"""
config.py — PayU configuration and constants
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── PayU Credentials ──────────────────────────────────────────────────────
PAYU_MERCHANT_KEY = os.getenv("PAYU_MERCHANT_KEY", "")
PAYU_MERCHANT_SALT = os.getenv("PAYU_MERCHANT_SALT", "")
PAYU_MODE = os.getenv("PAYU_MODE", "test")  # "test" or "production"

# ── PayU URLs ─────────────────────────────────────────────────────────────
PAYU_BASE_URL = (
    os.getenv("PAYU_TEST_URL", "https://test.payu.in/_payment")
    if PAYU_MODE == "test"
    else os.getenv("PAYU_PROD_URL", "https://secure.payu.in/_payment")
)

PAYU_VERIFY_URL = (
    os.getenv("PAYU_TEST_VERIFY_URL", "https://test.payu.in/merchant/postservice?form=2")
    if PAYU_MODE == "test"
    else os.getenv("PAYU_PROD_VERIFY_URL", "https://info.payu.in/merchant/postservice?form=2")
)

# ── Server ────────────────────────────────────────────────────────────────
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "9000"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:9000")

# ── Hotel ─────────────────────────────────────────────────────────────────
HOTEL_NAME = os.getenv("HOTEL_NAME", "Grand Hotel PersonaPlex")
HOTEL_GST_NUMBER = os.getenv("HOTEL_GST_NUMBER", "29ABCDE1234F1Z5")

# ── Tax Rates (India GST) ────────────────────────────────────────────────
TAX_RATES = {
    "food_order": 0.05,        # 5% GST on food
    "room_cleaning": 0.18,     # 18% GST on services
    "cab_booking": 0.05,       # 5% GST on transport
    "restaurant_booking": 0.05, # 5% GST on restaurant
    "laundry": 0.18,           # 18% GST on services
    "spa": 0.18,               # 18% GST on services
    "default": 0.18,           # Default 18%
}

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "data/payments.db")