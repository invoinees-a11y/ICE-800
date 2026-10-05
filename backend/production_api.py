from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from audit import audit_event
from config import settings
from db import db
from security import decode_token
import plaid_service
from providers import method_service, engine_service

router = APIRouter(prefix="/api/v1", tags=["production"])


def current_user(authorization: str | None = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return decode_token(authorization.split(" ", 1)[1])
    except ValueError:
        raise HTTPException(401, "Invalid or expired token")


def _lang_for(user_id: int) -> str:
    with db() as con:
        row = con.execute("SELECT language FROM user_settings_v2 WHERE user_id=?", (user_id,)).fetchone()
    return (row["language"] if row else settings.default_language) or "es"


class LanguageIn(BaseModel):
    language: str = Field(pattern="^(es|en)$")


class MethodEntityIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=25)
    email: str | None = Field(None, max_length=200)
    dob: str | None = Field(None, max_length=10)
    address: dict[str, Any] | None = None


class MethodAccountAttachIn(BaseModel):
    account_id: str = Field(min_length=6, max_length=128)
    role: str = Field(pattern="^(source|liability|both)$")


class PaymentIntentIn(BaseModel):
    source_account_id: str = Field(min_length=4, max_length=128)
    destination_account_id: str = Field(min_length=4, max_length=128)
    amount_cents: int = Field(gt=0, le=100_000_000)
    description: str = Field("ICE-800 payment", min_length=1, max_length=64)


class PaymentConfirmIn(BaseModel):
    confirm: bool


class CardPreviewIn(BaseModel):
    zip_code: str | None = Field(None, min_length=5, max_length=10)
    provided_credit_rating: str | None = Field(None, max_length=40)
    card_purpose: str | None = Field(None, max_length=80)


class CardApplicationIn(BaseModel):
    personal_information: dict[str, Any] = Field(default_factory=dict)
    financial_information: dict[str, Any] = Field(default_factory=dict)
    credit_card_information: dict[str, Any] = Field(default_factory=dict)
    offer_name: str | None = Field(None, max_length=160)
    offer_id: str | None = Field(None, max_length=160)


@router.get("/capabilities")
def capabilities(user_id: int = Depends(current_user)):
    return {
        "plaid": {
            "configured": bool(os.getenv("PLAID_CLIENT_ID") and os.getenv("PLAID_SECRET")),
            "environment": os.getenv("PLAID_ENV", "sandbox"),
            "live_sync": True,
        },
        "method": {
            "configured": method_service.configured(),
            "environment": os.getenv("METHOD_ENV", "dev"),
            "liability_data": True,
            "payments": bool(settings.payments_enabled and method_service.configured()),
            "opal_launch_configured": bool(method_service.opal_launch_url()),
        },
        "engine": {
            "configured": engine_service.configured(),
            "applications": bool(settings.applications_enabled and engine_service.configured()),
        },
        "languages": ["es", "en"],
        "selected_language": _lang_for(user_id),
        "payment_confirmation_required": True,
    }


@router.get("/settings/language")
def get_language(user_id: int = Depends(current_user)):
    return {"language": _lang_for(user_id)}


@router.put("/settings/language")
def set_language(payload: LanguageIn, user_id: int = Depends(current_user)):
    with db() as con:
        con.execute(
            """INSERT INTO user_settings_v2(user_id,language) VALUES(?,?)
               ON CONFLICT(user_id) DO UPDATE SET language=excluded.language, updated_at=CURRENT_TIMESTAMP""",
            (user_id, payload.language),
        )
    audit_event(user_id, "language.changed", {"language": payload.language})
    return {"ok": True, "language": payload.language}


@router.post("/bank/link-token")
async def bank_link_token(user_id: int = Depends(current_user)):
    try:
        token = await plaid_service.create_link_token(user_id, language=_lang_for(user_id))
    except Exception as exc:
        raise HTTPException(503, f"Bank connection unavailable: {exc}")
    return {"link_token": token, "language": _lang_for(user_id)}


@router.get("/method/connect")
def method_connect(user_id: int = Depends(current_user)):
    url = method_service.opal_launch_url()
    if not url:
        raise HTTPException(503, "Method Opal launch URL is not configured for this partner account")
    audit_event(user_id, "method.connect_started", {})
    return {"launch_url": url}


