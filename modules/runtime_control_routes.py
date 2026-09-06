"""
modules/runtime_control_routes.py — lightweight runtime control compatibility API.

This router is intentionally thin and non-owning. It exposes the already-existing
PerformanceManager and ChoreoController through stable endpoints expected by the
panoramic/control-room UI. When a subsystem is unavailable, routes return an
explicit unavailable payload rather than accidental 404s.

It supports either direct manager injection or late lookup from app.state / the
loaded main module. That keeps main.py surgery optional and lets existing mounted
routers bridge the frontend safely while the full runtime is reconciled.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from modules.media_intake_routes import create_media_intake_router


async def _json_dict(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _unavailable(name: str) -> Dict[str, Any]:
    return {"status": "unavailable", "available": False, "subsystem": name}


def _runtime_from_main(name: str) -> Optional[Any]:
    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    if main_mod is None:
        return None
    value = getattr(main_mod, name, None)
    return value


def _main_lookup_enabled(app: Any) -> bool:
    return bool(getattr(app.state, "allow_main_runtime_lookup", False))

def _resolve_runtime(request: Request, injected: Optional[Any], name: str) -> Optional[Any]:
    if injected is not None:
        return injected
    state_value = getattr(request.app.state, name, None)
    if state_value is not None:
        return state_value
    if _main_lookup_enabled(request.app):
        return _runtime_from_main(name)
    return None


def create_runtime_control_router(
    *,
    performance_manager: Optional[Any] = None,
    choreo_controller: Optional[Any] = None,
) -> APIRouter:
    router = APIRouter(tags=["Runtime Control"])

    # Mounted here because production_routes already includes this compatibility
    # router. The media intake router is intentionally non-owning and stores
    # assets under data/media_intake unless a later full mount injects recording.
    router.include_router(create_media_intake_router())

    @router.get("/api/performance/status")
    async def performance_status(request: Request):
        manager = _resolve_runtime(request, performance_manager, "performance_manager")
        if manager is None:
            return _unavailable("performance_manager")
        status = manager.status() if hasattr(manager, "status") else {}
        if isinstance(status, dict):
            return {"status": "ok", "available": True, **status}
        return {"status": "ok", "available": True, "value": status}

    @router.post("/api/performance/profile")
    async def set_performance_profile(request: Request):
        manager = _resolve_runtime(request, performance_manager, "performance_manager")
        if manager is None:
            return _unavailable("performance_manager")
        body = await _json_dict(request)
        profile = str(body.get("profile") or "").strip().lower()
        if not profile:
            raise HTTPException(status_code=400, detail="profile is required")
        try:
            snapshot = manager.set_profile(profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "available": True, **snapshot}

    @router.get("/api/choreo/status")
    async def choreo_status(request: Request):
        controller = _resolve_runtime(request, choreo_controller, "choreo_controller")
        if controller is None:
            return _unavailable("choreo_controller")
        status = controller.status() if hasattr(controller, "status") else {}
        if isinstance(status, dict):
            return {"status": "ok", "available": True, **status}
        return {"status": "ok", "available": True, "value": status}

    @router.get("/api/choreo/actions")
    async def choreo_actions(request: Request):
        controller = _resolve_runtime(request, choreo_controller, "choreo_controller")
        if controller is None:
            return _unavailable("choreo_controller")
        actions = controller.list_actions() if hasattr(controller, "list_actions") else {}
        return {"status": "ok", "available": True, "actions": actions}

    @router.get("/api/choreo/constraints")
    async def get_choreo_constraints(request: Request):
        controller = _resolve_runtime(request, choreo_controller, "choreo_controller")
        if controller is None:
            return _unavailable("choreo_controller")
        constraints = controller.get_constraints() if hasattr(controller, "get_constraints") else {}
        return {"status": "ok", "available": True, "constraints": constraints}

    @router.post("/api/choreo/constraints")
    async def set_choreo_constraints(request: Request):
        controller = _resolve_runtime(request, choreo_controller, "choreo_controller")
        if controller is None:
            return _unavailable("choreo_controller")
        body = await _json_dict(request)
        patch = body.get("constraints", body)
        if not isinstance(patch, dict):
            raise HTTPException(status_code=400, detail="constraints must be an object")
        constraints = controller.set_constraints(patch)
        return {"status": "ok", "available": True, "constraints": constraints}

    @router.post("/api/choreo/cue")
    async def cue_choreo_action(request: Request):
        controller = _resolve_runtime(request, choreo_controller, "choreo_controller")
        if controller is None:
            return _unavailable("choreo_controller")
        body = await _json_dict(request)
        try:
            payload = await controller.cue_action(
                room=str(body.get("room") or "default"),
                avatar_id=str(body.get("avatar_id") or body.get("avatar") or "").strip(),
                action=str(body.get("action") or "").strip(),
                intensity=float(body.get("intensity", 1.0)),
                duration=body.get("duration"),
                props=body.get("props") if isinstance(body.get("props"), dict) else {},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "available": True, "cue": payload}

    return router


__all__ = ["create_runtime_control_router"]

