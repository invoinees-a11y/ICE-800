from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Iterable
import math


@dataclass
class DebtTransferScenario:
    source_name: str
    balance: float
    source_apr: float
    target_name: str
    target_available_credit: float
    promo_apr: float = 0.0
    promo_months: int = 12
    transfer_fee_pct: float = 0.03
    post_promo_apr: Optional[float] = None
    requested_transfer: Optional[float] = None


@dataclass
class LineReallocationScenario:
    issuer: str
    source_name: str
    source_balance: float
    source_limit: float
    target_name: str
    target_balance: float
    target_limit: float
    amount: float
    minimum_source_limit: float = 500.0
    policy_eligible: Optional[bool] = None
    policy_note: Optional[str] = None


@dataclass
class CardCandidate:
    name: str
    issuer: str
    annual_fee: float = 0.0
    intro_apr_months: int = 0
    balance_transfer_intro_months: int = 0
    prequalification_available: bool = False
    rewards_fit: float = 0.5          # 0..1, supplied by catalog/profile matcher
    overlap: float = 0.0              # 0..1 overlap with existing cards
    welcome_value: float = 0.0        # estimated first-year cash-equivalent value
    expected_yearly_rewards: float = 0.0
    application_url: Optional[str] = None
    prequal_url: Optional[str] = None
    source_url: Optional[str] = None
    terms_verified_on: Optional[str] = None


@dataclass
class UserCardProfile:
    carry_balance: bool = False
    needs_balance_transfer: bool = False
    recent_hard_inquiries: int = 0
    recently_opened_accounts: int = 0
    prefers_no_annual_fee: bool = True
    values_rewards: bool = True
    prequalification_first: bool = True


def _money(v: float) -> float:
    return round(max(0.0, float(v or 0.0)) + 1e-9, 2)


def _util(balance: float, limit: float) -> float:
    return max(0.0, balance) / limit if limit and limit > 0 else 0.0


def _amortized_interest(balance: float, apr: float, months: int, payment: float) -> float:
    """Deterministic payoff estimate. Returns interest paid over the requested horizon.

    It intentionally does not claim lender statement accuracy; compounding is modeled monthly.
    """
    if balance <= 0 or months <= 0:
        return 0.0
    monthly_rate = max(0.0, apr) / 12.0
    bal = balance
    interest = 0.0
    for _ in range(months):
        if bal <= 0:
            break
        charge = bal * monthly_rate
        interest += charge
        bal += charge
        bal -= min(max(0.0, payment), bal)
    return _money(interest)


def analyze_debt_transfer(s: DebtTransferScenario) -> dict:
    fee_rate = max(0.0, s.transfer_fee_pct)
    source_balance = max(0.0, s.balance)
    available = max(0.0, s.target_available_credit)
    requested = source_balance if s.requested_transfer is None else max(0.0, s.requested_transfer)
    max_by_credit = available / (1.0 + fee_rate) if fee_rate >= 0 else available
    transferable = min(source_balance, requested, max_by_credit)
    fee = transferable * fee_rate
    financed = transferable + fee

    months = max(1, int(s.promo_months or 1))
    monthly_to_clear = financed / months

    # Baseline is paying the same monthly amount toward the source debt over the promo horizon.
    baseline_interest = _amortized_interest(transferable, max(0.0, s.source_apr), months, monthly_to_clear)
    promo_interest = _amortized_interest(financed, max(0.0, s.promo_apr), months, monthly_to_clear)
    estimated_savings = baseline_interest - promo_interest - fee

    fully_transferable = transferable + 0.005 >= min(source_balance, requested)
    sensible = transferable > 0 and estimated_savings > 0 and monthly_to_clear > 0
    if transferable <= 0:
        verdict = "not_available"
        reason = "No hay crédito disponible suficiente para realizar una transferencia en este escenario."
    elif estimated_savings <= 0:
        verdict = "not_recommended"
        reason = "La comisión y/o APR promocional eliminan el ahorro estimado frente a mantener la deuda actual."
    else:
        verdict = "consider"
        reason = "El escenario muestra ahorro estimado positivo si puedes sostener el pago mensual calculado durante la promoción."

    return {
        "source_name": s.source_name,
        "target_name": s.target_name,
        "source_balance": _money(source_balance),
        "requested_transfer": _money(requested),
        "transferable_amount": _money(transferable),
        "transfer_fee": _money(fee),
        "amount_posted_to_target": _money(financed),
        "promo_months": months,
        "monthly_payment_to_clear_before_promo_end": _money(monthly_to_clear),
        "estimated_interest_if_kept": baseline_interest,
        "estimated_interest_during_promo": promo_interest,
        "estimated_net_savings": _money(estimated_savings) if estimated_savings >= 0 else round(estimated_savings, 2),
        "fully_transferable": fully_transferable,
        "verdict": verdict,
        "reason": reason,
        "post_promo_apr": s.post_promo_apr,
        "caveat": "Estimación de planificación; verifica comisión, monto elegible, APR y duración exacta de la oferta antes de transferir.",
    }