@router.post("/method/entity")
async def method_entity(payload: MethodEntityIn, user_id: int = Depends(current_user)):
    if not method_service.configured():
        raise HTTPException(503, "Method is not configured")
    try:
        result = await method_service.create_entity(
            first_name=payload.first_name,
            last_name=payload.last_name,
            phone=payload.phone,
            email=payload.email,
            dob=payload.dob,
            address=payload.address,
        )
    except Exception as exc:
        raise HTTPException(502, str(exc))
    data = result.get("data", result)
    ent_id = data.get("id")
    if ent_id:
        with db() as con:
            con.execute(
                """INSERT INTO provider_profiles(user_id,method_entity_id,method_connect_status)
                   VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET method_entity_id=excluded.method_entity_id,
                   method_connect_status=excluded.method_connect_status, updated_at=CURRENT_TIMESTAMP""",
                (user_id, ent_id, "created"),
            )
    audit_event(user_id, "method.entity_created", {"method_entity_id": ent_id})
    return {"entity_id": ent_id, "status": data.get("status"), "capabilities": data.get("capabilities", [])}


def _provider_account(user_id: int, account_id: str):
    with db() as con:
        return con.execute(
            "SELECT * FROM provider_accounts WHERE user_id=? AND provider='method' AND provider_account_id=?",
            (user_id, account_id),
        ).fetchone()


@router.post("/method/accounts/attach")
async def attach_method_account(payload: MethodAccountAttachIn, user_id: int = Depends(current_user)):
    if not method_service.configured():
        raise HTTPException(503, "Method is not configured")
    with db() as con:
        profile = con.execute("SELECT method_entity_id FROM provider_profiles WHERE user_id=?", (user_id,)).fetchone()
    if not profile or not profile["method_entity_id"]:
        raise HTTPException(400, "Create/connect the Method entity first")
    try:
        result = await method_service.retrieve_account(payload.account_id)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    data = result.get("data", result)
    entity_id = data.get("entity_id") or data.get("holder_id")
    if entity_id and entity_id != profile["method_entity_id"]:
        raise HTTPException(403, "Method account does not belong to this ICE-800 user")
    if not entity_id:
        raise HTTPException(502, "Provider response did not include an entity owner; refusing to attach account")
    with db() as con:
        con.execute("""INSERT INTO provider_accounts(user_id,provider,provider_account_id,role,metadata_json)
                       VALUES(?,?,?,?,?) ON CONFLICT(user_id,provider,provider_account_id) DO UPDATE SET
                       role=excluded.role,metadata_json=excluded.metadata_json,updated_at=CURRENT_TIMESTAMP""",
                    (user_id, "method", payload.account_id, payload.role, json.dumps(data)))
    audit_event(user_id, "method.account_attached", {"account_id": payload.account_id, "role": payload.role})
    return {"ok": True, "account_id": payload.account_id, "role": payload.role}


@router.get("/provider-accounts")
def provider_accounts(user_id: int = Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "SELECT provider,provider_account_id,local_account_id,role,metadata_json,updated_at FROM provider_accounts WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/payments/intents")
def create_payment_intent(payload: PaymentIntentIn, user_id: int = Depends(current_user)):
    if not settings.payments_enabled:
        raise HTTPException(503, "Payments are not enabled for this deployment")
    if not _provider_account(user_id, payload.source_account_id) or not _provider_account(user_id, payload.destination_account_id):
        raise HTTPException(400, "Both payment accounts must be connected to this ICE-800 user")
    idem = secrets.token_urlsafe(24)
    with db() as con:
        cur = con.execute(
            """INSERT INTO payment_intents(user_id,provider,source_provider_account_id,destination_provider_account_id,
               amount_cents,description,idempotency_key,status) VALUES(?,?,?,?,?,?,?,'created')""",
            (user_id, "method", payload.source_account_id, payload.destination_account_id,
             payload.amount_cents, payload.description, idem),
        )
        intent_id = cur.lastrowid
    audit_event(user_id, "payment.intent_created", {"intent_id": intent_id, "amount_cents": payload.amount_cents})
    return {
        "intent_id": intent_id,
        "amount_cents": payload.amount_cents,
        "description": payload.description,
        "status": "requires_confirmation",
        "confirmation_required": True,
    }


