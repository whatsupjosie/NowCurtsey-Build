"""
⚠️  DEPRECATED — DO NOT WIRE THIS IN.  (marked 2026-08-23, Run 1)

This module was written on 2026-08-23 on the belief that the affect engine was
not connected to anything. That belief was WRONG. alex_core.py already has a
complete, live, better integration:

    - evaluate()            → alex_core.py line ~766 (inside process_message)
    - battery override      → lines ~769-771, with the None/'observing' guard
    - meet_them_at → prompt → line ~796 ('operating_note' in response_guidelines)
    - persistence           → _load/_save_affect_state via MemoryCore (canonical)
    - safety guard          → affect reading may NOT override ANCHOR/WITNESS

alex_core.py explicitly calls this module's flat-file approach "Prompt-1-era"
and migrated away from it to MemoryCore, which is the canonical sovereign store.

Wiring this module in would create a SECOND competing persistence path
(flat data/affect/*.json alongside MemoryCore) and double-evaluate every turn.

Kept only as a record of the duplicate-work incident. Read alex_core.py instead.

─────────────────────────────────────────────────────────────────────────────
Original docstring follows.

affect_wiring.py — Live integration of AffectContextEngine into PubCast message flow.

Responsible for:
  1. Creating and managing engine instances per session/user
  2. Calling evaluate() at message ingestion
  3. Bridging to alex_core.py via to_legacy_battery()
  4. Persisting baseline/prior state across restarts
  5. Injecting router guidance into bot system prompts

Dropped into pubcast/modules/. No external dependencies beyond affect_context_engine.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from modules.affect_context_engine import AffectContextEngine

logger = logging.getLogger("pubcast.affect_wiring")


class AffectEngineManager:
    """
    Singleton manager for AffectContextEngine instances.
    One engine per session_id, created lazily.
    """

    def __init__(self, data_dir: Path = Path("data/affect")):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.engines: Dict[str, AffectContextEngine] = {}
        self.last_results: Dict[str, Dict[str, Any]] = {}  # Store last result per key
        self._lock = threading.RLock()

    def get_or_create(self, session_id: str, user_id: str) -> AffectContextEngine:
        """Get or create engine for this session/user pair."""
        with self._lock:
            key = f"{session_id}:{user_id}"
            if key not in self.engines:
                engine = AffectContextEngine()
                # Load prior state if it exists
                self._load_state(engine, user_id)
                self.engines[key] = engine
                logger.info(f"Created affect engine for {key}")
            return self.engines[key]

    def evaluate_message(
        self,
        session_id: str,
        user_id: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        Evaluate a user message through the affect engine.
        Returns the full result dict including route() guidance.
        """
        engine = self.get_or_create(session_id, user_id)
        key = f"{session_id}:{user_id}"
        try:
            result = engine.evaluate(text, user_id, session_id)
            self.last_results[key] = result
            state = result.get("reading", {}).get("state", "unknown")
            conf = result.get("reading", {}).get("confidence", 0)
            logger.debug(f"Affect eval for {user_id}: confidence={conf:.2f}, state={state}")
            return result
        except Exception as exc:
            logger.error(f"Affect engine error for {user_id}: {exc}", exc_info=True)
            # Return neutral state on error — don't crash the bot
            fallback = {
                "reading": {"state": "observing", "confidence": 0.0, "sustained_turns": 0},
                "affect": {"load_z": 0.0},
                "route": {"everyday": {"meet_them_at": None}},
            }
            self.last_results[key] = fallback
            return fallback

    def get_battery_state(self, session_id: str, user_id: str) -> Optional[str]:
        """
        Get legacy UserBattery state for alex_core integration.
        Maps affect engine output to {CHARGED, MEDIUM, LOW, DEPLETED}.
        Returns None when the engine is still 'observing' — caller must NOT
        overwrite existing alex_core battery state in that case (see
        AFFECT_MODEL_CONCLUSIONS.md #1: low-confidence readings never clobber).
        """
        key = f"{session_id}:{user_id}"
        payload = self.last_results.get(key)
        if payload is None:
            return None  # No evaluation has happened yet this session

        battery_str = AffectContextEngine.to_legacy_battery(payload)
        if battery_str is None:
            return None  # observing → caller keeps existing state
        return battery_str.upper()

    def persist_state(self, user_id: str) -> None:
        """Save engine state to disk for this user."""
        with self._lock:
            # Find all engines for this user_id across sessions
            for key, engine in self.engines.items():
                if key.endswith(f":{user_id}"):
                    self._save_state(engine, user_id)

    def _load_state(self, engine: AffectContextEngine, user_id: str) -> None:
        """Load user's baseline and prior from disk."""
        baseline_path = self.data_dir / f"{user_id}_baseline.json"
        prior_path = self.data_dir / f"{user_id}_prior.json"

        try:
            if baseline_path.exists():
                baseline = json.loads(baseline_path.read_text())
                engine.import_baseline(user_id, baseline)
                logger.debug(f"Loaded baseline for {user_id}")
        except Exception as exc:
            logger.warning(f"Failed to load baseline for {user_id}: {exc}")

        try:
            if prior_path.exists():
                prior = json.loads(prior_path.read_text())
                engine.import_prior(user_id, prior)
                logger.debug(f"Loaded prior for {user_id}")
        except Exception as exc:
            logger.warning(f"Failed to load prior for {user_id}: {exc}")

    def _save_state(self, engine: AffectContextEngine, user_id: str) -> None:
        """Save engine state to disk."""
        try:
            baseline = engine.export_baseline(user_id)
            baseline_path = self.data_dir / f"{user_id}_baseline.json"
            baseline_path.write_text(json.dumps(baseline, indent=2))
            logger.debug(f"Saved baseline for {user_id}")
        except Exception as exc:
            logger.error(f"Failed to save baseline for {user_id}: {exc}")

        try:
            prior = engine.export_prior(user_id)
            prior_path = self.data_dir / f"{user_id}_prior.json"
            prior_path.write_text(json.dumps(prior, indent=2))
            logger.debug(f"Saved prior for {user_id}")
        except Exception as exc:
            logger.error(f"Failed to save prior for {user_id}: {exc}")


