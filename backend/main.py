from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    class AsyncIOScheduler:  # development fallback when optional scheduler is not installed
        def __init__(self, *args, **kwargs): self.running = False
        def add_job(self, *args, **kwargs): return None
        def start(self): self.running = True
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from audit import audit_event
from beta import BETA_VERSION, RELEASE_CHANNEL, completion_percent, invite_code_fingerprint, invite_code_valid, onboarding_steps, safe_event_name
from config import settings
from credit_engine import CreditSnapshot, analyze_credit, merge_priorities
from credit_provider import CreditProviderError, get_credit_provider
from db import init_db, db
from ice_engine import CardState, StrategyConfig, analyze_portfolio, simulate_card
from optimization_engine import (
    DebtTransferScenario, LineReallocationScenario, CardCandidate, UserCardProfile,
    analyze_debt_transfer, analyze_line_reallocation, rank_card_candidates, rank_optimization_options,
)
from notifications import send_email
import plaid_service
from production_api import router as production_router
from security import hash_password, verify_password, make_token, decode_token, encrypt_secret, decrypt_secret
from clerk_auth import current_user as clerk_current_user, public_config

APP_DIR = Path(__file__).parent
log = logging.getLogger("ice800")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings.validate()
app = FastAPI(title="ICE-800 Credit Optimization Engine", version="production-candidate-1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Cron-Secret"],
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
scheduler = AsyncIOScheduler(timezone="UTC")
app.include_router(production_router)
credit_provider = get_credit_provider()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://cdn.plaid.com https://*.clerk.accounts.dev https://*.clerk.com; "
        "connect-src 'self' https://*.plaid.com https://*.clerk.accounts.dev https://api.clerk.com https://*.clerk.com; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.clerk.com https://*.clerk.accounts.dev; "
        "font-src 'self' data: https://*.clerk.com https://*.clerk.accounts.dev; "
        "frame-src https://*.plaid.com https://*.clerk.accounts.dev https://*.clerk.com; object-src 'none'; base-uri 'self'"
    )
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class AuthIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class RegisterIn(AuthIn):
    invite_code: str | None = Field(None, max_length=128)
    accept_terms: bool = False
    accept_privacy: bool = False


class BetaFeedbackIn(BaseModel):
    feedback_type: str = Field(pattern="^(bug|idea|confusing|other)$")
    rating: int | None = Field(None, ge=1, le=5)
    message: str = Field(min_length=3, max_length=2000)
    page: str | None = Field(None, max_length=80)


