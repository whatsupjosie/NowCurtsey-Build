"""Small self-contained append-only BlackBox recorder used by PubCast.

The production boundary needs a deterministic local witness without relying on
an unpublished third-party module. Records are JSON Lines with a SHA-256 hash
chain. The file is append-only at the application layer; verification walks the
chain and reports the first integrity failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    checked: int
    errors: list[str]


class AppendOnlyBlackBoxRecorder:
    """Hash-chained JSONL recorder with a tiny, dependency-free API."""

    def __init__(self, path: Path | str, session_id: str):
        self.path = Path(path)
        self.session_id = str(session_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._next_seq = 1
        self._previous_hash = GENESIS_HASH
        self._load_tail()

    def _load_tail(self) -> None:
        try:
            with self.path.open("rb") as fh:
                lines = fh.readlines()
        except OSError:
            return
        if not lines:
            return
        try:
            last = json.loads(lines[-1].decode("utf-8"))
            self._next_seq = int(last["seq"]) + 1
            self._previous_hash = str(last["hash"])
        except Exception:
            # Preserve appendability but do not pretend the tail is trusted.
            self._next_seq = 1
            self._previous_hash = GENESIS_HASH

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @property
    def previous_hash(self) -> str:
        return self._previous_hash

    @property
    def compute_budget_percent(self) -> float:
        # The recorder itself has no scheduler; expose the remaining configured
        # budget if one is supplied, otherwise report a neutral 100%.
        try:
            return max(0.0, min(100.0, float(os.getenv("PUBCAST_BLACKBOX_BUDGET_PERCENT", "100"))))
        except ValueError:
            return 100.0

    def _append(self, kind: str, payload: Mapping[str, Any]) -> str:
        record = {
            "seq": self._next_seq,
            "timestamp": time.time(),
            "session_id": self.session_id,
            "kind": kind,
            "previous_hash": self._previous_hash,
            "payload": dict(payload),
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        record["hash"] = digest
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        self._previous_hash = digest
        self._next_seq += 1
        return digest

    def append_event(self, event: Mapping[str, Any]) -> str:
        return self._append("event", event)

    def access(self, *, actor: str, access: str, scope: str, reason: str) -> str:
        return self._append("access", {
            "actor": actor, "access": access, "scope": scope, "reason": reason,
        })

    def crash_position(self, signal: str, known: Mapping[str, Any]) -> str:
        return self._append("crash_position", {"signal": signal, "known": dict(known)})

    def verify(self) -> VerificationResult:
        errors: list[str] = []
        checked = 0
        previous = GENESIS_HASH
        expected_seq = 1
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    checked += 1
                    try:
                        record = json.loads(line)
                        actual_hash = record.get("hash")
                        if record.get("seq") != expected_seq:
                            errors.append(f"line {line_no}: expected seq {expected_seq}, got {record.get('seq')}")
                        if record.get("previous_hash") != previous:
                            errors.append(f"line {line_no}: previous hash mismatch")
                        unsigned = dict(record)
                        unsigned.pop("hash", None)
                        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                        expected_hash = hashlib.sha256(canonical).hexdigest()
                        if actual_hash != expected_hash:
                            errors.append(f"line {line_no}: hash mismatch")
                        previous = str(actual_hash)
                        expected_seq += 1
                    except Exception as exc:
                        errors.append(f"line {line_no}: invalid record: {exc}")
                        break
        except OSError as exc:
            errors.append(f"unable to read recorder file: {exc}")
        return VerificationResult(ok=not errors, checked=checked, errors=errors)


def record_pubcast_event(recorder: AppendOnlyBlackBoxRecorder, event: Mapping[str, Any]) -> str:
    return recorder.append_event(event)


__all__ = ["AppendOnlyBlackBoxRecorder", "VerificationResult", "record_pubcast_event"]
