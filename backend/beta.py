from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Iterable

BETA_VERSION = "Beta 2 · Optimization"
RELEASE_CHANNEL = "closed_beta"
ALLOWED_EVENT_NAMES = {
    "app_opened",
    "account_connected",
    "dashboard_viewed",
    "simulation_run",
    "strategy_saved",
    "credit_sync_requested",
    "feedback_opened",
    "card_candidates_ranked",
    "optimizer_viewed",
}


def normalize_invite_codes(raw: str) -> tuple[str, ...]:
    return tuple(sorted({x.strip() for x in (raw or "").split(",") if x.strip()}))


def invite_code_valid(candidate: str | None, allowed_codes: Iterable[str], required: bool = True) -> bool:
    codes = tuple(allowed_codes)
    if not required:
        return True
    if not candidate or not codes:
        return False
    return any(hmac.compare_digest(candidate.strip(), c) for c in codes)


def invite_code_fingerprint(code: str | None) -> str | None:
    if not code:
        return None
    return hashlib.sha256(code.strip().encode()).hexdigest()[:16]


def onboarding_steps(*, accepted_terms: bool, accepted_privacy: bool, has_connection: bool,
                     has_credit_report: bool, strategy_customized: bool) -> list[dict]:
    return [
        {"id": "legal", "label": "Aceptar términos y privacidad", "complete": accepted_terms and accepted_privacy},
        {"id": "connect", "label": "Vincular al menos una institución", "complete": has_connection},
        {"id": "strategy", "label": "Revisar la estrategia ICE-800", "complete": strategy_customized},
        {"id": "credit", "label": "Autorizar/sincronizar reporte de crédito", "complete": has_credit_report},
    ]


def completion_percent(steps: list[dict]) -> int:
    if not steps:
        return 0
    return round(100 * sum(1 for s in steps if s.get("complete")) / len(steps))


def safe_event_name(name: str) -> str:
    if name not in ALLOWED_EVENT_NAMES:
        raise ValueError("Unsupported beta event")
    return name
