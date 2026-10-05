import asyncio
from credit_provider import MockProvider, DisabledProvider, CreditProviderError
from config import Settings


def test_mock_credit_provider_is_explicitly_test_only():
    p = MockProvider()
    data = asyncio.run(p.fetch_snapshot("u1"))
    assert p.configured() is True
    assert "TEST" in data["score_model"]
    assert data["provider"] == "Mock Bureau Adapter"


def test_disabled_credit_provider_rejects_fetch():
    p = DisabledProvider()
    try:
        asyncio.run(p.fetch_snapshot("u1"))
        assert False, "expected CreditProviderError"
    except CreditProviderError:
        pass


def test_settings_parse_origin_lists():
    s = Settings(allowed_origins_raw="https://a.test, https://b.test", trusted_hosts_raw="a.test,b.test")
    assert s.allowed_origins == ["https://a.test", "https://b.test"]
    assert s.trusted_hosts == ["a.test", "b.test"]
