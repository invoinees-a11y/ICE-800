from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import date
import httpx


class CreditProviderError(RuntimeError):
    pass


class CreditProvider(ABC):
    name = "unconfigured"

    @abstractmethod
    async def fetch_snapshot(self, external_user_id: str) -> dict:
        raise NotImplementedError

    def configured(self) -> bool:
        return False


class DisabledProvider(CreditProvider):
    name = "disabled"

    async def fetch_snapshot(self, external_user_id: str) -> dict:
        raise CreditProviderError("No credit-report provider is configured.")


class MockProvider(CreditProvider):
    """Development-only deterministic provider used to exercise the integration boundary."""
    name = "mock"

    def configured(self) -> bool:
        return True

    async def fetch_snapshot(self, external_user_id: str) -> dict:
        return {
            "provider": "Mock Bureau Adapter",
            "score_model": "TEST MODEL — NOT A REAL CREDIT SCORE",
            "score": 700,
            "report_date": date.today().isoformat(),
            "utilization": None,
            "hard_inquiries_6m": None,
            "late_payments_24m": None,
            "collections_count": None,
            "derogatory_count": None,
            "oldest_age_months": None,
            "average_age_months": None,
            "total_accounts": None,
        }


class PartnerHTTPProvider(CreditProvider):
    """Generic contracted-provider adapter.

    ICE-800 deliberately does not hard-code a bureau's private/partner contract.
    Configure the endpoint and credentials only after the provider approves the use case.
    Expected response is normalized into ICE-800's CreditSnapshot fields.
    """
    name = "partner_http"

    def __init__(self):
        self.endpoint = os.getenv("CREDIT_PROVIDER_ENDPOINT", "")
        self.client_id = os.getenv("CREDIT_PROVIDER_CLIENT_ID", "")
        self.secret = os.getenv("CREDIT_PROVIDER_SECRET", "")

    def configured(self) -> bool:
        return bool(self.endpoint and self.client_id and self.secret)

    async def fetch_snapshot(self, external_user_id: str) -> dict:
        if not self.configured():
            raise CreditProviderError("Credit provider credentials/endpoint are incomplete.")
        headers = {
            "Authorization": f"Bearer {self.secret}",
            "X-Client-Id": self.client_id,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(self.endpoint, headers=headers, params={"external_user_id": external_user_id})
            r.raise_for_status()
            data = r.json()
        allowed = {
            "provider", "score_model", "score", "report_date", "utilization",
            "hard_inquiries_6m", "late_payments_24m", "collections_count",
            "derogatory_count", "oldest_age_months", "average_age_months", "total_accounts",
        }
        return {k: data.get(k) for k in allowed}


def get_credit_provider() -> CreditProvider:
    mode = os.getenv("CREDIT_PROVIDER", "disabled").lower()
    if mode == "mock":
        return MockProvider()
    if mode in {"partner", "partner_http", "http"}:
        return PartnerHTTPProvider()
    return DisabledProvider()
