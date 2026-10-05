import os
import httpx
from config import settings

ENV = os.environ.get("PLAID_ENV", "sandbox").lower()
BASES = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}
BASE = BASES.get(ENV, BASES["sandbox"])
CLIENT_ID = os.environ.get("PLAID_CLIENT_ID", "")
SECRET = os.environ.get("PLAID_SECRET", "")


def _creds():
    if not CLIENT_ID or not SECRET:
        raise RuntimeError("Set PLAID_CLIENT_ID and PLAID_SECRET")
    return {"client_id": CLIENT_ID, "secret": SECRET}


async def post(path: str, payload: dict) -> dict:
    body = {**_creds(), **payload}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(BASE + path, json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("error_code"):
            raise RuntimeError(f"Plaid error {data['error_code']}: {data.get('error_message')}")
        return data


async def create_link_token(user_id: int, access_token: str | None = None, language: str = "en") -> str:
    payload = {
        "user": {"client_user_id": str(user_id)},
        "client_name": "ICE-800",
        "products": ["transactions"],
        "optional_products": ["liabilities"],
        "country_codes": ["US"],
        "language": language if language in {"en", "es"} else "en",
        "webhook": settings.plaid_webhook_url,
    }
    if settings.android_package_name:
        payload["android_package_name"] = settings.android_package_name
    elif settings.plaid_redirect_uri:
        payload["redirect_uri"] = settings.plaid_redirect_uri
    if access_token:
        payload["access_token"] = access_token
        payload.pop("products", None)
        payload.pop("optional_products", None)
    data = await post("/link/token/create", payload)
    return data["link_token"]


async def exchange_public_token(public_token: str) -> dict:
    return await post("/item/public_token/exchange", {"public_token": public_token})


async def accounts(access_token: str) -> list[dict]:
    data = await post("/accounts/get", {"access_token": access_token})
    return data.get("accounts", [])


async def liabilities(access_token: str) -> dict:
    try:
        data = await post("/liabilities/get", {"access_token": access_token})
        return data.get("liabilities") or {}
    except Exception:
        return {}


async def remove_item(access_token: str) -> None:
    await post("/item/remove", {"access_token": access_token})


async def transactions_sync(access_token: str, cursor: str | None = None, count: int = 500) -> dict:
    payload = {"access_token": access_token, "count": min(max(int(count), 1), 500)}
    if cursor:
        payload["cursor"] = cursor
    return await post("/transactions/sync", payload)


# ---- Production webhook verification ----
import hashlib
import hmac
import time
import jwt

_WEBHOOK_KEY_CACHE: dict[str, dict] = {}

async def _webhook_verification_key(key_id: str) -> dict:
    if key_id in _WEBHOOK_KEY_CACHE:
        return _WEBHOOK_KEY_CACHE[key_id]
    data = await post('/webhook_verification_key/get', {'key_id': key_id})
    key = data.get('key') or {}
    if key:
        _WEBHOOK_KEY_CACHE[key_id] = key
    return key

async def verify_webhook(raw_body: bytes, signed_jwt: str | None) -> bool:
    """Verify Plaid-Verification JWT + request body hash.

    Follows Plaid's ES256/JWK verification flow. Returns False on any error.
    """
    if not signed_jwt:
        return False
    try:
        header = jwt.get_unverified_header(signed_jwt)
        if header.get('alg') != 'ES256' or not header.get('kid'):
            return False
        key = await _webhook_verification_key(header['kid'])
        if not key:
            return False
        public_key = jwt.PyJWK.from_dict(key).key
        payload = jwt.decode(
            signed_jwt,
            key=public_key,
            algorithms=['ES256'],
            options={'require': ['iat', 'request_body_sha256']},
        )
        iat = int(payload.get('iat', 0))
        if abs(int(time.time()) - iat) > 300:
            return False
        actual = hashlib.sha256(raw_body).hexdigest()
        claimed = str(payload.get('request_body_sha256', ''))
        return hmac.compare_digest(actual, claimed)
    except Exception:
        return False
