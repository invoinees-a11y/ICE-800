from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional


@dataclass
class CreditSnapshot:
    score: Optional[int] = None
    score_model: Optional[str] = None
    report_date: Optional[date] = None
    provider: Optional[str] = None
    utilization: Optional[float] = None
    hard_inquiries_6m: Optional[int] = None
    late_payments_24m: Optional[int] = None
    collections_count: Optional[int] = None
    derogatory_count: Optional[int] = None
    oldest_age_months: Optional[int] = None
    average_age_months: Optional[int] = None
    total_accounts: Optional[int] = None
    previous_score: Optional[int] = None


@dataclass
class CreditAction:
    severity: str
    priority: int
    factor: str
    title: str
    reason: str
    action: str
    score_prediction: None = None


def _severity(priority: int) -> str:
    if priority >= 90:
        return "critical"
    if priority >= 70:
        return "high"
    if priority >= 45:
        return "medium"
    return "info"


def _add(actions: list[CreditAction], priority: int, factor: str, title: str, reason: str, action: str) -> None:
    actions.append(CreditAction(_severity(priority), priority, factor, title, reason, action))


def analyze_credit(snapshot: Optional[CreditSnapshot], portfolio: Optional[dict] = None) -> dict:
    """Rules-based credit-factor diagnosis. Does not predict point changes."""
    if snapshot is None:
        return {
            "available": False,
            "score": None,
            "score_model": None,
            "report_date": None,
            "provider": None,
            "trend": None,
            "actions": [],
            "factor_health": [],
            "next_best_action": None,
            "disclaimer": "No hay reporte de crédito conectado/importado. ICE-800 puede seguir optimizando pagos y utilización con los datos de las tarjetas.",
        }

    actions: list[CreditAction] = []
    health: list[dict] = []

    late = snapshot.late_payments_24m
    if late is not None:
        if late > 0:
            _add(actions, 100, "payment_history", "Proteger historial de pagos",
                 f"El reporte registra {late} pago(s) tardío(s) en los últimos 24 meses.",
                 "Prioriza todos los vencimientos futuros; revisa el reporte y disputa únicamente información que sea inexacta.")
            health.append({"factor": "Historial de pagos", "status": "critical", "value": str(late) + " tardío(s)"})
        else:
            health.append({"factor": "Historial de pagos", "status": "good", "value": "Sin tardíos reportados en 24 meses"})

    collections = snapshot.collections_count
    derog = snapshot.derogatory_count
    if (collections or 0) + (derog or 0) > 0:
        n = (collections or 0) + (derog or 0)
        _add(actions, 95, "derogatory", "Revisar marcas negativas",
             f"Hay {n} registro(s) negativo(s) entre cobranzas/derogatorios.",
             "Verifica exactitud, estado, fechas y titularidad antes de decidir cualquier acción.")
        health.append({"factor": "Marcas negativas", "status": "critical", "value": str(n)})
    elif collections is not None or derog is not None:
        health.append({"factor": "Marcas negativas", "status": "good", "value": "0"})

    u = snapshot.utilization
    # Prefer live portfolio utilization when available because it can be newer than a bureau snapshot.
    if portfolio and portfolio.get("global_utilization") is not None:
        u = portfolio["global_utilization"]
    if u is not None:
        if u >= 0.30:
            p, st = 88, "critical"
            act = "Reduce balances antes de próximos cierres, sin comprometer liquidez ni pagos esenciales."
        elif u >= 0.10:
            p, st = 76, "high"
            act = "Baja primero las tarjetas más utilizadas hacia tu banda objetivo configurable."
        elif u > 0.07:
            p, st = 58, "medium"
            act = "Considera un prepago antes del cierre si la liquidez lo permite."
        else:
            p, st, act = 0, "good", "Mantén el control sin microgestionar pagos innecesarios."
        health.append({"factor": "Utilización", "status": st, "value": f"{u:.1%}"})
        if p:
            _add(actions, p, "utilization", "Optimizar utilización", f"La utilización observada es {u:.1%}.", act)

    inquiries = snapshot.hard_inquiries_6m
    if inquiries is not None:
        if inquiries >= 4:
            _add(actions, 72, "inquiries", "Pausar solicitudes innecesarias",
                 f"Hay {inquiries} consultas duras reportadas en 6 meses.",
                 "Evita nuevas solicitudes sin una razón financiera clara mientras envejecen las consultas recientes.")
            health.append({"factor": "Consultas recientes", "status": "high", "value": str(inquiries)})
        elif inquiries >= 2:
            _add(actions, 48, "inquiries", "Limitar nuevas solicitudes",
                 f"Hay {inquiries} consultas duras reportadas en 6 meses.",
                 "Solicita nuevo crédito solo si aporta un beneficio claro que compense la nueva consulta.")
            health.append({"factor": "Consultas recientes", "status": "medium", "value": str(inquiries)})
        else:
            health.append({"factor": "Consultas recientes", "status": "good", "value": str(inquiries)})

    avg_age = snapshot.average_age_months
    oldest = snapshot.oldest_age_months
    if avg_age is not None:
        if avg_age < 12:
            _add(actions, 38, "age", "Dejar madurar el historial",
                 f"La antigüedad media reportada es de aproximadamente {avg_age} meses.",
                 "Evita abrir/cerrar cuentas solo por perseguir el score; deja que el historial gane antigüedad.")
            status = "medium"
        elif avg_age < 36:
            status = "watch"
        else:
            status = "good"
        health.append({"factor": "Antigüedad media", "status": status, "value": f"{avg_age} meses"})
    if oldest is not None:
        health.append({"factor": "Cuenta más antigua", "status": "good" if oldest >= 24 else "watch", "value": f"{oldest} meses"})

    trend = None
    if snapshot.score is not None and snapshot.previous_score is not None:
        delta = snapshot.score - snapshot.previous_score
        trend = {"previous": snapshot.previous_score, "current": snapshot.score, "change": delta}
        if delta <= -20:
            _add(actions, 70, "score_trend", "Investigar caída del score",
                 f"El score bajó {abs(delta)} puntos entre los dos últimos snapshots disponibles.",
                 "Compara cambios en utilización, pagos, consultas y cuentas nuevas; no atribuyas la caída a una sola causa sin evidencia.")

    actions.sort(key=lambda a: a.priority, reverse=True)
    return {
        "available": True,
        "score": snapshot.score,
        "score_model": snapshot.score_model,
        "report_date": snapshot.report_date.isoformat() if snapshot.report_date else None,
        "provider": snapshot.provider,
        "trend": trend,
        "factor_health": health,
        "actions": [asdict(a) for a in actions],
        "next_best_action": asdict(actions[0]) if actions else None,
        "disclaimer": "ICE-800 no predice cambios exactos de puntaje. Los prestamistas pueden usar modelos, burós y criterios diferentes.",
    }


def merge_priorities(portfolio: dict, credit_analysis: dict) -> dict:
    """Return a single ordered action queue across card operations and bureau factors."""
    queue: list[dict] = []
    severity_rank = {"critical": 100, "high": 75, "medium": 50, "low": 25, "info": 10}

    if portfolio.get("global_action"):
        a = dict(portfolio["global_action"])
        a["source"] = "cards"
        a["priority"] = severity_rank.get(a.get("severity"), 40)
        queue.append(a)
    for a0 in portfolio.get("actions", []):
        a = dict(a0)
        a["source"] = "cards"
        # Payment history actions beat utilization at the same severity.
        bonus = 12 if a.get("category") == "payment_history" else 0
        a["priority"] = severity_rank.get(a.get("severity"), 40) + bonus
        queue.append(a)
    for a0 in credit_analysis.get("actions", []):
        a = dict(a0)
        a["source"] = "credit_report"
        queue.append(a)

    queue.sort(key=lambda a: a.get("priority", 0), reverse=True)
    return {"queue": queue, "next_best_action": queue[0] if queue else None}
