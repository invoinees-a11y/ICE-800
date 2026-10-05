import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-in-production")
JWT_ISSUER = os.environ.get("JWT_ISSUER", "ice-800")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "ice-800-app")
JWT_TTL_MINUTES = int(os.environ.get("JWT_TTL_MINUTES", "60"))
PASSWORD_ITERATIONS = int(os.environ.get("PASSWORD_ITERATIONS", "310000"))
FERNET_KEY = os.environ.get("FERNET_KEY")
if not FERNET_KEY:
    # Development-only fallback. Production validation rejects this mode.
    FERNET_KEY = "Gm2xnkHRVI4tBReaOTl2WscmDa9fJIVmPvGpiYMXDkw="
fernet = Fernet(FERNET_KEY.encode())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = hashed.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64url_decode(salt_b64), int(iterations))
        return hmac.compare_digest(_b64url(digest), digest_b64)
    except Exception:
        return False


def make_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_TTL_MINUTES)).timestamp()),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64url(json.dumps(header,separators=(',',':')).encode())}.{_b64url(json.dumps(payload,separators=(',',':')).encode())}"
    sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def decode_token(token: str) -> int:
    try:
        h, p, s = token.split(".")
        signing_input = f"{h}.{p}"
        expected = _b64url(hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, s):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64url_decode(p))
        now = int(datetime.now(timezone.utc).timestamp())
        if int(payload.get("exp", 0)) < now:
            raise ValueError("Expired token")
        if payload.get("iss") != JWT_ISSUER or payload.get("aud") != JWT_AUDIENCE:
            raise ValueError("Invalid claims")
        return int(payload["sub"])
    except Exception as e:
        raise ValueError("Invalid token") from e


def encrypt_secret(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return fernet.decrypt(value.encode()).decode()
