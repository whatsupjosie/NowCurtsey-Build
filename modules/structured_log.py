"""
modules/structured_log.py — Structured Production Logger
Rear View Foresight LLC — Feic Mo Chroí — 2026-03-25
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("pubcast.structured_log")


class ProductionLog:
    MAX_BUFFER = 1000
    MAX_FILE = 5 * 1024 * 1024

    def __init__(self, data_dir: Path):
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "production.jsonl"
        self._buf: Deque[Dict[str, Any]] = deque(maxlen=self.MAX_BUFFER)
        self._subs: List[Callable[[Dict[str, Any]], Any]] = []
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, system, event, data=None, severity="info"):
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "t": time.time(),
                "system": system,
                "event": event,
                "severity": severity,
                "data": data or {},
            }
            self._buf.append(entry)
            subs = list(self._subs)
        self._write(entry)
        for subscriber in subs:
            try:
                subscriber(entry)
            except Exception as exc:
                logger.warning("Structured log subscriber failed: %s", exc)
        return entry

    def subscribe(self, cb):
        with self._lock:
            self._subs.append(cb)

    def recent(self, limit=50, system=None, severity=None):
        with self._lock:
            items = list(self._buf)
        if system:
            items = [e for e in items if e["system"] == system]
        if severity:
            items = [e for e in items if e["severity"] == severity]
        return items[-limit:]

    def _write(self, entry):
        try:
            if self._path.exists() and self._path.stat().st_size > self.MAX_FILE:
                rotated = self._path.with_suffix(f".{int(time.time())}.jsonl")
                try:
                    self._path.rename(rotated)
                except Exception as exc:
                    logger.warning("Structured log rotation failed: %s", exc)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Structured log write failed: %s", exc)


_global: Optional[ProductionLog] = None


def init_production_log(d):
    global _global
    _global = ProductionLog(d)
    return _global


def get_production_log():
    return _global


def emit(system, event, data=None, severity="info"):
    if _global:
        _global.emit(system, event, data, severity)
