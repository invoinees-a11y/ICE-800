from __future__ import annotations

import base64
import os
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from config import settings
from db import db


def _frontend_api() -> str:
    key = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
    if not key:
        raise RuntimeError("CLERK_PUBLISHABLE_KEY is not configured")
    try:
        encoded = key.split("_", 2)[2]
        encoded += "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode().rstrip("$")
    except Exception as exc:
        raise RuntimeError("Invalid CLERK_PUBLISHABLE_KEY") from exc
    return f"https://{decoded}".rstrip("/")


def _jwks_url() -> str:
    return f"{_frontend_api()}/.well-known/jwks.json"


_jwks_client: PyJWKClient | None = None


def _verify_token(token: str) -> dict[str, Any]:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_jwks_url())
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
            leeway=5,
        )
    except Exception as exc:
        raise HTTPException(401, "Invalid or expired Clerk session") from exc

    expected_issuer = _frontend_api().rstrip("/")
    issuer = str(claims.get("iss") or "").rstrip("/")
    if issuer and issuer != expected_issuer:
        raise HTTPException(401, "Invalid Clerk token issuer")

    azp = claims.get("azp")
    permitted = {settings.public_base_url.rstrip("/")}
    if settings.app_env != "production":
        permitted.update({"http://localhost:8000", "http://127.0.0.1:8000"})
    if azp and str(azp).rstrip("/") not in permitted:
        raise HTTPException(401, "Invalid Clerk authorized party")

    if claims.get("sts") == "pending":
        raise HTTPException(403, "Authentication setup is incomplete")

    if not claims.get("sub"):
        raise HTTPException(401, "Clerk user is missing")
    return claims


def _fetch_clerk_user(clerk_user_id: str) -> dict[str, Any]:
    secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(503, "Clerk backend authentication is not configured")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
            )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise HTTPException(503, "Unable to resolve Clerk user") from exc


def _verified_primary_email(user: dict[str, Any]) -> str:
    primary_id = user.get("primary_email_address_id")
    addresses = user.get("email_addresses") or []
    selected = next((x for x in addresses if x.get("id") == primary_id), None)
    if not selected and addresses:
        selected = addresses[0]
    if not selected or not selected.get("email_address"):
        raise HTTPException(403, "A verified email address is required")
    verification = selected.get("verification") or {}
    if verification.get("status") != "verified":
        raise HTTPException(403, "Email verification is required")
    return str(selected["email_address"]).strip().lower()


def _ensure_identity_table(con) -> None:
    con.execute(
        '''
        CREATE TABLE IF NOT EXISTS clerk_identities (
          clerk_user_id TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL UNIQUE,
          email TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )


def _resolve_local_user(clerk_user_id: str) -> int:
    with db() as con:
        _ensure_identity_table(con)
        row = con.execute(
            "SELECT user_id FROM clerk_identities WHERE clerk_user_id=?",
            (clerk_user_id,),
        ).fetchone()
        if row:
            con.execute(
                "UPDATE clerk_identities SET last_seen_at=CURRENT_TIMESTAMP WHERE clerk_user_id=?",
                (clerk_user_id,),
            )
            return int(row["user_id"])

    user = _fetch_clerk_user(clerk_user_id)
    email = _verified_primary_email(user)

    with db() as con:
        _ensure_identity_table(con)
        row = con.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
        if not row:
            raise HTTPException(
                403,
                "This verified email is not provisioned in ICE-800. Use the same email as your existing pilot account.",
            )

        user_id = int(row["id"])
        conflict = con.execute(
            "SELECT clerk_user_id FROM clerk_identities WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if conflict and conflict["clerk_user_id"] != clerk_user_id:
            raise HTTPException(409, "ICE-800 account is already linked to another Clerk identity")

        con.execute(
            '''
            INSERT INTO clerk_identities(clerk_user_id,user_id,email,last_seen_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(clerk_user_id) DO UPDATE SET
              email=excluded.email,
              last_seen_at=CURRENT_TIMESTAMP
            ''',
            (clerk_user_id, user_id, email),
        )
        con.execute(
            "UPDATE beta_profiles SET last_seen_at=CURRENT_TIMESTAMP WHERE user_id=?",
            (user_id,),
        )
    return user_id


def current_user(authorization: str | None = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Clerk bearer token")
    claims = _verify_token(authorization.split(" ", 1)[1])
    return _resolve_local_user(str(claims["sub"]))


def strict_mfa_user(authorization: str | None = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Clerk bearer token")
    claims = _verify_token(authorization.split(" ", 1)[1])
    fva = claims.get("fva")
    if not isinstance(fva, (list, tuple)) or len(fva) < 2:
        raise HTTPException(403, "Recent multi-factor verification is required for this sensitive action.")
    try:
        first_age = int(fva[0])
        second_age = int(fva[1])
    except (TypeError, ValueError):
        raise HTTPException(403, "Recent multi-factor verification is required for this sensitive action.")
    if first_age < 0 or second_age < 0 or first_age > 5 or second_age > 5:
        raise HTTPException(
            403,
            "Security check required: sign out and sign in again with MFA before this sensitive action.",
        )
    return _resolve_local_user(str(claims["sub"]))



def strict_mfa_context(authorization: str | None = Header(None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Clerk bearer token")

    claims = _verify_token(authorization.split(" ", 1)[1])
    fva = claims.get("fva")
    if not isinstance(fva, (list, tuple)) or len(fva) < 2:
        raise HTTPException(
            403,
            "Recent multi-factor verification is required for this sensitive action.",
        )

    try:
        first_age = int(fva[0])
        second_age = int(fva[1])
    except (TypeError, ValueError):
        raise HTTPException(
            403,
            "Recent multi-factor verification is required for this sensitive action.",
        )

    if first_age < 0 or second_age < 0 or first_age > 5 or second_age > 5:
        raise HTTPException(
            403,
            "Security check required: sign out and sign in again with MFA before this sensitive action.",
        )

    session_id = str(claims.get("sid") or "").strip()
    clerk_user_id = str(claims.get("sub") or "").strip()
    if not session_id or not clerk_user_id:
        raise HTTPException(401, "Clerk session context is incomplete")

    return {
        "user_id": _resolve_local_user(clerk_user_id),
        "clerk_user_id": clerk_user_id,
        "session_id": session_id,
    }


def revoke_other_clerk_sessions(clerk_user_id: str, current_session_id: str) -> int:
    secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(503, "Clerk backend authentication is not configured")

    headers = {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                "https://api.clerk.com/v1/sessions",
                params={
                    "user_id": clerk_user_id,
                    "status": "active",
                    "limit": 100,
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                sessions = payload
            elif isinstance(payload, dict):
                sessions = payload.get("data") or []
            else:
                sessions = []

            revoked = 0
            for session in sessions:
                session_id = str((session or {}).get("id") or "").strip()
                if not session_id or session_id == current_session_id:
                    continue

                revoke = client.post(
                    f"https://api.clerk.com/v1/sessions/{session_id}/revoke",
                    headers=headers,
                )
                revoke.raise_for_status()
                revoked += 1

            return revoked
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502,
            "Clerk rejected the session revocation request.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            503,
            "Unable to reach Clerk to revoke other sessions.",
        ) from exc

def public_config() -> dict[str, Any]:
    return {
        "auth_provider": "clerk",
        "clerk_publishable_key": os.getenv("CLERK_PUBLISHABLE_KEY", ""),
        "mfa_required": True,
    }