class BetaEventIn(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    page: str | None = Field(None, max_length=80)


class ExchangeIn(BaseModel):
    public_token: str
    institution_name: str | None = None


class PrefsIn(BaseModel):
    target_low: float = Field(0.03, ge=0, le=0.30)
    target_high: float = Field(0.05, ge=0, le=0.30)
    warning: float = Field(0.07, ge=0, le=0.50)
    user_max: float = Field(0.10, ge=0, le=1)
    hard_warning: float = Field(0.30, ge=0, le=1)
    close_lead_days: int = Field(3, ge=0, le=14)
    due_lead_days: int = Field(5, ge=0, le=14)
    email_notifications: bool = True


class SimulationIn(BaseModel):
    account_id: str
    spend: float = Field(0, ge=0, le=1_000_000)
    payment: float = Field(0, ge=0, le=1_000_000)


class CreditReportIn(BaseModel):
    provider: str | None = None
    score_model: str | None = None
    score: int | None = Field(None, ge=300, le=850)
    report_date: date | None = None
    utilization: float | None = Field(None, ge=0, le=5)
    hard_inquiries_6m: int | None = Field(None, ge=0, le=100)
    late_payments_24m: int | None = Field(None, ge=0, le=100)
    collections_count: int | None = Field(None, ge=0, le=100)
    derogatory_count: int | None = Field(None, ge=0, le=100)
    oldest_age_months: int | None = Field(None, ge=0, le=1200)
    average_age_months: int | None = Field(None, ge=0, le=1200)
    total_accounts: int | None = Field(None, ge=0, le=500)


class ConsentIn(BaseModel):
    consent_type: str = Field(pattern="^(credit_report|terms|privacy)$")
    version: str
    granted: bool


class AlertReadIn(BaseModel):
    alert_id: int


class DebtTransferIn(BaseModel):
    source_name: str
    balance: float = Field(gt=0, le=1_000_000)
    source_apr: float = Field(ge=0, le=2)
    target_name: str
    target_available_credit: float = Field(ge=0, le=1_000_000)
    promo_apr: float = Field(0, ge=0, le=2)
    promo_months: int = Field(12, ge=1, le=60)
    transfer_fee_pct: float = Field(0.03, ge=0, le=0.25)
    post_promo_apr: float | None = Field(None, ge=0, le=2)
    requested_transfer: float | None = Field(None, ge=0, le=1_000_000)


class LineReallocationIn(BaseModel):
    source_account_id: str
    target_account_id: str
    amount: float = Field(gt=0, le=1_000_000)
    minimum_source_limit: float = Field(500, ge=0, le=1_000_000)


class LineReallocationScenarioIn(BaseModel):
    issuer: str
    source_name: str = "Tarjeta donante"
    source_balance: float = Field(ge=0, le=1_000_000)
    source_limit: float = Field(gt=0, le=1_000_000)
    target_name: str = "Tarjeta objetivo"
    target_balance: float = Field(ge=0, le=1_000_000)
    target_limit: float = Field(gt=0, le=1_000_000)
    amount: float = Field(gt=0, le=1_000_000)
    minimum_source_limit: float = Field(500, ge=0, le=1_000_000)


class CandidateCardIn(BaseModel):
    name: str
    issuer: str
    annual_fee: float = Field(0, ge=0, le=10_000)
    intro_apr_months: int = Field(0, ge=0, le=60)
    balance_transfer_intro_months: int = Field(0, ge=0, le=60)
    prequalification_available: bool = False
    rewards_fit: float = Field(0.5, ge=0, le=1)
    overlap: float = Field(0, ge=0, le=1)
    welcome_value: float = Field(0, ge=0, le=100_000)
    expected_yearly_rewards: float = Field(0, ge=0, le=100_000)
    application_url: str | None = None
    prequal_url: str | None = None
    source_url: str | None = None
    terms_verified_on: str | None = None


class OptimizationCompareIn(BaseModel):
    payment: dict | None = None
    line_reallocation: dict | None = None
    debt_transfer: dict | None = None
    new_card: dict | None = None


class CardRecommendationIn(BaseModel):
    carry_balance: bool = False
    needs_balance_transfer: bool = False
    recent_hard_inquiries: int = Field(0, ge=0, le=100)
    recently_opened_accounts: int = Field(0, ge=0, le=100)
    prefers_no_annual_fee: bool = True
    values_rewards: bool = True
    prequalification_first: bool = True
    candidates: list[CandidateCardIn]


def current_user(authorization: str | None = Header(None)) -> int:
    return clerk_current_user(authorization)


def config_for(user_id: int) -> StrategyConfig:
    with db() as con:
        row = con.execute("SELECT * FROM preferences WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return StrategyConfig()
    return StrategyConfig(
        target_low=row["target_low"], target_high=row["target_high"], warning=row["warning"],
        user_max=row["user_max"], hard_warning=row["hard_warning"],
        close_lead_days=row["close_lead_days"], due_lead_days=row["due_lead_days"],
    )


def parse_date(v):
    return date.fromisoformat(v) if v else None


def card_rows_for(user_id: int):
    with db() as con:
        return con.execute("""
          SELECT a.*, l.last_statement_issue_date, l.last_statement_balance,
                 l.next_payment_due_date, l.minimum_payment, l.last_payment_date,
                 l.last_payment_amount, l.is_overdue, l.apr
          FROM accounts a LEFT JOIN liabilities l USING(account_id)
          WHERE a.user_id=? AND a.type='credit'
        """, (user_id,)).fetchall()


def row_to_card(r) -> CardState:
    return CardState(
        account_id=r["account_id"], name=r["name"], balance=float(r["balance"] or 0),
        credit_limit=float(r["credit_limit"]) if r["credit_limit"] is not None else None,
        last_statement_issue_date=parse_date(r["last_statement_issue_date"]),
        statement_balance=float(r["last_statement_balance"]) if r["last_statement_balance"] is not None else None,
        next_payment_due_date=parse_date(r["next_payment_due_date"]),
        minimum_payment=float(r["minimum_payment"]) if r["minimum_payment"] is not None else None,
        is_overdue=bool(r["is_overdue"]), apr=float(r["apr"]) if r["apr"] is not None else None,
    )


def portfolio_for(user_id: int):
    return analyze_portfolio([row_to_card(r) for r in card_rows_for(user_id)], config_for(user_id))

def credit_account_detail(user_id: int, account_id: str):
    with db() as con:
        return con.execute("""
          SELECT a.*, c.institution_name, l.apr, l.next_payment_due_date, l.last_statement_balance
          FROM accounts a JOIN connections c ON c.id=a.connection_id
          LEFT JOIN liabilities l ON l.account_id=a.account_id
          WHERE a.user_id=? AND a.account_id=? AND a.type='credit'
        """, (user_id, account_id)).fetchone()


def issuer_policy(name: str) -> dict:
    n=(name or '').lower()
    if 'chase' in n:
        return {
          "issuer":"Chase", "line_reallocation":"supported_for_eligible_accounts", "policy_eligible":True,
          "note":"Chase permite mover línea disponible entre tarjetas personales elegibles (o entre tarjetas business elegibles); aplican mínimos y restricciones de elegibilidad.",
          "verified_on":"2026-10-04", "source":"https://www.chase.com/personal/credit-cards/creditline-exchange"
        }
    if 'capital one' in n or 'discover' in n:
        return {
          "issuer":"Capital One / Discover", "line_reallocation":"supported_for_eligible_accounts", "policy_eligible":True,
          "note":"Capital One permite a clientes elegibles transferir parte de la línea disponible entre determinadas tarjetas Capital One y/o Discover; no transfiere el saldo de deuda.",
          "verified_on":"2026-10-04", "source":"https://www.capitalone.com/credit-cards/faq/line-transfer/"
        }
    return {
      "issuer":name or "Unknown", "line_reallocation":"confirm_with_issuer", "policy_eligible":None,
      "note":"ICE-800 no tiene una regla confirmada para este emisor; verifica elegibilidad directamente antes de actuar.",
      "verified_on":None, "source":None
    }


def latest_credit_snapshot(user_id: int):
    with db() as con:
        rows = con.execute(
            "SELECT * FROM credit_reports WHERE user_id=? ORDER BY COALESCE(report_date, created_at) DESC, id DESC LIMIT 2",
            (user_id,),
        ).fetchall()
    if not rows:
        return None
    r = rows[0]
    prev_score = rows[1]["score"] if len(rows) > 1 else None
    return CreditSnapshot(
        score=r["score"], score_model=r["score_model"], report_date=parse_date(r["report_date"]), provider=r["provider"],
        utilization=r["utilization"], hard_inquiries_6m=r["hard_inquiries_6m"], late_payments_24m=r["late_payments_24m"],
        collections_count=r["collections_count"], derogatory_count=r["derogatory_count"], oldest_age_months=r["oldest_age_months"],
        average_age_months=r["average_age_months"], total_accounts=r["total_accounts"], previous_score=prev_score,
    )


def credit_history_for(user_id: int):
    with db() as con:
        rows = con.execute(
            "SELECT score,score_model,provider,report_date,created_at FROM credit_reports "
            "WHERE user_id=? AND score IS NOT NULL ORDER BY COALESCE(report_date, created_at) ASC, id ASC LIMIT 24",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def consent_granted(user_id: int, consent_type: str, version: str) -> bool:
    with db() as con:
        row = con.execute(
            "SELECT granted FROM consents WHERE user_id=? AND consent_type=? AND version=?",
            (user_id, consent_type, version),
        ).fetchone()
    return bool(row and row["granted"])


def connection_summary(user_id: int) -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            "SELECT id,institution_name,status,last_sync_at,last_sync_error,created_at FROM connections WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def beta_status_for(user_id: int) -> dict[str, Any]:
    with db() as con:
        profile = con.execute("SELECT * FROM beta_profiles WHERE user_id=?", (user_id,)).fetchone()
        has_connection = bool(con.execute("SELECT 1 FROM connections WHERE user_id=? LIMIT 1", (user_id,)).fetchone())
        has_report = bool(con.execute("SELECT 1 FROM credit_reports WHERE user_id=? LIMIT 1", (user_id,)).fetchone())
        terms = bool(con.execute("SELECT 1 FROM consents WHERE user_id=? AND consent_type='terms' AND version=? AND granted=1 LIMIT 1", (user_id, settings.terms_version)).fetchone())
        privacy = bool(con.execute("SELECT 1 FROM consents WHERE user_id=? AND consent_type='privacy' AND version=? AND granted=1 LIMIT 1", (user_id, settings.privacy_version)).fetchone())
        credit_consent = bool(con.execute("SELECT 1 FROM consents WHERE user_id=? AND consent_type='credit_report' AND granted=1 LIMIT 1", (user_id,)).fetchone())
        strategy_reviewed = bool(profile and profile["strategy_reviewed_at"])
        feedback_count = con.execute("SELECT COUNT(*) c FROM beta_feedback WHERE user_id=?", (user_id,)).fetchone()["c"]
    steps = onboarding_steps(
        accepted_terms=terms,
        accepted_privacy=privacy,
        has_connection=has_connection,
        has_credit_report=has_report or credit_consent,
        strategy_customized=strategy_reviewed,
    )
    pct = completion_percent(steps)
    if pct == 100 and profile and not profile["onboarding_completed_at"]:
        with db() as con:
            con.execute("UPDATE beta_profiles SET onboarding_completed_at=CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
    return {
        "version": BETA_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "cohort": profile["cohort"] if profile else settings.beta_cohort,
        "steps": steps,
        "completion_percent": pct,
        "feedback_count": feedback_count,
        "invite_required": settings.beta_invite_required,
        "terms_version": settings.terms_version,
        "privacy_version": settings.privacy_version,
    }


def dashboard_for(user_id: int):
    portfolio = portfolio_for(user_id)
    credit = analyze_credit(latest_credit_snapshot(user_id), portfolio)
    merged = merge_priorities(portfolio, credit)
    portfolio["credit"] = credit
    portfolio["credit_history"] = credit_history_for(user_id)
    portfolio["priority_queue"] = merged["queue"]
    portfolio["next_best_action"] = merged["next_best_action"] or portfolio.get("next_best_action")
    portfolio["connections"] = connection_summary(user_id)
    portfolio["beta"] = beta_status_for(user_id)
    portfolio["autopilot"] = {
        "enabled": True,
        "sync_interval_hours": settings.sync_interval_hours,
        "credit_provider": credit_provider.name,
        "credit_provider_configured": credit_provider.configured(),
        "credit_consent": consent_granted(user_id, "credit_report", settings.credit_consent_version),
        "mode": "production" if settings.app_env == "production" else "development",
    }
    return portfolio


def save_credit_snapshot(user_id: int, payload: dict[str, Any]) -> None:
    with db() as con:
        con.execute("""
          INSERT INTO credit_reports(user_id,provider,score_model,score,report_date,utilization,hard_inquiries_6m,late_payments_24m,
            collections_count,derogatory_count,oldest_age_months,average_age_months,total_accounts,payload_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user_id, payload.get("provider"), payload.get("score_model"), payload.get("score"), payload.get("report_date"),
            payload.get("utilization"), payload.get("hard_inquiries_6m"), payload.get("late_payments_24m"),
            payload.get("collections_count"), payload.get("derogatory_count"), payload.get("oldest_age_months"),
            payload.get("average_age_months"), payload.get("total_accounts"), json.dumps(payload, default=str),
        ))


@app.on_event("startup")
async def startup():
    init_db()
    if settings.enable_in_process_scheduler and not scheduler.running:
        scheduler.add_job(run_all_syncs, "interval", hours=settings.sync_interval_hours, id="sync_all", replace_existing=True)
        scheduler.add_job(run_daily_alerts, "cron", hour=13, minute=0, id="daily_alerts", replace_existing=True)
        scheduler.start()


@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(APP_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(APP_DIR / "static" / "sw.js", media_type="application/javascript")


@app.get("/api/health")
def health():
    return {
        "ok": True, "name": "ICE-800", "version": "production-candidate-1.0", "environment": settings.app_env,
        "credit_provider": credit_provider.name, "credit_provider_configured": credit_provider.configured(),
    }


@app.get("/api/public-config")
def get_public_config():
    return public_config()


@app.post("/api/register", include_in_schema=False)
def register(x: RegisterIn):
    raise HTTPException(410, "Legacy ICE-800 authentication is disabled. Use Clerk Secure Access.")
    if not invite_code_valid(x.invite_code, settings.beta_invite_codes, settings.beta_invite_required):
        raise HTTPException(403, "Código de acceso inválido")
    if not x.accept_terms or not x.accept_privacy:
        raise HTTPException(400, "Debes aceptar los términos y la privacidad para crear la cuenta")
    fp = invite_code_fingerprint(x.invite_code)
    if settings.beta_invite_single_use and fp:
        with db() as con:
            if con.execute("SELECT 1 FROM beta_profiles WHERE invite_fingerprint=? LIMIT 1", (fp,)).fetchone():
                raise HTTPException(409, "Este código de acceso ya fue utilizado")
    try:
        with db() as con:
            cur = con.execute("INSERT INTO users(email,password_hash) VALUES(?,?)", (x.email.lower(), hash_password(x.password)))
            uid = cur.lastrowid
            con.execute("INSERT OR IGNORE INTO preferences(user_id) VALUES(?)", (uid,))
            con.execute("INSERT OR IGNORE INTO user_settings_v2(user_id,language) VALUES(?,?)", (uid, settings.default_language))
            con.execute(
                "INSERT INTO beta_profiles(user_id,cohort,invite_fingerprint,last_seen_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                (uid, settings.beta_cohort, fp),
            )
            con.execute("INSERT INTO consents(user_id,consent_type,version,granted) VALUES(?,?,?,?)", (uid, "terms", settings.terms_version, 1))
            con.execute("INSERT INTO consents(user_id,consent_type,version,granted) VALUES(?,?,?,?)", (uid, "privacy", settings.privacy_version, 1))
        audit_event(uid, "user.registered", {"release_channel": RELEASE_CHANNEL, "cohort": settings.beta_cohort})
        return {"token": make_token(uid), "release": "production-candidate"}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(409, "Email already registered")
        raise


@app.post("/api/login", include_in_schema=False)
def login(x: AuthIn):
    raise HTTPException(410, "Legacy ICE-800 authentication is disabled. Use Clerk Secure Access.")
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (x.email.lower(),)).fetchone()
    if not row or not verify_password(x.password, row["password_hash"]):
        audit_event(row["id"] if row else None, "auth.failed")
        raise HTTPException(401, "Invalid credentials")
    with db() as con:
        con.execute("UPDATE beta_profiles SET last_seen_at=CURRENT_TIMESTAMP WHERE user_id=?", (row["id"],))
    audit_event(row["id"], "auth.login")
    return {"token": make_token(row["id"])}


@app.get("/api/consents")
def consents(user_id: int = Depends(current_user)):
    with db() as con:
        rows = con.execute("SELECT consent_type,version,granted,created_at FROM consents WHERE user_id=?", (user_id,)).fetchall()
    return {
        "required": {
            "credit_report": settings.credit_consent_version,
            "privacy": settings.privacy_version,
            "terms": settings.terms_version,
        },
        "records": [dict(r) for r in rows],
    }


@app.post("/api/consents")
def set_consent(x: ConsentIn, user_id: int = Depends(current_user)):
    with db() as con:
        con.execute(
            "INSERT INTO consents(user_id,consent_type,version,granted) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,consent_type,version) DO UPDATE SET granted=excluded.granted, created_at=CURRENT_TIMESTAMP",
            (user_id, x.consent_type, x.version, int(x.granted)),
        )
    audit_event(user_id, "consent.changed", x.model_dump())
    return {"ok": True}


@app.post("/api/plaid/link-token")
async def link_token(user_id: int = Depends(current_user)):
    if not consent_granted(user_id, "terms", settings.terms_version) or not consent_granted(user_id, "privacy", settings.privacy_version):
        raise HTTPException(403, "Debes aceptar los términos y la privacidad vigentes antes de vincular cuentas")
    with db() as con:
        lr = con.execute("SELECT language FROM user_settings_v2 WHERE user_id=?", (user_id,)).fetchone()
    lang = lr["language"] if lr else settings.default_language
    token = await plaid_service.create_link_token(user_id, language=lang)
    audit_event(user_id, "plaid.link_token_created")
    return {"link_token": token}


@app.post("/api/plaid/exchange")
async def exchange(x: ExchangeIn, user_id: int = Depends(current_user)):
    data = await plaid_service.exchange_public_token(x.public_token)
    with db() as con:
        con.execute("""
          INSERT INTO connections(user_id,item_id,institution_name,access_token_enc,status)
          VALUES(?,?,?,?, 'active')
          ON CONFLICT(user_id,item_id) DO UPDATE SET institution_name=excluded.institution_name,
            access_token_enc=excluded.access_token_enc,status='active',last_sync_error=NULL
        """, (user_id, data["item_id"], x.institution_name, encrypt_secret(data["access_token"])))
    audit_event(user_id, "plaid.connection_added", {"item_id": data["item_id"], "institution": x.institution_name})
    await sync_user(user_id, source="link")
    return {"ok": True}


@app.get("/api/connections")
def connections(user_id: int = Depends(current_user)):
    return {"connections": connection_summary(user_id)}


@app.delete("/api/connections/{connection_id}")
async def disconnect(connection_id: int, user_id: int = Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT * FROM connections WHERE id=? AND user_id=?", (connection_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Connection not found")
    try:
        await plaid_service.remove_item(decrypt_secret(row["access_token_enc"]))
    except Exception as e:
        log.warning("provider disconnect failed connection=%s: %s", connection_id, e)
    with db() as con:
        account_ids = [r["account_id"] for r in con.execute("SELECT account_id FROM accounts WHERE connection_id=? AND user_id=?", (connection_id, user_id)).fetchall()]
        for account_id in account_ids:
            con.execute("DELETE FROM liabilities WHERE account_id=?", (account_id,))
        con.execute("DELETE FROM accounts WHERE connection_id=? AND user_id=?", (connection_id, user_id))
        con.execute("DELETE FROM connections WHERE id=? AND user_id=?", (connection_id, user_id))
    audit_event(user_id, "plaid.connection_removed", {"connection_id": connection_id})
    return {"ok": True}


async def sync_user(user_id: int, source: str = "manual"):
    with db() as con:
        run = con.execute("INSERT INTO sync_runs(user_id,source,status) VALUES(?,?,?)", (user_id, source, "running"))
        run_id = run.lastrowid
        conns = con.execute("SELECT * FROM connections WHERE user_id=? AND status='active'", (user_id,)).fetchall()
    errors: list[str] = []
    for conn in conns:
        try:
            token = decrypt_secret(conn["access_token_enc"])
            accts = await plaid_service.accounts(token)
            liabs = await plaid_service.liabilities(token)
            by_id = {item.get("account_id"): item for item in (liabs.get("credit", []) if isinstance(liabs, dict) else [])}

            # Incremental transaction synchronization. Plaid supplies a cursor; persist it per Item.
            tx_added, tx_modified, tx_removed = [], [], []
            cursor = conn["transactions_cursor"] if "transactions_cursor" in conn.keys() else None
            try:
                while True:
                    tx_page = await plaid_service.transactions_sync(token, cursor)
                    tx_added.extend(tx_page.get("added", []))
                    tx_modified.extend(tx_page.get("modified", []))
                    tx_removed.extend(tx_page.get("removed", []))
                    cursor = tx_page.get("next_cursor") or cursor
                    if not tx_page.get("has_more"):
                        break
            except Exception as tx_exc:
                # Accounts/liabilities are still useful while Transactions is warming or temporarily unavailable.
                log.warning("transactions sync deferred user=%s connection=%s: %s", user_id, conn["id"], tx_exc)
            with db() as con:
                for a in accts:
                    b = a.get("balances") or {}
                    con.execute("""
                      INSERT INTO accounts(user_id,connection_id,account_id,name,type,subtype,mask,balance,available,credit_limit,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                      ON CONFLICT(user_id,account_id) DO UPDATE SET
                        connection_id=excluded.connection_id,name=excluded.name,type=excluded.type,subtype=excluded.subtype,mask=excluded.mask,
                        balance=excluded.balance,available=excluded.available,credit_limit=excluded.credit_limit,updated_at=CURRENT_TIMESTAMP
                    """, (user_id, conn["id"], a["account_id"], a.get("name") or "Account", a.get("type"), a.get("subtype"),
                          a.get("mask"), b.get("current"), b.get("available"), b.get("limit")))
                for account_id, l in by_id.items():
                    aprs = l.get("aprs") or []
                    apr = next((z.get("apr_percentage") for z in aprs if z.get("apr_type") == "purchase_apr"), None)
                    con.execute("""
                      INSERT INTO liabilities(account_id,last_statement_issue_date,last_statement_balance,next_payment_due_date,
                        minimum_payment,last_payment_date,last_payment_amount,is_overdue,apr,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                      ON CONFLICT(account_id) DO UPDATE SET
                        last_statement_issue_date=excluded.last_statement_issue_date,last_statement_balance=excluded.last_statement_balance,
                        next_payment_due_date=excluded.next_payment_due_date,minimum_payment=excluded.minimum_payment,
                        last_payment_date=excluded.last_payment_date,last_payment_amount=excluded.last_payment_amount,
                        is_overdue=excluded.is_overdue,apr=excluded.apr,updated_at=CURRENT_TIMESTAMP
                    """, (account_id, l.get("last_statement_issue_date"), l.get("last_statement_balance"),
                          l.get("next_payment_due_date"), l.get("minimum_payment_amount"), l.get("last_payment_date"),
                          l.get("last_payment_amount"), int(bool(l.get("is_overdue"))), apr))
                for tx in tx_added + tx_modified:
                    con.execute("""
                      INSERT INTO bank_transactions(user_id,connection_id,account_id,transaction_id,amount,iso_currency_code,merchant_name,name,category_json,pending,transaction_date,authorized_date,removed,payload_json,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,CURRENT_TIMESTAMP)
                      ON CONFLICT(user_id,transaction_id) DO UPDATE SET
                        connection_id=excluded.connection_id,account_id=excluded.account_id,amount=excluded.amount,iso_currency_code=excluded.iso_currency_code,
                        merchant_name=excluded.merchant_name,name=excluded.name,category_json=excluded.category_json,pending=excluded.pending,
                        transaction_date=excluded.transaction_date,authorized_date=excluded.authorized_date,removed=0,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP
                    """, (user_id, conn["id"], tx.get("account_id"), tx.get("transaction_id"), tx.get("amount"),
                          tx.get("iso_currency_code"), tx.get("merchant_name"), tx.get("name"),
                          json.dumps(tx.get("personal_finance_category") or tx.get("category") or {}), int(bool(tx.get("pending"))),
                          tx.get("date"), tx.get("authorized_date"), json.dumps(tx)))
                for tx in tx_removed:
                    tid = tx.get("transaction_id")
                    if tid:
                        con.execute("UPDATE bank_transactions SET removed=1,updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND transaction_id=?", (user_id, tid))
                con.execute("UPDATE connections SET transactions_cursor=?,last_sync_at=CURRENT_TIMESTAMP,last_sync_error=NULL WHERE id=?", (cursor, conn["id"]))
        except Exception as e:
            errors.append(f"{conn['id']}: {type(e).__name__}")
            with db() as con:
                con.execute("UPDATE connections SET last_sync_error=? WHERE id=?", (str(e)[:500], conn["id"]))
            log.exception("sync failed user=%s connection=%s", user_id, conn["id"])
    with db() as con:
        con.execute(
            "UPDATE sync_runs SET status=?,detail=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
            ("partial" if errors else "success", "; ".join(errors) if errors else None, run_id),
        )
    audit_event(user_id, "sync.completed", {"source": source, "connections": len(conns), "errors": len(errors)})


@app.post("/api/sync")
async def sync(user_id: int = Depends(current_user)):
    await sync_user(user_id)
    return dashboard_for(user_id)


@app.post("/api/plaid/webhook")
async def plaid_webhook(request: Request):
    raw_body = await request.body()
    verify_required = os.getenv("PLAID_VERIFY_WEBHOOKS", "true").lower() == "true"
    if verify_required:
        signed_jwt = request.headers.get("Plaid-Verification")
        if not await plaid_service.verify_webhook(raw_body, signed_jwt):
            raise HTTPException(status_code=401, detail="Invalid Plaid webhook signature")
    payload = json.loads(raw_body.decode("utf-8"))
    item_id = payload.get("item_id") or payload.get("user_id") or "unknown"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    event_key = hashlib.sha256((str(item_id) + raw).encode()).hexdigest()
    with db() as con:
        try:
            con.execute("INSERT INTO webhook_events(provider,event_key,payload_json) VALUES('plaid',?,?)", (event_key, raw))
        except Exception as e:
            if "UNIQUE" in str(e):
                return {"ok": True, "duplicate": True}
            raise
        users = con.execute("SELECT DISTINCT user_id FROM connections WHERE item_id=?", (payload.get("item_id"),)).fetchall()
    for u in users:
        await sync_user(u["user_id"], source=f"plaid:{payload.get('webhook_type','event')}")
    with db() as con:
        con.execute("UPDATE webhook_events SET processed_at=CURRENT_TIMESTAMP WHERE provider='plaid' AND event_key=?", (event_key,))
    return {"ok": True}


@app.get("/api/transactions")
def transactions(limit: int = 100, user_id: int = Depends(current_user)):
    limit = max(1, min(int(limit), 500))
    with db() as con:
        rows = con.execute("""
          SELECT transaction_id,account_id,amount,iso_currency_code,merchant_name,name,pending,transaction_date,authorized_date
          FROM bank_transactions WHERE user_id=? AND removed=0
          ORDER BY COALESCE(transaction_date,authorized_date) DESC, id DESC LIMIT ?
        """, (user_id, limit)).fetchall()
    return {"transactions": [dict(r) for r in rows]}


@app.get("/api/dashboard")
def dashboard(user_id: int = Depends(current_user)):
    return dashboard_for(user_id)


@app.get("/api/calendar")
def calendar(user_id: int = Depends(current_user)):
    p = dashboard_for(user_id)
    return {"as_of": p["as_of"], "events": p["calendar"]}


@app.get("/api/preferences")
def get_preferences(user_id: int = Depends(current_user)):
    cfg = config_for(user_id)
    with db() as con:
        row = con.execute("SELECT email_notifications FROM preferences WHERE user_id=?", (user_id,)).fetchone()
    return {**cfg.__dict__, "email_notifications": bool(row["email_notifications"]) if row else True}


@app.put("/api/preferences")
def preferences(x: PrefsIn, user_id: int = Depends(current_user)):
    if not (x.target_low <= x.target_high <= x.warning <= x.user_max <= x.hard_warning):
        raise HTTPException(400, "Use ascending thresholds: target_low ≤ target_high ≤ warning ≤ user_max ≤ hard_warning")
    with db() as con:
        con.execute("""
          INSERT INTO preferences(user_id,target_low,target_high,warning,user_max,hard_warning,close_lead_days,due_lead_days,email_notifications)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET target_low=excluded.target_low,target_high=excluded.target_high,
          warning=excluded.warning,user_max=excluded.user_max,hard_warning=excluded.hard_warning,
          close_lead_days=excluded.close_lead_days,due_lead_days=excluded.due_lead_days,email_notifications=excluded.email_notifications
        """, (user_id, x.target_low, x.target_high, x.warning, x.user_max, x.hard_warning, x.close_lead_days, x.due_lead_days, int(x.email_notifications)))
    with db() as con:
        con.execute("UPDATE beta_profiles SET strategy_reviewed_at=CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
    audit_event(user_id, "strategy.updated", x.model_dump())
    return dashboard_for(user_id)


@app.get("/api/credit/provider/status")
def provider_status(user_id: int = Depends(current_user)):
    return {
        "provider": credit_provider.name,
        "configured": credit_provider.configured(),
        "consent_version": settings.credit_consent_version,
        "consent_granted": consent_granted(user_id, "credit_report", settings.credit_consent_version),
        "note": "A real bureau/credit-report connection requires a contracted provider and a compliant consumer-consent flow.",
    }


@app.post("/api/credit/provider/sync")
async def sync_credit_provider(user_id: int = Depends(current_user)):
    if not consent_granted(user_id, "credit_report", settings.credit_consent_version):
        raise HTTPException(403, "Credit-report consent is required")
    try:
        payload = await credit_provider.fetch_snapshot(str(user_id))
    except CreditProviderError as e:
        raise HTTPException(503, str(e))
    save_credit_snapshot(user_id, payload)
    audit_event(user_id, "credit_report.synced", {"provider": credit_provider.name})
    return dashboard_for(user_id)


@app.get("/api/credit/analysis")
def credit_analysis(user_id: int = Depends(current_user)):
    p = portfolio_for(user_id)
    c = analyze_credit(latest_credit_snapshot(user_id), p)
    return {**c, "history": credit_history_for(user_id)}


@app.post("/api/credit/report")
def save_credit_report(x: CreditReportIn, user_id: int = Depends(current_user)):
    if settings.app_env == "production":
        raise HTTPException(403, "Manual credit snapshots are disabled in production")
    payload = x.model_dump(mode="json")
    save_credit_snapshot(user_id, payload)
    audit_event(user_id, "credit_report.manual_snapshot", {"provider": x.provider, "report_date": payload.get("report_date")})
    return dashboard_for(user_id)




@app.get("/api/optimization/platforms")
def optimization_platforms(user_id: int = Depends(current_user)):
    return {
      "application_platforms":[
        {
          "name":"Bankrate CardMatch",
          "type":"multi_issuer_prequalification",
          "url":"https://www.bankrate.com/credit-cards/tools/cardmatch/",
          "credit_check":"soft inquiry according to the platform",
          "note":"Úsalo como etapa de descubrimiento/precalificación; ICE-800 debe volver a verificar la oferta y el emisor antes de recomendar APPLY.",
          "verified_on":"2026-10-04"
        },
        {
          "name":"Issuer official application",
          "type":"official_issuer",
          "url":None,
          "credit_check":"may become a hard inquiry when a formal application is submitted",
          "note":"ICE-800 prioriza la precalificación cuando existe y la solicitud final en el sitio oficial del emisor."
        }
      ],
      "issuer_policies":[issuer_policy("Chase"), issuer_policy("Capital One")],
      "disclosure":"Las políticas y ofertas cambian. La Beta trata estas reglas como datos versionados que deben revisarse periódicamente."
    }


@app.post("/api/optimization/debt-transfer")
def optimization_debt_transfer(x: DebtTransferIn, user_id: int = Depends(current_user)):
    r=analyze_debt_transfer(DebtTransferScenario(**x.model_dump()))
    audit_event(user_id, "optimization.debt_transfer", {"verdict":r.get("verdict"),"source":x.source_name,"target":x.target_name})
    return r


@app.post("/api/optimization/line-reallocation")
def optimization_line_reallocation(x: LineReallocationIn, user_id: int = Depends(current_user)):
    src=credit_account_detail(user_id,x.source_account_id); dst=credit_account_detail(user_id,x.target_account_id)
    if not src or not dst: raise HTTPException(404,"Credit card not found")
    if src["account_id"]==dst["account_id"]: raise HTTPException(400,"Choose two different cards")
    if not src["credit_limit"] or not dst["credit_limit"]: raise HTTPException(400,"Both cards need known credit limits")
    same_issuer=(src["institution_name"] or '').lower()==(dst["institution_name"] or '').lower()
    policy=issuer_policy(src["institution_name"] if same_issuer else "")
    if not same_issuer:
        policy={"policy_eligible":False,"note":"La reasignación de línea se modela solo entre cuentas del mismo emisor; esto no es un balance transfer.","source":None}
    cfg=config_for(user_id)
    scenario=LineReallocationScenario(
      issuer=src["institution_name"] or "Issuer", source_name=src["name"], source_balance=float(src["balance"] or 0),
      source_limit=float(src["credit_limit"]), target_name=dst["name"], target_balance=float(dst["balance"] or 0),
      target_limit=float(dst["credit_limit"]), amount=x.amount, minimum_source_limit=x.minimum_source_limit,
      policy_eligible=policy.get("policy_eligible"), policy_note=policy.get("note")
    )
    r=analyze_line_reallocation(scenario,target_high=cfg.target_high,user_max=cfg.user_max)
    r["policy_source"]=policy.get("source")
    audit_event(user_id,"optimization.line_reallocation",{"verdict":r.get("verdict"),"source_account":x.source_account_id,"target_account":x.target_account_id})
    return r


@app.post("/api/optimization/line-reallocation/simulate")
def optimization_line_reallocation_simulate(x: LineReallocationScenarioIn, user_id: int = Depends(current_user)):
    policy=issuer_policy(x.issuer)
    cfg=config_for(user_id)
    scenario=LineReallocationScenario(
      issuer=x.issuer, source_name=x.source_name, source_balance=x.source_balance, source_limit=x.source_limit,
      target_name=x.target_name, target_balance=x.target_balance, target_limit=x.target_limit, amount=x.amount,
      minimum_source_limit=x.minimum_source_limit, policy_eligible=policy.get("policy_eligible"), policy_note=policy.get("note")
    )
    r=analyze_line_reallocation(scenario,target_high=cfg.target_high,user_max=cfg.user_max)
    r["policy_source"]=policy.get("source")
    return r


@app.post("/api/optimization/compare")
def optimization_compare(x: OptimizationCompareIn, user_id: int = Depends(current_user)):
    queue=rank_optimization_options(
      payment=x.payment, line_reallocation=x.line_reallocation, debt_transfer=x.debt_transfer, new_card=x.new_card
    )
    audit_event(user_id,"optimization.compared",{"options":len(queue)})
    return {
      "queue":queue,
      "next_best_option":queue[0] if queue else None,
      "disclosure":"La prioridad compara costo, urgencia y beneficio operativo; no predice puntos de score."
    }


@app.post("/api/optimization/card-recommendations")
def optimization_card_recommendations(x: CardRecommendationIn, user_id: int = Depends(current_user)):
    p=UserCardProfile(**x.model_dump(exclude={"candidates"}))
    candidates=[CardCandidate(**c.model_dump()) for c in x.candidates]
    ranked=rank_card_candidates(candidates,p)
    audit_event(user_id,"optimization.card_ranked",{"candidate_count":len(ranked)})
    return {
      "ranked":ranked,
      "application_sequence":["check_prequalification_if_available","verify_live_terms","compare_with_existing_cards","apply_on_official_issuer_site_if_selected"],
      "disclosure":"ICE Fit es compatibilidad estratégica, no probabilidad de aprobación. Las ofertas deben verificarse en vivo antes de aplicar."
    }


@app.post("/api/simulate")
def simulate(x: SimulationIn, user_id: int = Depends(current_user)):
    rows = card_rows_for(user_id)
    row = next((r for r in rows if r["account_id"] == x.account_id), None)
    if not row:
        raise HTTPException(404, "Credit card not found")
    return simulate_card(row_to_card(row), config_for(user_id), spend=x.spend, payment=x.payment)


def create_alert(user_id: int, payload: dict, channel: str = "in_app", status: str = "created") -> bool:
    stable = {k: payload.get(k) for k in ("source", "category", "account_id", "title", "due_date")}
    fingerprint = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:24]
    with db() as con:
        try:
            con.execute(
                "INSERT INTO alerts(user_id,fingerprint,payload,channel,status) VALUES(?,?,?,?,?)",
                (user_id, fingerprint, json.dumps(payload, default=str), channel, status),
            )
            return True
        except Exception as e:
            if "UNIQUE" in str(e):
                return False
            raise


@app.get("/api/alerts")
def get_alerts(user_id: int = Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "SELECT id,payload,channel,status,sent_at,read_at FROM alerts WHERE user_id=? ORDER BY sent_at DESC LIMIT 50",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["payload"] = json.loads(item["payload"])
        out.append(item)
    return {"alerts": out}


@app.post("/api/alerts/read")
def read_alert(x: AlertReadIn, user_id: int = Depends(current_user)):
    with db() as con:
        con.execute("UPDATE alerts SET read_at=CURRENT_TIMESTAMP,status='read' WHERE id=? AND user_id=?", (x.alert_id, user_id))
    return {"ok": True}


async def run_daily_alerts():
    with db() as con:
        users = con.execute(
            "SELECT u.id,u.email,COALESCE(p.email_notifications,1) AS email_notifications FROM users u LEFT JOIN preferences p ON p.user_id=u.id"
        ).fetchall()
    for u in users:
        try:
            await sync_user(u["id"], source="daily_alert")
            portfolio = dashboard_for(u["id"])
            candidates = portfolio.get("priority_queue", [])
            if not candidates:
                continue
            top = candidates[0]
            created = create_alert(u["id"], top, "in_app", "created")
            if not created:
                continue
            lines = ["ICE-800 detectó una acción prioritaria:", ""]
            for a in candidates[:5]:
                lines.append(f"• {a['title']}: {a['reason']}")
                amount = a.get("amount_to_pay") or a.get("amount_to_pay_across_cards")
                if amount:
                    lines.append(f"  Pago orientativo: ${amount:.2f}")
            if u["email_notifications"] and send_email(u["email"], "ICE-800: acción de crédito", "\n".join(lines)):
                create_alert(u["id"], top, "email", "sent")
        except Exception:
            log.exception("daily alert failed user=%s", u["id"])


async def run_all_syncs():
    with db() as con:
        users = [r["id"] for r in con.execute("SELECT id FROM users").fetchall()]
    for user_id in users:
        try:
            await sync_user(user_id, source="scheduled")
        except Exception:
            log.exception("scheduled sync failed user=%s", user_id)


@app.post("/api/jobs/sync-all")
async def cron_sync_all(x_cron_secret: str | None = Header(None)):
    if not settings.cron_secret or not x_cron_secret or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(401, "Invalid cron secret")
    await run_all_syncs()
    return {"ok": True}


@app.post("/api/jobs/alerts")
async def cron_alerts(x_cron_secret: str | None = Header(None)):
    if not settings.cron_secret or not x_cron_secret or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(401, "Invalid cron secret")
    await run_daily_alerts()
    return {"ok": True}


@app.get("/api/beta/status")
def beta_status(user_id: int = Depends(current_user)):
    return beta_status_for(user_id)


@app.post("/api/beta/feedback")
def beta_feedback(x: BetaFeedbackIn, user_id: int = Depends(current_user)):
    with db() as con:
        con.execute(
            "INSERT INTO beta_feedback(user_id,feedback_type,rating,message,page) VALUES(?,?,?,?,?)",
            (user_id, x.feedback_type, x.rating, x.message.strip(), x.page),
        )
    audit_event(user_id, "beta.feedback_submitted", {"type": x.feedback_type, "rating": x.rating, "page": x.page})
    return {"ok": True, "message": "Gracias. Tu feedback quedó registrado."}


@app.post("/api/beta/event")
def beta_event(x: BetaEventIn, user_id: int = Depends(current_user)):
    try:
        event_name = safe_event_name(x.event_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with db() as con:
        con.execute("INSERT INTO product_events(user_id,event_name,page) VALUES(?,?,?)", (user_id, event_name, x.page))
    return {"ok": True}


@app.get("/api/account/export")
def export_account(user_id: int = Depends(current_user)):
    with db() as con:
        user = con.execute("SELECT id,email,created_at FROM users WHERE id=?", (user_id,)).fetchone()
        accounts = [dict(r) for r in con.execute("SELECT account_id,name,type,subtype,mask,balance,available,credit_limit,updated_at FROM accounts WHERE user_id=?", (user_id,)).fetchall()]
        reports = [dict(r) for r in con.execute("SELECT provider,score_model,score,report_date,utilization,created_at FROM credit_reports WHERE user_id=?", (user_id,)).fetchall()]
        prefs = con.execute("SELECT * FROM preferences WHERE user_id=?", (user_id,)).fetchone()
        cons = [dict(r) for r in con.execute("SELECT consent_type,version,granted,created_at FROM consents WHERE user_id=?", (user_id,)).fetchall()]
        beta_profile = con.execute("SELECT cohort,joined_at,last_seen_at,onboarding_completed_at,strategy_reviewed_at FROM beta_profiles WHERE user_id=?", (user_id,)).fetchone()
        feedback = [dict(r) for r in con.execute("SELECT feedback_type,rating,message,page,created_at FROM beta_feedback WHERE user_id=?", (user_id,)).fetchall()]
        events = [dict(r) for r in con.execute("SELECT event_name,page,created_at FROM product_events WHERE user_id=?", (user_id,)).fetchall()]
    audit_event(user_id, "account.exported")
    return {"user": dict(user), "accounts": accounts, "credit_reports": reports, "preferences": dict(prefs) if prefs else {}, "consents": cons, "beta_profile": dict(beta_profile) if beta_profile else {}, "feedback": feedback, "product_events": events}


@app.delete("/api/account")
async def delete_account(user_id: int = Depends(current_user)):
    with db() as con:
        conns = con.execute("SELECT access_token_enc FROM connections WHERE user_id=?", (user_id,)).fetchall()
    for c in conns:
        try:
            await plaid_service.remove_item(decrypt_secret(c["access_token_enc"]))
        except Exception:
            pass
    audit_event(user_id, "account.deletion_requested")
    with db() as con:
        account_ids = [r["account_id"] for r in con.execute("SELECT account_id FROM accounts WHERE user_id=?", (user_id,)).fetchall()]
        for account_id in account_ids:
            con.execute("DELETE FROM liabilities WHERE account_id=?", (account_id,))
        con.execute("DELETE FROM users WHERE id=?", (user_id,))
    return JSONResponse({"ok": True, "deleted": True})
