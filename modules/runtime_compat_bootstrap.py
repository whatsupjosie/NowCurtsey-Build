"""
modules/runtime_compat_bootstrap.py — one-call mounting for compatibility routes.

This keeps main.py surgery tiny. main.py should only need to import
mount_runtime_compat_routes and call it after hub/cameras/recording,
performance_manager, and choreo_controller exist.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI

from modules.runtime_control_routes import create_runtime_control_router
from modules.stage_compat_routes import create_stage_compat_router

logger = logging.getLogger("pubcast.runtime_compat")


def mount_runtime_compat_routes(
    app: FastAPI,
    *,
    hub: Optional[Any] = None,
    cameras: Optional[Any] = None,
    recording: Optional[Any] = None,
    performance_manager: Optional[Any] = None,
    choreo_controller: Optional[Any] = None,
) -> None:
    """Mount the control-room/stage compatibility route surface.

    The routers are safe to mount even when optional subsystems are unavailable;
    they return explicit unavailable payloads instead of accidental 404s.
    """
    app.include_router(
        create_runtime_control_router(
            performance_manager=performance_manager,
            choreo_controller=choreo_controller,
        )
    )
    app.include_router(
        create_stage_compat_router(
            hub=hub,
            cameras=cameras,
            recording=recording,
        )
    )
    logger.info("Runtime compatibility routes mounted")


__all__ = ["mount_runtime_compat_routes"]
