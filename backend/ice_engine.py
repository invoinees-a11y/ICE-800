from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from datetime import date
from typing import Optional, Iterable
import calendar


@dataclass
class CardState:
    account_id: str
    name: str
    balance: float
    credit_limit: Optional[float]
    last_statement_issue_date: Optional[date] = None
    statement_balance: Optional[float] = None
    next_payment_due_date: Optional[date] = None
    minimum_payment: Optional[float] = None
    is_overdue: bool = False
    apr: Optional[float] = None


@dataclass
class StrategyConfig:
    target_low: float = 0.03
    target_high: float = 0.05
    warning: float = 0.07
    user_max: float = 0.10
    hard_warning: float = 0.30
    close_lead_days: int = 3
    due_lead_days: int = 5


@dataclass
class Action:
    severity: str
    account_id: Optional[str]
    title: str
    reason: str
    amount_to_pay: Optional[float] = None
    due_date: Optional[str] = None
    category: str = "strategy"


def _money(x: float) -> float:
    return round(max(0.0, x) + 1e-9, 2)


def utilization(balance: float, credit_limit: Optional[float]) -> Optional[float]:
    if credit_limit is None or credit_limit <= 0:
        return None
    return max(0.0, balance) / credit_limit


def next_monthly_anniversary(last_date: date, today: date) -> date:
    """Planning estimate only; the issuer's official date always wins."""
    day = last_date.day
    year, month = today.year, today.month
    last_day = calendar.monthrange(year, month)[1]
    candidate = date(year, month, min(day, last_day))
    if candidate >= today:
        return candidate
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def pay_to_target(balance: float, limit: float, target: float) -> float:
    return _money(balance - (limit * target))


def utilization_status(u: Optional[float], cfg: StrategyConfig) -> str:
    if u is None:
        return "unknown"
    if u <= cfg.target_high:
        return "target"
    if u <= cfg.warning:
        return "watch"
    if u < cfg.user_max:
        return "warning"
    if u < cfg.hard_warning:
        return "high"
    return "critical"


def _risk_rank(severity: str) -> int:
    return {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}.get(severity, 0)


def analyze_card(card: CardState, cfg: StrategyConfig, today: Optional[date] = None) -> dict:
    today = today or date.today()
    u = utilization(card.balance, card.credit_limit)
    estimated_close = next_monthly_anniversary(card.last_statement_issue_date, today) if card.last_statement_issue_date else None
    actions: list[Action] = []

    if card.is_overdue:
        actions.append(Action(
            severity="critical", account_id=card.account_id, title="Pago vencido",
            reason="La cuenta aparece vencida. Ponla al día antes de optimizar utilización.",
            amount_to_pay=card.minimum_payment,
            due_date=card.next_payment_due_date.isoformat() if card.next_payment_due_date else None,
            category="payment_history",
        ))

    if card.next_payment_due_date:
        days_due = (card.next_payment_due_date - today).days
        statement_due = max(0.0, card.statement_balance or 0.0)
        if 0 <= days_due <= cfg.due_lead_days and statement_due > 0:
            actions.append(Action(
                severity="critical" if days_due <= 1 else "high", account_id=card.account_id,
                title="Vencimiento próximo",
                reason=f"Faltan {days_due} días para la fecha límite. Protege primero el historial de pago.",
                amount_to_pay=_money(statement_due), due_date=card.next_payment_due_date.isoformat(),
                category="payment_history",
            ))

    if u is not None and card.credit_limit:
        if estimated_close:
            days_close = (estimated_close - today).days
            if 0 <= days_close <= cfg.close_lead_days and u > cfg.target_high:
                actions.append(Action(
                    severity="high" if u >= cfg.user_max else "medium", account_id=card.account_id,
                    title="Prepago antes del cierre",
                    reason=(f"El cierre estimado está a {days_close} días y la utilización es {u:.1%}. "
                            f"Si tu liquidez lo permite, bájala hacia {cfg.target_high:.0%}."),
                    amount_to_pay=pay_to_target(card.balance, card.credit_limit, cfg.target_high),
                    due_date=estimated_close.isoformat(), category="utilization",
                ))
        elif u > cfg.warning:
            actions.append(Action(
                severity="high" if u >= cfg.user_max else "medium", account_id=card.account_id,
                title="Modo cierre desconocido",
                reason=(f"No hay fecha de cierre disponible y la utilización es {u:.1%}. "
                        f"Mantén margen bajando hacia {cfg.target_high:.0%}."),
                amount_to_pay=pay_to_target(card.balance, card.credit_limit, cfg.target_high),
                category="utilization",
            ))

        if u >= cfg.hard_warning:
            actions.append(Action(
                severity="high", account_id=card.account_id, title="Utilización muy alta",
                reason=f"La tarjeta está en {u:.1%}. Reducirla mejora el margen operativo y evita depender de un cierre favorable.",
                amount_to_pay=pay_to_target(card.balance, card.credit_limit, cfg.user_max), category="utilization",
            ))

    limit = card.credit_limit or 0
    target_balance_low = _money(limit * cfg.target_low) if limit else None
    target_balance_high = _money(limit * cfg.target_high) if limit else None
    warning_balance = _money(limit * cfg.warning) if limit else None
    max_balance = _money(limit * cfg.user_max) if limit else None
    headroom_to_warning = _money((warning_balance or 0) - max(0.0, card.balance)) if limit else None
    headroom_to_max = _money((max_balance or 0) - max(0.0, card.balance)) if limit else None

    actions.sort(key=lambda x: _risk_rank(x.severity), reverse=True)
    return {
        "account_id": card.account_id,
        "name": card.name,
        "balance": round(card.balance, 2),
        "credit_limit": card.credit_limit,
        "utilization": round(u, 4) if u is not None else None,
        "status": utilization_status(u, cfg),
        "statement_balance": card.statement_balance,
        "last_statement_issue_date": card.last_statement_issue_date.isoformat() if card.last_statement_issue_date else None,
        "estimated_next_close": estimated_close.isoformat() if estimated_close else None,
        "next_payment_due_date": card.next_payment_due_date.isoformat() if card.next_payment_due_date else None,
        "minimum_payment": card.minimum_payment,
        "apr": card.apr,
        "target_balance_low": target_balance_low,
        "target_balance_high": target_balance_high,
        "warning_balance": warning_balance,
        "max_operating_balance": max_balance,
        "headroom_to_warning": headroom_to_warning,
        "headroom_to_max": headroom_to_max,
        "actions": [asdict(a) for a in actions],
    }


