from __future__ import annotations

import os
from typing import Any
import httpx


class EngineError(RuntimeError):
    pass


BASE = os.getenv("ENGINE_BASE_URL", "https://api.engine.tech").rstrip("/")
TOKEN = os.getenv("ENGINE_API_TOKEN", "")
PARTNER_PAGE_URL = os.getenv("ENGINE_PARTNER_PAGE_URL", "")


def configured() -> bool:
    return bool(TOKEN)


def _headers() -> dict[str, str]:
    if not TOKEN:
        raise EngineError("ENGINE_API_TOKEN is not configured")
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json", "Content-Type": "application/json"}


async def preview_credit_cards(*, zip_code: str | None = None, provided_credit_rating: str | None = None,
                               card_purpose: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, str] = {}
    if zip_code:
        params["zipCode"] = zip_code
    if provided_credit_rating:
        params["providedCreditRating"] = provided_credit_rating
    if card_purpose:
        params["cardPurposes"] = card_purpose
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(BASE + "/offerPreview/creditCardOffers", headers=_headers(), params=params)
    if r.status_code >= 400:
        raise EngineError(f"Engine {r.status_code}: {r.text}")
    data = r.json()
    return data if isinstance(data, list) else data.get("creditCardOffers", [])


async def create_card_prefill(payload: dict[str, Any]) -> dict[str, Any]:
    body = {"productTypes": ["credit_card"], **payload}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(BASE + "/originator/prefills", headers=_headers(), json=body)
    if r.status_code >= 400:
        raise EngineError(f"Engine {r.status_code}: {r.text}")
    return r.json()


def partner_page_url() -> str | None:
    return PARTNER_PAGE_URL or None
