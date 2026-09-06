"""Operator-only BlackBox status routes.

These routes do not expose record contents. They let the operator confirm the
external BlackBox witness is alive and verify the hash chain from outside the
player menu surface.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from .blackbox_runtime import BlackBoxRuntimeWitness
from .route_security import require_role


def create_blackbox_router(witness: BlackBoxRuntimeWitness) -> APIRouter:
    router = APIRouter(prefix="/api/operator/blackbox", tags=["BlackBox Operator Boundary"])

    @router.get("/status")
    async def blackbox_status(identity: Dict[str, Any] = Depends(require_role("mod"))):
        actor = str(identity.get("user_id") or "operator")
        witness.access(actor=actor, access="status", scope=witness.session_id, reason="status_check")
        status = witness.status()
        return {
            "enabled": status.enabled,
            "session_id": status.session_id,
            "path": status.path,
            "next_seq": status.next_seq,
            "previous_hash": status.previous_hash,
            "compute_budget_percent": status.compute_budget_percent,
            "player_menu_exposed": False,
            "record_contents_exposed": False,
        }

    @router.get("/verify")
    async def blackbox_verify(identity: Dict[str, Any] = Depends(require_role("mod"))):
        actor = str(identity.get("user_id") or "operator")
        witness.access(actor=actor, access="verify", scope=witness.session_id, reason="hash_chain_verify")
        result = witness.verify()
        return {"ok": result.ok, "checked": result.checked, "errors": result.errors}

    return router


__all__ = ["create_blackbox_router"]