def analyze_line_reallocation(s: LineReallocationScenario, target_high: float = 0.05, user_max: float = 0.10) -> dict:
    amt = max(0.0, s.amount)
    source_available = max(0.0, s.source_limit - max(0.0, s.source_balance))
    max_transfer = max(0.0, s.source_limit - max(s.minimum_source_limit, s.source_balance))
    feasible_amount = min(amt, max_transfer, source_available)
    after_source_limit = s.source_limit - feasible_amount
    after_target_limit = s.target_limit + feasible_amount

    before_source_u = _util(s.source_balance, s.source_limit)
    before_target_u = _util(s.target_balance, s.target_limit)
    after_source_u = _util(s.source_balance, after_source_limit)
    after_target_u = _util(s.target_balance, after_target_limit)
    total_before_limit = s.source_limit + s.target_limit
    total_after_limit = after_source_limit + after_target_limit
    total_balance = max(0.0, s.source_balance) + max(0.0, s.target_balance)
    global_before = _util(total_balance, total_before_limit)
    global_after = _util(total_balance, total_after_limit)

    improvement_pp = (before_target_u - after_target_u) * 100
    donor_ok = after_source_u <= user_max
    policy_blocked = s.policy_eligible is False
    if policy_blocked:
        verdict = "not_available"
        reason = s.policy_note or "La política conocida del emisor no permite esta reasignación para el escenario."
    elif feasible_amount <= 0:
        verdict = "not_feasible"
        reason = "El límite donante no tiene margen suficiente respetando el mínimo operativo configurado."
    elif improvement_pp <= 0:
        verdict = "not_useful"
        reason = "Mover límite no mejora la utilización de la tarjeta objetivo."
    elif not donor_ok:
        verdict = "not_recommended"
        reason = f"La tarjeta donante quedaría en {after_source_u:.1%}, por encima del máximo operativo de {user_max:.0%}."
    else:
        verdict = "consider"
        reason = "Mejora la utilización individual de la tarjeta objetivo sin cambiar la utilización global total."

    return {
        "issuer": s.issuer,
        "requested_amount": _money(amt),
        "feasible_amount": _money(feasible_amount),
        "source": {
            "name": s.source_name,
            "balance": _money(s.source_balance),
            "limit_before": _money(s.source_limit),
            "limit_after": _money(after_source_limit),
            "utilization_before": round(before_source_u, 4),
            "utilization_after": round(after_source_u, 4),
        },
        "target": {
            "name": s.target_name,
            "balance": _money(s.target_balance),
            "limit_before": _money(s.target_limit),
            "limit_after": _money(after_target_limit),
            "utilization_before": round(before_target_u, 4),
            "utilization_after": round(after_target_u, 4),
            "improvement_percentage_points": round(improvement_pp, 2),
        },
        "global_utilization_before": round(global_before, 4),
        "global_utilization_after": round(global_after, 4),
        "global_limit_before": _money(total_before_limit),
        "global_limit_after": _money(total_after_limit),
        "policy_eligible": s.policy_eligible,
        "policy_note": s.policy_note,
        "verdict": verdict,
        "reason": reason,
        "target_high": target_high,
        "user_max": user_max,
        "caveat": "La elegibilidad final depende del emisor, producto, antigüedad y mínimos de línea; ICE-800 no ejecuta la transferencia.",
    }


