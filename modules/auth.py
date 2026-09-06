# PubCast AI — auth.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/auth.py — JWT authentication and role-based access control.

Exports:
    create_access_token(data: dict) -> str
    decode_access_token(token: str) -> dict | None
    verify_password(plain: str, hashed: str) -> bool
    get_password_hash(plain: str) -> str
    role_gte(user_role: str, min_role: str) -> bool
    ROLE_ORDER: dict[str, int]
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from passlib.context import CryptContext
except Exception:  # pragma: no cover - minimal env fallback
    CryptContext = None

try:  # Prefer python-jose when available.
    from jose import JWTError as _JoseJWTError, jwt as _jose_jwt
except Exception:  # pragma: no cover - exercised implicitly in minimal envs
    _JoseJWTError = None
    _jose_jwt = None


class JWTError(Exception):
    pass


# ---------------------------------------------------------------------------
# Role hierarchy — higher number = more permissions
# ---------------------------------------------------------------------------
ROLE_ORDER: Dict[str, int] = {
    "guest": 0,
    "viewer": 1,
    "mod": 2,
    "admin": 3,
    "owner": 4,
}

# ---------------------------------------------------------------------------
# Config — pulled from env so secrets never live in source
# ---------------------------------------------------------------------------
_SECRET_KEY: str = os.environ.get("PUBCAST_JWT_SECRET", "change-me-in-production-please")
_ALGORITHM: str = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("PUBCAST_JWT_EXPIRE_MINUTES", "1440"))  # 24h default

if _SECRET_KEY == "change-me-in-production-please":
    logger.warning(
        "PUBCAST_JWT_SECRET is not set — using insecure default. "
        "Set PUBCAST_JWT_SECRET in your environment before going live."
    )

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
if CryptContext is not None:
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
else:  # pragma: no cover - exercised in lean container environments
    _pwd_context = None


def _fallback_password_hash(plain: str, *, salt: str | None = None, iterations: int = 200_000) -> str:
    salt = salt or base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), iterations)
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${salt}${iterations}${digest_b64}"


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain-text password matches the stored hash."""
    try:
        if _pwd_context is not None:
            return _pwd_context.verify(plain, hashed)
        if hashed.startswith("pbkdf2_sha256$"):
            _, salt, iteration_s, expected = hashed.split("$", 3)
            candidate = _fallback_password_hash(plain, salt=salt, iterations=int(iteration_s))
            return hmac.compare_digest(candidate, hashed)
        logger.warning("Password verification unavailable for hash format without passlib")
        return False
    except Exception as exc:
        logger.warning("Password verification error: %s", exc)
        return False


def get_password_hash(plain: str) -> str:
    """Return a password hash of the given plain-text password."""
    if _pwd_context is not None:
        return _pwd_context.hash(plain)
    return _fallback_password_hash(plain)


# ---------------------------------------------------------------------------
# Minimal HS256 fallback (used only if python-jose is unavailable)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = '=' * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _fallback_jwt_encode(payload: Dict[str, Any], secret: str) -> str:
    header = {"alg": _ALGORITHM, "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def _fallback_jwt_decode(token: str, secret: str) -> Dict[str, Any]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".", 2)
    except ValueError as exc:
        raise JWTError("Malformed token") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected, actual):
        raise JWTError("Invalid signature")
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise JWTError("Invalid payload") from exc
    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_ts = int(exp)
        except Exception as exc:
            raise JWTError("Invalid exp claim") from exc
        if datetime.now(timezone.utc).timestamp() >= exp_ts:
            raise JWTError("Token expired")
    return payload


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(data: Dict[str, Any], *, expires_minutes: Optional[int] = None) -> str:
    """Encode ``data`` into a signed JWT."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else _ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode["exp"] = int(expire.timestamp())
    if _jose_jwt is not None:
        return _jose_jwt.encode(to_encode, _SECRET_KEY, algorithm=_ALGORITHM)
    return _fallback_jwt_encode(to_encode, _SECRET_KEY)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT. Returns payload dict or None on failure."""
    if not token:
        return None
    try:
        if _jose_jwt is not None:
            return _jose_jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        return _fallback_jwt_decode(token, _SECRET_KEY)
    except ((_JoseJWTError or JWTError), JWTError) as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None
    except Exception as exc:
        logger.debug("JWT decode failed unexpectedly: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------

def role_gte(user_role: str, min_role: str) -> bool:
    """Return True if ``user_role`` has at least ``min_role`` privileges."""
    user_level = ROLE_ORDER.get(user_role, -1)
    min_level = ROLE_ORDER.get(min_role, 999)
    return user_level >= min_level
