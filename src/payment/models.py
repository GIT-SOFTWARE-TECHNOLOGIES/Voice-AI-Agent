"""
models.py — Pydantic models for bills, payments, services
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ServiceType(str, Enum):
    FOOD_ORDER = "food_order"
    ROOM_CLEANING = "room_cleaning"
    CAB_BOOKING = "cab_booking"
    RESTAURANT_BOOKING = "restaurant_booking"
    LAUNDRY = "laundry"
    SPA = "spa"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    INITIATED = "initiated"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class BillItem(BaseModel):
    """Single line item on a bill"""
    name: str
    quantity: int = 1
    unit_price: float
    total: float = 0.0

    def model_post_init(self, __context):
        self.total = round(self.quantity * self.unit_price, 2)


class ServiceRequest(BaseModel):
    """Request from AI agent to book a service"""
    service_type: ServiceType
    room_number: str
    guest_name: str
    guest_phone: str
    guest_email: str = "guest@hotel.com"
    items: list[BillItem]
    notes: str = ""


class Bill(BaseModel):
    """Generated bill for a service"""
    bill_id: str = Field(default_factory=lambda: f"BILL-{uuid.uuid4().hex[:10].upper()}")
    order_id: str = Field(default_factory=lambda: f"ORD-{uuid.uuid4().hex[:12].upper()}")
    service_type: ServiceType
    room_number: str
    guest_name: str
    guest_phone: str
    guest_email: str
    items: list[BillItem]
    subtotal: float = 0.0
    tax_rate: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = "INR"
    status: PaymentStatus = PaymentStatus.PENDING
    payment_link: str = ""
    payu_txn_id: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    paid_at: Optional[str] = None


class PayUPaymentData(BaseModel):
    """Data needed to create a PayU payment"""
    merchant_key: str
    txn_id: str
    amount: str
    product_info: str
    firstname: str
    email: str
    phone: str
    surl: str  # success URL
    furl: str  # failure URL
    hash: str
    udf1: str = ""  # bill_id
    udf2: str = ""  # room_number
    udf3: str = ""  # service_type
    udf4: str = ""
    udf5: str = ""


class PaymentWebhookData(BaseModel):
    """Data received from PayU webhook/redirect"""
    mihpayid: str = ""
    status: str = ""
    txnid: str = ""
    amount: str = ""
    productinfo: str = ""
    firstname: str = ""
    email: str = ""
    phone: str = ""
    hash: str = ""
    key: str = ""
    udf1: str = ""
    udf2: str = ""
    udf3: str = ""
    udf4: str = ""
    udf5: str = ""
    additional_charges: str = ""
    error_Message: str = ""