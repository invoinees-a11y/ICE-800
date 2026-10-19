"""ICE-800 integrated financial strategy preview (v1).

Read-only calculations. No bank calls, credit-score prediction, underwriting,
transactions, database writes or implicit consent to financial actions.
This module intentionally keeps consumer and business cash flows separate.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DebtType = Literal[
    "credit_card", "mortgage", "student_loan", "auto_loan",
    "personal_loan", "business_credit", "medical_debt",
    "insurance_financing", "other",
]

TYPES = {
    "credit_card": "Tarjeta de crédito",
    "mortgage": "Hipoteca",
    "student_loan": "Préstamo estudiantil",
    "auto_loan": "Préstamo de vehículo",
    "personal_loan": "Préstamo personal",
    "business_credit": "Crédito comercial",
    "medical_debt": "Deuda médica",
    "insurance_financing": "Financiación de seguro",
    "other": "Otra obligación",
}


class DebtInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: DebtType
    balance: float = Field(ge=0, le=1_000_000_000)
    apr: float | None = Field(default=None, ge=0, le=100, description="APR porcentual anual; no fracción")
    minimum_payment: float = Field(default=0, ge=0, le=100_000_000)
    days_until_due: int | None = Field(default=None, ge=-365, le=365)
    past_due: bool = False
    federal_student: bool = False
    personal_guarantee: bool = False
    property_value: float | None = Field(default=None, gt=0, le=1_000_000_000)


class StrategyInput(BaseModel):
    monthly_income: float = Field(ge=0, le=1_000_000_000)
    essential_expenses: float = Field(ge=0, le=1_000_000_000, description="Excluye mínimos de deuda y primas de seguro")
    monthly_insurance_premiums: float = Field(default=0, ge=0, le=1_000_000_000)
    liquid_savings: float = Field(default=0, ge=0, le=1_000_000_000)
    reserve_months: int = Field(default=3, ge=1, le=12)
    monthly_business_revenue: float | None = Field(default=None, ge=0, le=1_000_000_000)
    business_operating_expenses: float | None = Field(default=None, ge=0, le=1_000_000_000)
    debts: list[DebtInput] = Field(default_factory=list, max_length=40)


def _dollar(value: float) -> float:
    return round(value + 1e-9, 2)


def _label(d: DebtInput) -> tuple[str, str]:
    # Neither collateral nor tax treatment alone makes a debt "good".
    if d.past_due or (d.days_until_due is not None and d.days_until_due < 0):
        return "alto_riesgo", "Hay pagos vencidos; proteger el historial y evitar consecuencias inmediatas es prioritario."
    if d.kind == "business_credit":
        return "condicional", "Evaluar retorno operativo, liquidez empresarial y garantía personal; no asumir que es deuda buena."
    if d.kind == "student_loan" and d.federal_student:
        return "condicional", "Revisar protecciones y planes federales antes de refinanciar o adelantar pagos."
    if d.kind == "mortgage":
        return "condicional", "Evaluar costo total, valor de la vivienda, liquidez y riesgo de ejecución hipotecaria."
    if d.kind == "insurance_financing":
        return "costo_financiero", "Es financiación de primas: revisar intereses y consecuencias de cancelar la cobertura."
    if d.apr is not None and d.apr >= 20:
        return "costo_alto", "La tasa es elevada; reducir intereses puede mejorar el flujo de caja si existe reserva suficiente."
    return "condicional", "La calidad de una deuda depende del costo, finalidad, términos, riesgos y capacidad de pago."


def _action(key: str, rank: int, title: str, explanation: str, scope: str = "personal", amount: float | None = None) -> dict:
    return {"code": key, "priority": rank, "title": title, "why": explanation,
            "scope": scope, "suggested_amount": _dollar(amount) if amount is not None else None}


def build_strategy(profile: StrategyInput) -> dict:
    personal = [d for d in profile.debts if d.kind != "business_credit" and d.balance > 0]
    business = [d for d in profile.debts if d.kind == "business_credit" and d.balance > 0]
    p_min = sum(d.minimum_payment for d in personal)
    b_min = sum(d.minimum_payment for d in business)
    personal_required = profile.essential_expenses + profile.monthly_insurance_premiums + p_min
    personal_free = profile.monthly_income - personal_required
    target = personal_required * profile.reserve_months
    reserve_gap = max(0.0, target - profile.liquid_savings)
    business_known = profile.monthly_business_revenue is not None and profile.business_operating_expenses is not None
    business_free = (profile.monthly_business_revenue - profile.business_operating_expenses - b_min) if business_known else None
    actions: list[dict] = []
    warnings: list[str] = []

    for d in personal + business:
        scope = "business" if d.kind == "business_credit" else "personal"
        if d.past_due or (d.days_until_due is not None and d.days_until_due < 0):
            actions.append(_action("past_due", 100, f"Atender pago vencido: {d.name}",
                         "Verifica el monto vencido real con el acreedor; no sustituye una confirmación del estado de cuenta.", scope))
        elif d.days_until_due is not None and d.days_until_due <= 7 and d.minimum_payment > 0:
            actions.append(_action("payment_due", 92, f"Preparar pago: {d.name}",
                          f"Vence en {d.days_until_due} días. Confirma fecha e importe con el proveedor.",scope,d.minimum_payment))
        if d.kind == "student_loan" and d.federal_student:
            actions.append(_action("federal_student_review", 58, f"Revisar beneficios federales: {d.name}",
                        "Antes de refinanciar o acelerar pagos, verificar programa, elegibilidad y protecciones vigentes."))
        if d.kind == "business_credit" and d.personal_guarantee:
            actions.append(_action("business_guarantee", 65, f"Revisar garantía personal: {d.name}",
                        "Una obligación comercial puede afectar patrimonio personal si existe garantía.", "business"))
        if d.kind == "mortgage" and d.property_value and d.balance > d.property_value:
            actions.append(_action("mortgage_equity", 70, f"Revisar patrimonio inmobiliario: {d.name}",
                        "La deuda declarada supera el valor estimado de la propiedad; confirma cifras y opciones antes de refinanciar."))
        if d.apr is None:
            warnings.append(f"Falta APR de {d.name}; no se puede calcular su costo financiero aproximado.")
        elif d.kind not in {"mortgage", "student_loan"} and d.minimum_payment > 0 and d.minimum_payment < d.balance * d.apr / 1200:
            warnings.append(f"El pago mínimo declarado para {d.name} es menor que el interés mensual aproximado; confirma las condiciones.")

    if personal_free < 0:
        actions.append(_action("budget_shortfall", 99, "Corregir déficit mensual",
                     "Los gastos esenciales, primas y mínimos declarados superan los ingresos; prioriza pagos esenciales y consulta opciones de asistencia antes de abonar extras."))
    elif personal_free == 0:
        actions.append(_action("no_surplus", 80, "No comprometer pagos adicionales",
                     "Los ingresos declarados solo cubren los pagos obligatorios y gastos esenciales."))

    if reserve_gap > 0:
        urgency = 88 if profile.liquid_savings < personal_required else 74
        actions.append(_action("emergency_reserve", urgency, "Fortalecer reserva de emergencia",
                     f"Objetivo ajustable: {profile.reserve_months} meses de obligaciones personales. Evita aplicar toda la liquidez a deudas mientras no exista un colchón adecuado.", amount=min(max(personal_free, 0.0), reserve_gap)))

    extra_eligible = [d for d in personal if d.apr is not None and d.apr > 0 and not d.past_due and (d.days_until_due is None or d.days_until_due >= 0)
                      and not (d.kind == "student_loan" and d.federal_student)]
    extra_eligible.sort(key=lambda d: d.apr or 0, reverse=True)
    available_extra = max(0.0, personal_free) if reserve_gap <= 0 and not any(d.past_due or (d.days_until_due is not None and d.days_until_due < 0) for d in personal) else 0.0
    if available_extra > 0 and extra_eligible:
        d = extra_eligible[0]
        proposal = min(available_extra, d.balance)
        actions.append(_action("extra_payment", 72, f"Simular abono adicional: {d.name}",
                     f"Es la APR más alta elegible ({d.apr:.2f}%). Estimación ilustrativa; no considera comisiones, deducibilidad fiscal, recargos ni otros beneficios contractuales.",amount=proposal))
    elif personal_free > 0 and reserve_gap > 0:
        warnings.append("El pago adicional se pospone en este escenario hasta cubrir la reserva indicada; cambia el objetivo de reserva si tus circunstancias lo justifican.")

    if business:
        if not business_known:
            warnings.append("Ingresa ingresos y gastos de la empresa para evaluar su crédito; los fondos personales no se asignan automáticamente a deuda comercial.")
        elif business_free is not None and business_free < 0:
            actions.append(_action("business_deficit", 96, "Corregir déficit empresarial",
                         "Los compromisos comerciales declarados exceden el flujo operativo estimado; revisar caja y acreedores.","business"))
        elif business_free is not None and business_free > 0:
            actions.append(_action("business_cashflow", 57, "Planificar excedente empresarial",
                         "Comparar capital de trabajo, impuestos, vencimientos y costo de financiación antes de adelantar pagos comerciales.","business"))

    if profile.monthly_insurance_premiums > 0:
        actions.append(_action("insurance_review", 45, "Revisar cobertura y primas",
                     "Comparar protección, deducibles y costo total; una prima ordinaria es gasto, no deuda, salvo que esté financiada."))

    if not profile.debts:
        warnings.append("No se han ingresado deudas: el resultado solo analiza liquidez y reserva.")
    if profile.monthly_income == 0:
        warnings.append("Ingreso mensual declarado en cero: las recomendaciones de pagos adicionales quedan limitadas.")

    reports = []
    for d in profile.debts:
        label, rationale = _label(d)
        reports.append({
            "name": d.name, "kind": d.kind, "category": TYPES[d.kind],
            "balance": _dollar(d.balance), "apr": d.apr,
            "monthly_interest_estimate": _dollar(d.balance * d.apr / 1200) if d.apr is not None else None,
            "minimum_payment": _dollar(d.minimum_payment),
            "scope": "business" if d.kind == "business_credit" else "personal",
            "classification": label, "classification_reason": rationale,
            "loan_to_value": round(d.balance / d.property_value, 4) if d.kind == "mortgage" and d.property_value else None,
        })
    actions.sort(key=lambda x: (-x["priority"], x["title"]))
    return {
        "engine": "ICE-800 Integrated Strategy Preview",
        "version": "1.0-preview",
        "as_of": date.today().isoformat(),
        "summary": {
            "personal_monthly_obligations": _dollar(personal_required),
            "personal_monthly_surplus": _dollar(personal_free),
            "business_monthly_surplus": _dollar(business_free) if business_free is not None else None,
            "personal_debt_total": _dollar(sum(d.balance for d in personal)),
            "business_debt_total": _dollar(sum(d.balance for d in business)),
            "reserve_goal": _dollar(target),
            "reserve_gap": _dollar(reserve_gap),
            "eligible_extra_payment_budget": _dollar(available_extra),
        },
        "debts": reports,
        "actions": actions,
        "warnings": warnings,
        "limitations": [
            "Vista de simulación: no ejecuta pagos ni solicita créditos.",
            "No predice puntajes, aprobaciones ni beneficios fiscales.",
            "APR y fechas introducidas manualmente no se verifican con prestamistas.",
            "Hipotecas, préstamos estudiantiles y crédito comercial pueden requerir reglas contractuales específicas.",
            "No clasifica una deuda como buena o mala solamente por su categoría.",
        ],
    }
