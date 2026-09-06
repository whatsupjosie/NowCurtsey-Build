# PubCast AI — circuit_breaker.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/circuit_breaker.py — Circuit Breaker pattern
=====================================================
Prevents cascading failures in the distributed engine by tracking failure
rates per named breaker and stopping calls once the threshold is exceeded.

State machine:
    CLOSED  → normal operation, failures are counted
    OPEN    → calls are rejected immediately with CircuitOpenError
    HALF_OPEN → one probe call allowed; success → CLOSED, failure → OPEN

Public API (consumed by distributed_engine.py):
    CircuitBreaker
    CircuitOpenError
    get_breaker(name, failure_threshold, recovery_timeout) → CircuitBreaker
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""
    def __init__(self, name: str, until: float) -> None:
        self.name  = name
        self.until = until
        remaining  = max(0.0, until - time.time())
        super().__init__(
            f"Circuit '{name}' is OPEN — retry in {remaining:.1f}s"
        )


# ── State ─────────────────────────────────────────────────────────────────────

class _State(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    Parameters
    ----------
    name
        Human-readable identifier (used in logs and errors).
    failure_threshold
        Number of consecutive failures before the circuit opens.
    recovery_timeout
        Seconds to wait in OPEN state before allowing a probe (HALF_OPEN).
    success_threshold
        Consecutive successes in HALF_OPEN needed to close the circuit.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int   = 5,
        recovery_timeout: float  = 30.0,
        success_threshold: int   = 2,
    ) -> None:
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.success_threshold = success_threshold

        self._state:             _State = _State.CLOSED
        self._failure_count:     int    = 0
        self._success_count:     int    = 0
        self._opened_at:         float  = 0.0
        self._last_probe_at:     float  = 0.0
        self._total_calls:       int    = 0
        self._total_failures:    int    = 0
        self._total_rejections:  int    = 0
        self._lock = Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition()
            return self._state.value

    def allow_request(self) -> bool:
        """
        Return True if a call should be attempted.
        CLOSED → always True.
        OPEN   → False unless recovery_timeout has elapsed (probe allowed).
        HALF_OPEN → True for one probe at a time.
        """
        with self._lock:
            self._maybe_transition()
            if self._state == _State.CLOSED:
                return True
            if self._state == _State.OPEN:
                return False
            # HALF_OPEN: only allow one concurrent probe
            if time.time() - self._last_probe_at >= 1.0:
                self._last_probe_at = time.time()
                return True
            return False

    def call_succeeded(self) -> None:
        """Record a successful call result."""
        with self._lock:
            self._total_calls += 1
            if self._state == _State.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._close()
            elif self._state == _State.CLOSED:
                self._failure_count = 0  # reset on any success

    def call_failed(self) -> None:
        """Record a failed call result."""
        with self._lock:
            self._total_calls    += 1
            self._total_failures += 1
            if self._state == _State.HALF_OPEN:
                # Probe failed → reopen immediately
                self._open()
                return
            if self._state == _State.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._open()

    def guard(self) -> None:
        """
        Raise CircuitOpenError if the circuit will not allow a request.
        Intended for use in non-context-manager call sites::

            breaker.guard()         # raises if OPEN
            result = do_work()
            breaker.call_succeeded()
        """
        if not self.allow_request():
            self._total_rejections += 1
            raise CircuitOpenError(self.name, self._opened_at + self.recovery_timeout)

    def reset(self) -> None:
        """Force the circuit to CLOSED state (admin/test use)."""
        with self._lock:
            self._close()
            logger.info("Circuit '%s' manually reset to CLOSED", self.name)

    def stats(self) -> dict:
        with self._lock:
            self._maybe_transition()
            return {
                "name":             self.name,
                "state":            self._state.value,
                "failure_count":    self._failure_count,
                "total_calls":      self._total_calls,
                "total_failures":   self._total_failures,
                "total_rejections": self._total_rejections,
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _maybe_transition(self) -> None:
        """Check if OPEN → HALF_OPEN transition should happen (called under lock)."""
        if (
            self._state == _State.OPEN
            and time.time() >= self._opened_at + self.recovery_timeout
        ):
            logger.info(
                "Circuit '%s': OPEN → HALF_OPEN (recovery timeout elapsed)", self.name
            )
            self._state         = _State.HALF_OPEN
            self._success_count = 0
            self._last_probe_at = 0.0

    def _open(self) -> None:
        """Transition to OPEN state (called under lock)."""
        self._state       = _State.OPEN
        self._opened_at   = time.time()
        self._failure_count = 0
        logger.warning(
            "Circuit '%s' OPENED after %d failures — back-off %.1fs",
            self.name, self.failure_threshold, self.recovery_timeout,
        )

    def _close(self) -> None:
        """Transition to CLOSED state (called under lock)."""
        self._state         = _State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("Circuit '%s' CLOSED — normal operation resumed", self.name)


# ── Registry ─────────────────────────────────────────────────────────────────

_registry: Dict[str, CircuitBreaker] = {}
_registry_lock = Lock()


def get_breaker(
    name: str,
    failure_threshold: int  = 5,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """
    Return a named CircuitBreaker, creating it on first call.
    Subsequent calls with the same name return the existing instance;
    threshold/timeout parameters are ignored on retrieval.
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            logger.debug(
                "CircuitBreaker '%s' created (threshold=%d, timeout=%.1fs)",
                name, failure_threshold, recovery_timeout,
            )
        return _registry[name]


def all_breaker_stats() -> Dict[str, dict]:
    """Return stats for every registered breaker (useful for /healthz endpoints)."""
    with _registry_lock:
        return {name: cb.stats() for name, cb in _registry.items()}
