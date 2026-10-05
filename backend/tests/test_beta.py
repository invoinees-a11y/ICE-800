from beta import completion_percent, invite_code_fingerprint, invite_code_valid, normalize_invite_codes, onboarding_steps, safe_event_name


def test_invite_codes():
    codes = normalize_invite_codes("A, B,A")
    assert codes == ("A", "B")
    assert invite_code_valid("A", codes, True)
    assert not invite_code_valid("C", codes, True)
    assert invite_code_valid(None, (), False)
    assert invite_code_fingerprint("A") == invite_code_fingerprint("A")


def test_onboarding_completion():
    steps = onboarding_steps(accepted_terms=True, accepted_privacy=True, has_connection=True, has_credit_report=False, strategy_customized=True)
    assert completion_percent(steps) == 75
    assert completion_percent(onboarding_steps(accepted_terms=True, accepted_privacy=True, has_connection=True, has_credit_report=True, strategy_customized=True)) == 100


def test_event_allowlist():
    assert safe_event_name("app_opened") == "app_opened"
    try:
        safe_event_name("card_balance_1234")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown event should be rejected")