# Module-level singleton
_manager: Optional[AffectEngineManager] = None


def get_manager() -> AffectEngineManager:
    """Get the singleton manager."""
    global _manager
    if _manager is None:
        _manager = AffectEngineManager()
    return _manager


def init_affect_system(data_dir: Path = Path("data/affect")) -> AffectEngineManager:
    """Initialize the affect system. Call once at startup."""
    global _manager
    _manager = AffectEngineManager(data_dir)
    logger.info("Affect system initialized")
    return _manager


def evaluate_user_message(
    session_id: str,
    user_id: str,
    text: str,
) -> Dict[str, Any]:
    """Convenience function: evaluate a message without manager boilerplate."""
    return get_manager().evaluate_message(session_id, user_id, text)


def get_battery_for_user(session_id: str, user_id: str) -> str:
    """Convenience function: get battery state for alex_core."""
    return get_manager().get_battery_state(session_id, user_id)


def get_route_guidance(
    session_id: str,
    user_id: str,
    text: str,
) -> Optional[Dict[str, Any]]:
    """
    Get route() guidance for a user message.
    Returns the ['route']['everyday']['meet_them_at'] instruction for the bot,
    or None if not yet confident enough to steer.
    """
    result = evaluate_user_message(session_id, user_id, text)
    route = result.get("route", {})
    everyday = route.get("everyday", {})
    return everyday.get("meet_them_at")


if __name__ == "__main__":
    # Quick smoke test — real payload shape, not guessed
    logging.basicConfig(level=logging.INFO)
    mgr = init_affect_system(data_dir=Path("/tmp/affect_smoke_test"))

    session = "test_session"
    user = "alice"

    msgs = [
        "Hey, I'm working on this project and it's going well so far.",
        "Actually we just hit a major blocker, hours gone by now.",
        "I don't know, maybe I'm wrong about the whole approach.",
        "Whatever. Doesn't matter. Let's just ship it broken.",
    ]

    for i, msg in enumerate(msgs, 1):
        result = evaluate_user_message(session, user, msg)
        reading = result.get("reading", {})
        print(
            f"Turn {i}: state={reading.get('state', '?'):12} "
            f"conf={reading.get('confidence', 0):.2f} "
            f"battery={get_battery_for_user(session, user)}"
        )

    mgr.persist_state(user)
    print("State persisted to", mgr.data_dir)
