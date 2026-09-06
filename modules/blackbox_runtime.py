"""Runtime witness bridge for PubCast BlackBox.

This module keeps the impartial flight recorder outside player-facing UI while
letting camera, recording, studio, and AI systems report compact known events.
It records facts only: what system acted, what changed, and the small payload
PubCast already knows at the boundary.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from blackbox_recorder import AppendOnlyBlackBoxRecorder, record_pubcast_event

logger = logging.getLogger("pubcast.blackbox_runtime")


@dataclass(frozen=True)
class BlackBoxStatus:
    enabled: bool
    session_id: str
    path: str
    next_seq: int
    previous_hash: str
    compute_budget_percent: float


class BlackBoxRuntimeWitness:
    """Small append-only witness used by runtime systems.

    The witness is intentionally boring and defensive: if BlackBox recording
    fails, production code keeps running and the failure is logged normally.
    """

    def __init__(self, data_dir: Path | str, session_id: Optional[str] = None, enabled: bool = True):
        self.data_dir = Path(data_dir)
        self.session_id = session_id or f"pubcast_{time.strftime('%Y%m%d_%H%M%S')}"
        self.enabled = bool(enabled)
        self.path = self.data_dir / "blackbox" / f"{self.session_id}.bbx"
        self._recorder = AppendOnlyBlackBoxRecorder(self.path, self.session_id)
        if self.enabled:
            self.record_event(
                "runtime.blackbox_ready",
                source="blackbox",
                actor="system:blackbox",
                data={"session_id": self.session_id, "mode": "external_boundary"},
            )

    @property
    def recorder(self) -> AppendOnlyBlackBoxRecorder:
        return self._recorder

    def status(self) -> BlackBoxStatus:
        return BlackBoxStatus(
            enabled=self.enabled,
            session_id=self.session_id,
            path=str(self.path),
            next_seq=self._recorder.next_seq,
            previous_hash=self._recorder.previous_hash,
            compute_budget_percent=self._recorder.compute_budget_percent,
        )

    def record_event(
        self,
        event_type: str,
        *,
        source: str = "system",
        actor: str = "SYS",
        data: Optional[Mapping[str, Any]] = None,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        event = {
            "event_type": event_type,
            "source": source,
            "actor": actor,
            "data": dict(data or {}),
        }
        try:
            return record_pubcast_event(self._recorder, event)
        except Exception as exc:  # pragma: no cover - runtime safety belt
            logger.warning("BlackBox witness failed for %s: %s", event_type, exc)
            return None

    def access(self, actor: str, access: str, scope: str = "status", reason: str = "operator_check") -> Optional[str]:
        if not self.enabled:
            return None
        try:
            return self._recorder.access(actor=actor, access=access, scope=scope, reason=reason)
        except Exception as exc:  # pragma: no cover
            logger.warning("BlackBox access record failed: %s", exc)
            return None

    def crash_position(self, signal: str, known: Optional[Mapping[str, Any]] = None) -> bool:
        if not self.enabled:
            return False
        try:
            self._recorder.crash_position(signal, known or {})
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("BlackBox crash-position record failed: %s", exc)
            return False

    def verify(self):
        return self._recorder.verify()


def create_blackbox_witness(data_dir: Path | str, *, session_id: Optional[str] = None, enabled: bool = True) -> BlackBoxRuntimeWitness:
    return BlackBoxRuntimeWitness(data_dir, session_id=session_id, enabled=enabled)


__all__ = ["BlackBoxRuntimeWitness", "BlackBoxStatus", "create_blackbox_witness"]