@router.post("/payments/intents/{intent_id}/confirm")
async def confirm_payment(intent_id: int, payload: PaymentConfirmIn, user_id: int = Depends(current_user)):
    if not payload.confirm:
        raise HTTPException(400, "Explicit confirmation is required")
    if not settings.payments_enabled or not method_service.configured():
        raise HTTPException(503, "Live payments are not available in this deployment")
    with db() as con:
        row = con.execute("SELECT * FROM payment_intents WHERE id=? AND user_id=?", (intent_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Payment intent not found")
    if row["status"] in {"submitted", "completed", "pending"}:
        return {"intent_id": intent_id, "status": row["status"], "provider_payment_id": row["provider_payment_id"]}
    try:
        result = await method_service.create_payment(
            source_account_id=row["source_provider_account_id"],
            destination_account_id=row["destination_provider_account_id"],
            amount_cents=int(row["amount_cents"]),
            description=row["description"] or "ICE-800 payment",
        )
    except Exception as exc:
        with db() as con:
            con.execute("UPDATE payment_intents SET status='failed',provider_payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (json.dumps({"error": str(exc)}), intent_id))
        audit_event(user_id, "payment.failed", {"intent_id": intent_id})
        raise HTTPException(502, f"Payment provider rejected the request: {exc}")
    data = result.get("data", result)
    pid = data.get("id")
    status = data.get("status", "submitted")
    with db() as con:
        con.execute(
            """UPDATE payment_intents SET status=?,provider_payment_id=?,provider_payload_json=?,
               confirmed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (status, pid, json.dumps(data), intent_id),
        )
    audit_event(user_id, "payment.submitted", {"intent_id": intent_id, "provider_payment_id": pid})
    return {"intent_id": intent_id, "provider_payment_id": pid, "status": status}


@router.get("/payments")
def list_payments(user_id: int = Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "SELECT id,amount_cents,description,status,provider_payment_id,created_at,confirmed_at FROM payment_intents WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/cards/preview")
async def card_preview(payload: CardPreviewIn, user_id: int = Depends(current_user)):
    if not engine_service.configured():
        raise HTTPException(503, "Credit-card marketplace is not configured")
    try:
        offers = await engine_service.preview_credit_cards(
            zip_code=payload.zip_code,
            provided_credit_rating=payload.provided_credit_rating,
            card_purpose=payload.card_purpose,
        )
    except Exception as exc:
        raise HTTPException(502, str(exc))
    audit_event(user_id, "cards.preview", {"count": len(offers)})
    return {"offers": offers, "disclosure_required": True}


@router.post("/applications/card/start")
async def start_card_application(payload: CardApplicationIn, user_id: int = Depends(current_user)):
    if not settings.applications_enabled or not engine_service.configured():
        raise HTTPException(503, "Live card applications are not enabled for this deployment")
    req: dict[str, Any] = {}
    if payload.personal_information:
        req["personalInformation"] = payload.personal_information
    if payload.financial_information:
        req["financialInformation"] = payload.financial_information
    if payload.credit_card_information:
        req["creditCardInformation"] = payload.credit_card_information
    try:
        result = await engine_service.create_card_prefill(req)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    url = result.get("partnerPageUrl") or result.get("url") or engine_service.partner_page_url()
    with db() as con:
        cur = con.execute(
            """INSERT INTO credit_applications(user_id,provider,offer_id,offer_name,application_url,status,payload_json)
               VALUES(?,?,?,?,?,'started',?)""",
            (user_id, "engine", payload.offer_id, payload.offer_name, url, json.dumps({"response": result})),
        )
        app_id = cur.lastrowid
    audit_event(user_id, "application.started", {"application_id": app_id, "provider": "engine"})
    return {
        "application_id": app_id,
        "status": "user_action_required",
        "application_url": url,
        "message": "The user must review and complete the issuer/partner application flow.",
    }


@router.get("/applications")
def applications(user_id: int = Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "SELECT id,provider,offer_id,offer_name,application_url,status,prequalified,created_at,updated_at FROM credit_applications WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/method/webhook", include_in_schema=False)
async def method_webhook(request: Request, x_method_signature: str | None = Header(None)):
    raw = await request.body()
    secret = os.getenv("METHOD_WEBHOOK_SECRET", "")
    if secret:
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not x_method_signature or not hmac.compare_digest(expected, x_method_signature):
            raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    # Payload shapes vary by contracted Method product/version. Store idempotently for processing.
    event_key = str(payload.get("id") or payload.get("event_id") or hashlib.sha256(raw).hexdigest())
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO webhook_events(provider,event_key,payload_json) VALUES('method',?,?)",
            (event_key, json.dumps(payload)),
        )
    return {"ok": True}
