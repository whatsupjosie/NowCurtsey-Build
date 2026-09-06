from __future__ import annotations

import os


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def alex_little_one_enabled() -> bool:
    return env_flag("ENABLE_ALEX_LITTLE_ONE", default=False)
