from datetime import date
from credit_engine import CreditSnapshot, analyze_credit, merge_priorities


def test_late_payment_is_top_priority():
    s = CreditSnapshot(score=690, score_model="Example", report_date=date(2026,10,1), late_payments_24m=1,
                       utilization=.04, hard_inquiries_6m=1, collections_count=0, derogatory_count=0)
    x = analyze_credit(s, {"global_utilization": .04})
    assert x["next_best_action"]["factor"] == "payment_history"
    assert x["next_best_action"]["score_prediction"] is None


def test_live_utilization_can_override_report_snapshot():
    s = CreditSnapshot(utilization=.02, hard_inquiries_6m=0, late_payments_24m=0)
    x = analyze_credit(s, {"global_utilization": .32})
    util = next(a for a in x["actions"] if a["factor"] == "utilization")
    assert util["priority"] >= 80


def test_merge_payment_due_beats_medium_report_factor():
    portfolio = {"global_action": None, "actions":[{"severity":"high","category":"payment_history","title":"Vencimiento","reason":"x"}]}
    credit = {"actions":[{"severity":"medium","priority":48,"factor":"inquiries","title":"Consultas","reason":"x","action":"y"}]}
    x = merge_priorities(portfolio, credit)
    assert x["next_best_action"]["source"] == "cards"
