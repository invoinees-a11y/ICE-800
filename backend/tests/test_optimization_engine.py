from optimization_engine import (
    DebtTransferScenario, LineReallocationScenario, CardCandidate, UserCardProfile,
    analyze_debt_transfer, analyze_line_reallocation, rank_card_candidates, rank_optimization_options
)


def test_balance_transfer_positive_savings():
    r = analyze_debt_transfer(DebtTransferScenario(
        source_name='Old Card', balance=4000, source_apr=.25,
        target_name='Promo Card', target_available_credit=5000,
        promo_apr=0, promo_months=15, transfer_fee_pct=.03,
    ))
    assert r['transferable_amount'] == 4000
    assert r['transfer_fee'] == 120
    assert r['monthly_payment_to_clear_before_promo_end'] > 0
    assert r['verdict'] == 'consider'
    assert r['estimated_net_savings'] > 0


def test_line_reallocation_keeps_global_utilization_same():
    r = analyze_line_reallocation(LineReallocationScenario(
        issuer='Example Bank', source_name='A', source_balance=300, source_limit=5000,
        target_name='B', target_balance=600, target_limit=1000, amount=2000,
        minimum_source_limit=500, policy_eligible=True,
    ), user_max=.10)
    assert r['verdict'] == 'consider'
    assert abs(r['global_utilization_before'] - r['global_utilization_after']) < 1e-9
    assert r['target']['utilization_after'] < r['target']['utilization_before']


def test_line_reallocation_rejects_if_donor_becomes_too_high():
    r = analyze_line_reallocation(LineReallocationScenario(
        issuer='Example Bank', source_name='A', source_balance=2500, source_limit=5000,
        target_name='B', target_balance=600, target_limit=1000, amount=2000,
        minimum_source_limit=500, policy_eligible=True,
    ), user_max=.10)
    assert r['verdict'] == 'not_recommended'


def test_card_ranking_prefers_prequal_low_overlap():
    p = UserCardProfile(prequalification_first=True, recent_hard_inquiries=1, recently_opened_accounts=1)
    candidates = [
        CardCandidate(name='A', issuer='X', prequalification_available=True, rewards_fit=.9, overlap=.1),
        CardCandidate(name='B', issuer='Y', prequalification_available=False, rewards_fit=.5, overlap=.8),
    ]
    r = rank_card_candidates(candidates, p)
    assert r[0]['name'] == 'A'
    assert r[0]['ice_fit_score'] > r[1]['ice_fit_score']


def test_option_queue_can_prioritize_payment_history():
    q = rank_optimization_options(
        payment={'protects_payment_history':True,'urgency':10,'cash_required':100,'utilization_improvement_pp':2},
        line_reallocation={'verdict':'consider','target':{'improvement_percentage_points':30}},
        new_card={'ice_fit_score':90,'annual_fee':0}
    )
    assert q[0]['type'] == 'payment'
