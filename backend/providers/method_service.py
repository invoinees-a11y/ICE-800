from __future__ import annotations

import os
from typing import Any
import httpx


class MethodError(RuntimeError):
    pass


ENV = os.getenv("METHOD_ENV", "dev").lower()
BASES = {
    "dev": "https://dev.methodfi.com",
    "production": "https://production.methodfi.com",
}
BASE = os.getenv("METHOD_BASE_URL", BASES.get(ENV, BASES["dev"])).rstrip("/")
API_KEY = os.getenv("METHOD_API_KEY", "")
API_VERSION = os.getenv("METHOD_VERSION", "2026-03-30")
OPAL_LAUNCH_URL = os.getenv("METHOD_OPAL_LAUNCH_URL", "")


def configured() -> bool:
    return bool(API_KEY)


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise MethodError("METHOD_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Method-Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def request(method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.request(method, BASE + path, headers=_headers(), json=payload)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    if r.status_code >= 400:
        raise MethodError(f"Method {r.status_code}: {body}")
    return body


async def create_entity(*, first_name: str, last_name: str, phone: str, email: str | None = None,
                        dob: str | None = None, address: dict | None = None) -> dict:
    individual: dict[str, Any] = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
    }
    if email:
        individual["email"] = email
    if dob:
        individual["dob"] = dob
    payload: dict[str, Any] = {"type": "individual", "individual": individual}
    if address:
        payload["address"] = address
    return await request("POST", "/entities", payload)


async def retrieve_account(account_id: str) -> dict:
    return await request("GET", f"/accounts/{account_id}")


async def start_account_update(account_id: str) -> dict:
    # Current Method docs expose real-time account Updates; older integrations used /syncs.
    # Keep the path configurable so an approved Method team can select the contracted API version.
    update_path = os.getenv("METHOD_ACCOUNT_UPDATE_PATH", "/accounts/{account_id}/updates").format(account_id=account_id)
    return await request("POST", update_path, {})


async def list_account_transactions(account_id: str) -> dict:
    return await request("GET", f"/accounts/{account_id}/transactions")


async def create_payment(*, source_account_id: str, destination_account_id: str,
                         amount_cents: int, description: str) -> dict:
    if amount_cents <= 0:
        raise MethodError("Payment amount must be positive")
    payload = {
        "amount": amount_cents,
        "source": source_account_id,
        "destination": destination_account_id,
        "description": description[:64],
    }
    return await request("POST", "/payments", payload)


async def retrieve_payment(payment_id: str) -> dict:
    return await request("GET", f"/payments/{payment_id}")


def opal_launch_url() -> str | None:
    # Opal is an embedded/hosted product provisioned per Method partner. The exact launch URL is
    # supplied by Method after commercial onboarding, so it is configuration rather than guessed.
    return OPAL_LAUNCH_URL or None
