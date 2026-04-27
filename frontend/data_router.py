"""
data_router.py — REST endpoints for transcripts, CRM records, and bills.

Mounted by main_server.py under /api.

Routes added (all GET):
    /api/transcripts            → list all sessions
    /api/transcripts/{id}       → turns for one session
    /api/crm                    → list all CRM JSON files
    /api/crm/{session_id}       → one CRM JSON file
    /api/bills                  → list all bills from SQLite
    /api/bills/{order_id}       → one bill row
"""

import json
import logging
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("data_router")

# ── Paths (same defaults used by the workers) ─────────────────────────────────
TRANSCRIPTS_DB  = Path(os.getenv("TRANSCRIPTS_DB",  "transcripts/sessions.db"))
CRM_OUTPUTS_DIR = Path(os.getenv("CRM_OUTPUTS_DIR", "crm_outputs"))
PAYMENTS_DB     = Path(os.getenv("DB_PATH",         "data/payments.db"))

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _transcript_conn():
    if not TRANSCRIPTS_DB.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Transcripts DB not found at {TRANSCRIPTS_DB}. "
                   "Has the agent run at least one session?",
        )
    conn = sqlite3.connect(TRANSCRIPTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _payments_conn():
    if not PAYMENTS_DB.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Payments DB not found at {PAYMENTS_DB}. "
                   "Has a bill been generated yet?",
        )
    conn = sqlite3.connect(PAYMENTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── Transcripts ───────────────────────────────────────────────────────────────

@router.get("/transcripts")
def list_transcripts():
    """
    Returns all sessions ordered newest-first.
    Each item includes: session_id, room_name, started_at, ended_at, turn_count.
    """
    conn = _transcript_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        return {"sessions": [dict(r) for r in rows]}
    except Exception as exc:
        logger.error("list_transcripts error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


@router.get("/transcripts/{session_id}")
def get_transcript(session_id: str):
    """
    Returns all turns for a session ordered by turn_index.
    Each turn: session_id, room_name, role, text, ts, turn_index.
    """
    conn = _transcript_conn()
    try:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

        turns = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
            (session_id,),
        ).fetchall()
        return {
            "session": dict(session),
            "turns":   [dict(t) for t in turns],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_transcript error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


# ── CRM Records ───────────────────────────────────────────────────────────────

@router.get("/crm")
def list_crm_records():
    """
    Returns a list of all CRM extraction JSON files found in crm_outputs/.
    Each item includes the filename (which is the session_id) and its parsed content.
    """
    if not CRM_OUTPUTS_DIR.exists():
        return {"records": []}

    records = []
    for path in sorted(CRM_OUTPUTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Use filename stem as the ID (e.g. "test_001_crm" or "<session_id>_crm")
            records.append({"id": path.stem, "file": path.name, **data})
        except Exception as exc:
            logger.warning("Could not read CRM file %s: %s", path, exc)

    return {"records": records}


@router.get("/crm/{record_id}")
def get_crm_record(record_id: str):
    """
    Returns a single CRM JSON file by its stem name (without .json extension).
    Example: /api/crm/test_001_crm
    """
    # Try exact stem match first
    path = CRM_OUTPUTS_DIR / f"{record_id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"CRM record '{record_id}' not found in {CRM_OUTPUTS_DIR}",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"id": record_id, "file": path.name, **data}
    except Exception as exc:
        logger.error("get_crm_record error for %s: %s", record_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Bills ─────────────────────────────────────────────────────────────────────

@router.get("/bills")
def list_bills():
    """
    Returns all bills from SQLite ordered by created_at descending.
    Columns: bill_id, order_id, service_type, room_number, guest_name,
             guest_phone, guest_email, items_json, subtotal, tax_rate,
             tax_amount, total, currency, status, payment_link,
             payu_txn_id, notes, created_at, paid_at.
    """
    conn = _payments_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM bills ORDER BY created_at DESC"
        ).fetchall()
        bills = []
        for r in rows:
            bill = dict(r)
            # Parse items_json so the frontend gets a real array, not a string
            try:
                bill["items"] = json.loads(bill.get("items_json") or "[]")
            except Exception:
                bill["items"] = []
            bills.append(bill)
        return {"bills": bills}
    except Exception as exc:
        logger.error("list_bills error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


@router.get("/bills/{order_id}")
def get_bill(order_id: str):
    """
    Returns a single bill row by its order_id.
    Also parses items_json into a proper 'items' array.
    """
    conn = _payments_conn()
    try:
        row = conn.execute(
            "SELECT * FROM bills WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Bill '{order_id}' not found")
        bill = dict(row)
        try:
            bill["items"] = json.loads(bill.get("items_json") or "[]")
        except Exception:
            bill["items"] = []
        return bill
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_bill error for %s: %s", order_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()