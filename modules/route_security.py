"""
modules/route_security.py — lightweight request identity helpers for PubCast routes.

Purpose
-------
Provide a single place for request-level auth / role enforcement so route modules
can move toward real boundaries without each one re-implementing JWT parsing.

Behavior
--------
- If ``PUBCAST_ENFORCE_AUTH`` is falsey (default), routes remain usable without
  JWTs so local/dev workflows and existing tests do not instantly break.
- If a bearer token *is* provided, it is decoded and exposed to the route.
- If ``PUBCAST_ENFORCE_AUTH`` is truthy, missing / invalid tokens become 401s
  and insufficient role claims become 403s.
- Caller identity fields in request bodies should not be trusted over the
  authenticated/header identity; helpers below let routes bind actor fields to
  the actual caller.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from modules.auth import decode_access_token, role_gte

security = HTTPBearer(auto_error=False)


_TRUTHY = {"1", "true", "yes", "on"}


def auth_enforced() -> bool:
    return str(os.getenv("PUBCAST_ENFORCE_AUTH", "0")).strip().lower() in _TRUTHY


def _header_identity(request: Request) -> str:
    return str(request.headers.get("X-Client-Id", "anon") or "anon").strip() or "anon"


def _header_role(request: Request) -> str:
    """Dev-only: X-Dev-Role header allows role override when auth is not enforced."""
    from .chat_rooms import VALID_ROLES
    raw = str(request.headers.get("X-Dev-Role", "guest") or "guest").strip().lower()
    return raw if raw in VALID_ROLES else "guest"


async def current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Return a normalized identity object for the current request."""
    header_user = _header_identity(request)
    if credentials is None:
        if auth_enforced():
            raise HTTPException(401, "Authentication required")
        return {
            "user_id": header_user,
            "role": _header_role(request),
            "authenticated": False,
            "payload": None,
        }

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")

    user_id = str(payload.get("sub") or header_user or "anon").strip() or "anon"
    role = str(payload.get("role") or "guest").strip() or "guest"
    return {
        "user_id": user_id,
        "role": role,
        "authenticated": True,
        "payload": payload,
    }


def require_role(min_role: str):
    async def dependency(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> Dict[str, Any]:
        identity = await current_identity(request, credentials)
        if auth_enforced() and not role_gte(identity.get("role", "guest"), min_role):
            raise HTTPException(403, f"{min_role} role required")
        return identity

    return dependency


def bound_actor(
    *,
    request: Request,
    identity: Dict[str, Any],
    explicit_value: Any = None,
    field_name: str = "actor",
    allow_privileged_override: bool = True,
) -> str:
    """Bind an actor/body identity field to the real caller.

    In relaxed mode, explicit body identities still may not contradict the
    ``X-Client-Id`` header. In enforced mode, explicit identities may not
    contradict the authenticated token unless the caller has at least mod-level
    privileges and overrides are explicitly allowed.
    """
    explicit = str(explicit_value or "").strip()
    header_user = _header_identity(request)
    auth_user = str(identity.get("user_id") or header_user or "anon").strip() or "anon"
    caller_role = str(identity.get("role") or "guest")

    if explicit:
        if auth_enforced():
            if explicit != auth_user:
                if not (allow_privileged_override and role_gte(caller_role, "mod")):
                    raise HTTPException(403, f"{field_name} does not match authenticated caller")
        else:
            # Relaxed mode. _header_identity() returns the sentinel "anon" when
            # X-Client-Id is absent, so comparing it against an explicit body
            # identity rejected EVERY unauthenticated request — which defeats
            # the purpose of relaxed mode. Only enforce the match when a real
            # header was actually supplied.
            if header_user and header_user != "anon" and explicit != header_user:
                raise HTTPException(403, f"{field_name} must match X-Client-Id")
        return explicit

    if header_user and auth_enforced() and header_user != auth_user and not role_gte(caller_role, "mod"):
        raise HTTPException(403, f"X-Client-Id does not match authenticated caller")

    return auth_user if auth_enforced() else (header_user or auth_user)