def calendar_events(card_analyses: list[dict], today: date) -> list[dict]:
    events: list[dict] = []
    for c in card_analyses:
        if c.get("estimated_next_close"):
            events.append({
                "date": c["estimated_next_close"], "kind": "close", "account_id": c["account_id"],
                "card": c["name"], "title": "Cierre estimado", "is_estimate": True,
            })
        if c.get("next_payment_due_date"):
            events.append({
                "date": c["next_payment_due_date"], "kind": "due", "account_id": c["account_id"],
                "card": c["name"], "title": "Fecha límite de pago", "is_estimate": False,
            })
    events.sort(key=lambda e: (e["date"], 0 if e["kind"] == "due" else 1))
    for e in events:
        e["days_away"] = (date.fromisoformat(e["date"]) - today).days
    return events


def analyze_portfolio(cards: Iterable[CardState], cfg: StrategyConfig, today: Optional[date] = None) -> dict:
    today = today or date.today()
    cards = list(cards)
    analyses = [analyze_card(c, cfg, today) for c in cards]

    known = [c for c in cards if c.credit_limit and c.credit_limit > 0]
    total_limit = sum(c.credit_limit or 0 for c in known)
    total_balance = sum(max(0.0, c.balance) for c in known)
    global_util = (total_balance / total_limit) if total_limit else None

    actions = [a for x in analyses for a in x["actions"]]
    actions.sort(key=lambda a: _risk_rank(a["severity"]), reverse=True)

    global_action = None
    if global_util is not None and global_util > cfg.warning:
        global_action = {
            "severity": "high" if global_util >= cfg.user_max else "medium",
            "title": "Reducir utilización total",
            "reason": f"La utilización global es {global_util:.1%}; objetivo operativo {cfg.target_low:.0%}–{cfg.target_high:.0%}.",
            "amount_to_pay_across_cards": _money(total_balance - total_limit * cfg.target_high),
            "category": "utilization",
        }

    target_total_high = _money(total_limit * cfg.target_high) if total_limit else 0
    warning_total = _money(total_limit * cfg.warning) if total_limit else 0
    max_total = _money(total_limit * cfg.user_max) if total_limit else 0

    events = calendar_events(analyses, today)
    next_action = actions[0] if actions else global_action
    risk_level = "critical" if any(a["severity"] == "critical" for a in actions) else \
                 "high" if any(a["severity"] == "high" for a in actions) else \
                 "medium" if actions or global_action else "stable"

    return {
        "as_of": today.isoformat(),
        "total_balance": round(total_balance, 2),
        "total_limit": round(total_limit, 2),
        "global_utilization": round(global_util, 4) if global_util is not None else None,
        "global_status": utilization_status(global_util, cfg),
        "risk_level": risk_level,
        "target_band": [cfg.target_low, cfg.target_high],
        "warning": cfg.warning,
        "user_max": cfg.user_max,
        "target_total_high": target_total_high,
        "warning_total": warning_total,
        "max_operating_total": max_total,
        "global_headroom_to_warning": _money(warning_total - total_balance) if total_limit else None,
        "global_headroom_to_max": _money(max_total - total_balance) if total_limit else None,
        "global_action": global_action,
        "next_best_action": next_action,
        "cards": analyses,
        "actions": actions,
        "calendar": events,
        "principles": [
            "Pagar siempre a tiempo tiene prioridad sobre optimizar utilización.",
            "No es necesario mantener deuda ni pagar intereses para construir crédito.",
            "Las fechas estimadas de cierre son de planificación; el dato oficial del emisor prevalece.",
            "ICE-800 no predice puntos exactos de score; optimiza variables controlables.",
        ],
    }


def simulate_card(card: CardState, cfg: StrategyConfig, spend: float = 0.0, payment: float = 0.0,
                  today: Optional[date] = None) -> dict:
    """Simulate a hypothetical card balance after a spend and/or payment."""
    new_balance = max(0.0, card.balance + max(0.0, spend) - max(0.0, payment))
    hypothetical = replace(card, balance=new_balance)
    before = analyze_card(card, cfg, today)
    after = analyze_card(hypothetical, cfg, today)
    return {
        "before": before,
        "after": after,
        "spend": round(max(0.0, spend), 2),
        "payment": round(max(0.0, payment), 2),
        "utilization_change": None if before["utilization"] is None else round((after["utilization"] or 0) - before["utilization"], 4),
        "note": "Escenario hipotético. No representa una predicción de cambio de puntaje de crédito.",
    }