def score_card_candidate(c: CardCandidate, p: UserCardProfile) -> dict:
    # 0-100 transparent score. It ranks fit; it is NOT an approval probability.
    score = 50.0
    breakdown = []

    if c.prequalification_available and p.prequalification_first:
        score += 12; breakdown.append(("prequalification", 12, "Existe una ruta previa de precalificación/soft check."))
    if p.prefers_no_annual_fee:
        delta = 10 if c.annual_fee <= 0 else -min(15, c.annual_fee / 20)
        score += delta; breakdown.append(("annual_fee", round(delta,1), "Ajuste por costo anual frente a la preferencia del usuario."))
    if p.values_rewards:
        delta = 20 * max(0.0, min(1.0, c.rewards_fit))
        score += delta; breakdown.append(("rewards_fit", round(delta,1), "Ajuste por compatibilidad de recompensas."))
    overlap_penalty = 16 * max(0.0, min(1.0, c.overlap))
    score -= overlap_penalty; breakdown.append(("overlap", round(-overlap_penalty,1), "Penalización por duplicar funciones de tarjetas existentes."))

    if p.needs_balance_transfer:
        delta = 16 if c.balance_transfer_intro_months >= 12 else (8 if c.balance_transfer_intro_months >= 6 else -8)
        score += delta; breakdown.append(("balance_transfer", delta, "Ajuste por utilidad para transferencia de saldo."))
    elif p.carry_balance:
        delta = 8 if c.intro_apr_months >= 12 else -5
        score += delta; breakdown.append(("intro_apr", delta, "Ajuste por mantener saldo y oferta introductoria."))

    if c.welcome_value > 0:
        delta = min(8.0, c.welcome_value / 75.0)
        score += delta; breakdown.append(("welcome_value", round(delta,1), "Valor inicial estimado, limitado para no dominar el ranking."))
    if c.expected_yearly_rewards > 0:
        delta = min(8.0, c.expected_yearly_rewards / 100.0)
        score += delta; breakdown.append(("ongoing_value", round(delta,1), "Valor recurrente estimado según el perfil."))

    inquiry_penalty = min(15.0, p.recent_hard_inquiries * 2.5)
    new_account_penalty = min(12.0, p.recently_opened_accounts * 3.0)
    score -= inquiry_penalty + new_account_penalty
    if inquiry_penalty: breakdown.append(("recent_inquiries", round(-inquiry_penalty,1), "Penalización conservadora por consultas recientes."))
    if new_account_penalty: breakdown.append(("recent_accounts", round(-new_account_penalty,1), "Penalización conservadora por aperturas recientes."))

    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 80: verdict = "strong_fit"
    elif score >= 65: verdict = "good_fit"
    elif score >= 50: verdict = "mixed_fit"
    else: verdict = "weak_fit"

    return {
        "name": c.name, "issuer": c.issuer, "ice_fit_score": score, "verdict": verdict,
        "annual_fee": _money(c.annual_fee), "intro_apr_months": c.intro_apr_months,
        "balance_transfer_intro_months": c.balance_transfer_intro_months,
        "prequalification_available": c.prequalification_available,
        "application_url": c.application_url, "prequal_url": c.prequal_url,
        "source_url": c.source_url, "terms_verified_on": c.terms_verified_on,
        "score_breakdown": [{"factor":a,"points":b,"reason":d} for a,b,d in breakdown],
        "disclosure": "ICE Fit mide compatibilidad estratégica, no probabilidad de aprobación ni cambio esperado de puntaje.",
    }


def rank_card_candidates(candidates: Iterable[CardCandidate], profile: UserCardProfile) -> list[dict]:
    ranked = [score_card_candidate(c, profile) for c in candidates]
    ranked.sort(key=lambda x: x["ice_fit_score"], reverse=True)
    return ranked


def rank_optimization_options(payment: dict | None = None,
                              line_reallocation: dict | None = None,
                              debt_transfer: dict | None = None,
                              new_card: dict | None = None) -> list[dict]:
    """Create one ordered decision queue across the available interventions.

    Scores are decision priorities, not score-point forecasts.
    """
    options = []
    if payment:
        urgency = float(payment.get("urgency", 0))
        cost = float(payment.get("cash_required", 0))
        benefit = float(payment.get("utilization_improvement_pp", 0))
        priority = 85 + min(15, urgency) if payment.get("protects_payment_history") else 45 + min(30, benefit)
        options.append({"type":"payment","priority":round(min(100,priority),1),"benefit":benefit,"cost":cost,"detail":payment})
    if line_reallocation and line_reallocation.get("verdict") == "consider":
        benefit = float(line_reallocation["target"].get("improvement_percentage_points",0))
        priority = 58 + min(25, benefit)
        options.append({"type":"credit_line_reallocation","priority":round(min(90,priority),1),"benefit":benefit,"cost":0,"detail":line_reallocation})
    if debt_transfer and debt_transfer.get("verdict") == "consider":
        savings = float(debt_transfer.get("estimated_net_savings",0))
        monthly = float(debt_transfer.get("monthly_payment_to_clear_before_promo_end",0))
        priority = 55 + min(30, max(0,savings)/20)
        options.append({"type":"balance_transfer","priority":round(min(88,priority),1),"benefit":savings,"cost":monthly,"detail":debt_transfer})
    if new_card and new_card.get("ice_fit_score",0) >= 65:
        priority = 35 + min(35, new_card["ice_fit_score"]*.35)
        options.append({"type":"new_card","priority":round(min(75,priority),1),"benefit":new_card["ice_fit_score"],"cost":new_card.get("annual_fee",0),"detail":new_card})
    options.sort(key=lambda x:x["priority"], reverse=True)
    for i,x in enumerate(options,1): x["rank"] = i
    return options
