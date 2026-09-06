# PubCast AI — performance_manager.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
Performance profile policy manager for PubCast.

Profiles are loaded from system_policy.json and persisted by profile name to:
    data/global/performance_profile.json
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .persistence import read_json, write_json


DEFAULT_PROFILE = "medium"
DEFAULT_POLICY: Dict[str, Any] = {
    "version": 1,
    "default_profile": DEFAULT_PROFILE,
    "profiles": {
        "low": {
            "description": "Maximum stability for weak hardware or heavy load.",
            "stage_target_fps": 20,
            "choreo_tick_hz": 20,
            "stage_static_fx": True,
            "architect_enabled": False,
            "architect_max_concurrency": 1,
            "architect_timeout_s": 6,
            "breaker_threshold": 2,
            "breaker_cooldown_s": 30,
            "studio_model": "ministral-pubcast:3b",
        },
        "medium": {
            "description": "Balanced default for daily production.",
            "stage_target_fps": 35,
            "choreo_tick_hz": 30,
            "stage_static_fx": False,
            "architect_enabled": True,
            "architect_max_concurrency": 1,
            "architect_timeout_s": 12,
            "breaker_threshold": 3,
            "breaker_cooldown_s": 60,
            "studio_model": "ministral-pubcast:3b",
        },
        "high": {
            "description": "Higher visual smoothness where client hardware can handle it.",
            "stage_target_fps": 60,
            "choreo_tick_hz": 45,
            "stage_static_fx": False,
            "architect_enabled": True,
            "architect_max_concurrency": 1,
            "architect_timeout_s": 16,
            "breaker_threshold": 5,
            "breaker_cooldown_s": 120,
            "studio_model": "ministral-pubcast:3b",
        },
    },
}


class PerformanceManager:
    def __init__(self, policy_path: Path, state_path: Path) -> None:
        self.policy_path = policy_path
        self.state_path = state_path
        self._lock = threading.Lock()
        self.policy = self._load_policy()
        self.active_profile = self._resolve_startup_profile()
        self._save_state()

    def _load_policy(self) -> Dict[str, Any]:
        if self.policy_path.exists():
            try:
                loaded = read_json(self.policy_path)
                if isinstance(loaded, dict) and isinstance(loaded.get("profiles"), dict):
                    return loaded
            except Exception:
                pass
        return DEFAULT_POLICY

    def _resolve_startup_profile(self) -> str:
        profiles = self.policy.get("profiles", {})
        fallback = self.policy.get("default_profile", DEFAULT_PROFILE)

        env_profile = (os.getenv("PUBCAST_PERF_PROFILE") or "").strip().lower()
        if env_profile and env_profile in profiles:
            return env_profile

        if self.state_path.exists():
            try:
                state = read_json(self.state_path)
                saved = str(state.get("active_profile", "")).strip().lower()
                if saved in profiles:
                    return saved
            except Exception:
                pass

        if fallback in profiles:
            return fallback
        # Last-resort if policy is malformed
        return next(iter(profiles.keys()), DEFAULT_PROFILE)

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_profile": self.active_profile,
            "saved_at": time.time(),
        }
        write_json(self.state_path, payload)

    def set_profile(self, profile: str) -> Dict[str, Any]:
        with self._lock:
            requested = (profile or "").strip().lower()
            if requested not in self.policy.get("profiles", {}):
                raise ValueError(f"Unknown profile: {profile!r}")
            self.active_profile = requested
            self._save_state()
            return self.current_profile_snapshot()

    def current_profile_snapshot(self) -> Dict[str, Any]:
        profiles = self.policy.get("profiles", {})
        current = dict(profiles.get(self.active_profile, {}))
        return {
            "profile": self.active_profile,
            "settings": current,
        }

    def get(self, key: str, default: Any = None) -> Any:
        profiles = self.policy.get("profiles", {})
        current = profiles.get(self.active_profile, {})
        return current.get(key, default)

    def status(self) -> Dict[str, Any]:
        return {
            "available": True,
            "policy_path": str(self.policy_path),
            "state_path": str(self.state_path),
            "version": self.policy.get("version", 1),
            "active_profile": self.active_profile,
            "profiles": self.policy.get("profiles", {}),
            "current": self.current_profile_snapshot().get("settings", {}),
        }


_performance_manager: Optional[PerformanceManager] = None


def init_performance_manager(data_dir: Path, policy_path: Optional[Path] = None) -> PerformanceManager:
    global _performance_manager
    resolved_policy = policy_path or (Path(__file__).resolve().parent.parent / "system_policy.json")
    state_path = data_dir / "global" / "performance_profile.json"
    _performance_manager = PerformanceManager(resolved_policy, state_path)
    return _performance_manager


def get_performance_manager() -> Optional[PerformanceManager]:
    return _performance_manager


__all__ = [
    "PerformanceManager",
    "init_performance_manager",
    "get_performance_manager",
    "DEFAULT_POLICY",
    "DEFAULT_PROFILE",
]
