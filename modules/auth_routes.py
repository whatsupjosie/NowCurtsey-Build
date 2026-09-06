# PubCast AI — auth_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Authentication API Routes
JWT-based authentication system
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from modules import userdb

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()


class LoginRequest(BaseModel):
    """Login credentials."""
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=4096)


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


_auth_module = None


def set_auth_instance(auth_module):
    """Set global auth module (called from main.py)."""
    global _auth_module
    _auth_module = auth_module


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Authenticate against the user database and issue a JWT."""
    if not _auth_module:
        raise HTTPException(503, "Auth system not initialized")

    user = await userdb.get_user(request.username)
    if not user or not _auth_module.verify_password(request.password, user.get("hashed_password", "")):
        raise HTTPException(401, "Authentication failed")

    token = _auth_module.create_access_token({
        "sub": request.username,
        "role": user.get("role", "guest"),
    })
    return TokenResponse(access_token=token)


@router.get("/verify")
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify a JWT token."""
    if not _auth_module:
        raise HTTPException(503, "Auth system not initialized")

    payload = _auth_module.decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Token invalid")
    return {"valid": True, "payload": payload}
