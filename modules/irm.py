# PubCast AI — irm.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/irm.py — Intelligent Resource Monitor
===============================================
Provides CPU/memory/GPU health sensing and IRM-controlled actuators for the
DistributedEngineNode.  Designed for zero-dependency operation: psutil is used
when available; falls back to platform stdlib when not.

Public API (consumed by distributed_engine.py):
    IRMController   — top-level controller; tick(), get_health(), get_batch_size(), record_latency()
    IRMSensor       — reads system metrics
    IRMActuator     — applies corrective actions
    HealthStatus    — enum: OK / DEGRADED / CRITICAL / FAILED
    HealthReport    — dataclass snapshot returned by get_health()
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)

# ── Optional psutil ───────────────────────────────────────────────────────────
try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    _psutil = None  # type: ignore
    _HAS_PSUTIL = False


# ── Enums & dataclasses ───────────────────────────────────────────────────────

class HealthStatus(str, Enum):
    OK       = "ok"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    FAILED   = "failed"


@dataclass
class HealthReport:
    status: HealthStatus
    cpu_pct: float
    memory_pct: float
    gpu_pct: float                       # 0.0 when GPU unavailable
    health_score: float                  # 0.0 (worst) – 1.0 (perfect)
    batch_size: int
    avg_latency_ms: float
    p99_latency_ms: float
    timestamp: float = field(default_factory=time.time)
    notes: str = ""


# ── Sensor ────────────────────────────────────────────────────────────────────

class IRMSensor:
    """
    Reads raw system metrics.  All values are 0–100 percentages.
    GPU reading uses nvidia-smi via subprocess; silently returns 0.0 if
    unavailable (no CUDA, no nvidia-smi, running in a VM, etc.).
    """

    def __init__(self) -> None:
        self._gpu_available: Optional[bool] = None

    def cpu_percent(self) -> float:
        if _HAS_PSUTIL:
            return float(_psutil.cpu_percent(interval=None))
        # Fallback: read /proc/loadavg on Linux
        try:
            with open("/proc/loadavg") as f:
                load1 = float(f.read().split()[0])
            cpu_count = os.cpu_count() or 1
            return min(load1 / cpu_count * 100, 100.0)
        except OSError:
            return 0.0

    def memory_percent(self) -> float:
        if _HAS_PSUTIL:
            return float(_psutil.virtual_memory().percent)
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info: Dict[str, int] = {}
            for line in lines:
                parts = line.split()
                if parts:
                    info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", 0)
            if total:
                return (total - avail) / total * 100.0
        except OSError:
            pass
        return 0.0

    def gpu_percent(self) -> float:
        if self._gpu_available is False:
            return 0.0
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                self._gpu_available = True
                vals = [float(v.strip()) for v in result.stdout.strip().splitlines() if v.strip()]
                return sum(vals) / len(vals) if vals else 0.0
        except Exception as exc:
            logger.debug("irm: nvidia-smi query failed, marking GPU unavailable: %s", exc)
        return 0.0


# ── Actuator ──────────────────────────────────────────────────────────────────

class IRMActuator:
    """
    Applies corrective actions in response to IRM decisions.
    Actions are logged; physical implementation (throttling, shedding, etc.)
    is handled by the engine layer that owns the actuator.
    """

    def __init__(self) -> None:
        self._actions: deque[str] = deque(maxlen=100)

    def reduce_batch_size(self, current: int, factor: float = 0.75) -> int:
        new_size = max(1, int(current * factor))
        msg = f"IRMActuator: reducing batch size {current} → {new_size}"
        logger.info(msg)
        self._actions.append(msg)
        return new_size

    def increase_batch_size(self, current: int, max_size: int, factor: float = 1.25) -> int:
        new_size = min(max_size, int(current * factor))
        msg = f"IRMActuator: increasing batch size {current} → {new_size}"
        logger.debug(msg)
        self._actions.append(msg)
        return new_size

    def signal_shed_load(self, reason: str) -> None:
        msg = f"IRMActuator: load shedding — {reason}"
        logger.warning(msg)
        self._actions.append(msg)

    def signal_recover(self) -> None:
        msg = "IRMActuator: system recovering, resuming normal operation"
        logger.info(msg)
        self._actions.append(msg)

    def recent_actions(self) -> list[str]:
        return list(self._actions)


# ── Controller ────────────────────────────────────────────────────────────────

class IRMController:
    """
    Orchestrates sensor readings, applies heuristics, and exposes the API
    consumed by DistributedEngineNode:

        irm.tick()                → update internal state (call every cycle)
        irm.get_health()          → HealthReport
        irm.get_batch_size()      → int
        irm.record_latency(ms)    → None
    """

    # Thresholds for health classification
    CPU_DEGRADED  = 75.0
    CPU_CRITICAL  = 90.0
    MEM_DEGRADED  = 80.0
    MEM_CRITICAL  = 92.0
    GPU_DEGRADED  = 80.0
    GPU_CRITICAL  = 95.0

    def __init__(
        self,
        *,
        initial_batch_size: int = 8,
        max_batch_size: int = 64,
        latency_window: int = 200,
    ) -> None:
        self.sensor   = IRMSensor()
        self.actuator = IRMActuator()

        self._batch_size     = initial_batch_size
        self._max_batch_size = max_batch_size

        # Rolling latency window (ms values)
        self._latencies: Deque[float] = deque(maxlen=latency_window)

        # Cached last report
        self._last_report: Optional[HealthReport] = None

        # Smoothed metrics (exponential moving average, α = 0.2)
        self._cpu_ema:    float = 0.0
        self._mem_ema:    float = 0.0
        self._gpu_ema:    float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def tick(self) -> None:
        """Update sensor readings and apply IRM heuristics.  Call once per engine cycle."""
        alpha = 0.2
        cpu = self.sensor.cpu_percent()
        mem = self.sensor.memory_percent()
        gpu = self.sensor.gpu_percent()

        self._cpu_ema = alpha * cpu + (1 - alpha) * self._cpu_ema
        self._mem_ema = alpha * mem + (1 - alpha) * self._mem_ema
        self._gpu_ema = alpha * gpu + (1 - alpha) * self._gpu_ema

        status = self._classify(self._cpu_ema, self._mem_ema, self._gpu_ema)
        score  = self._compute_score(self._cpu_ema, self._mem_ema, self._gpu_ema)

        # Adaptive batch sizing
        if status == HealthStatus.CRITICAL:
            self._batch_size = self.actuator.reduce_batch_size(self._batch_size, factor=0.5)
            self.actuator.signal_shed_load(
                f"CPU={self._cpu_ema:.1f}% MEM={self._mem_ema:.1f}% GPU={self._gpu_ema:.1f}%"
            )
        elif status == HealthStatus.DEGRADED:
            self._batch_size = self.actuator.reduce_batch_size(self._batch_size, factor=0.8)
        elif status == HealthStatus.OK and score > 0.85:
            self._batch_size = self.actuator.increase_batch_size(
                self._batch_size, self._max_batch_size, factor=1.1
            )

        avg_lat, p99_lat = self._latency_stats()

        self._last_report = HealthReport(
            status=status,
            cpu_pct=round(self._cpu_ema, 2),
            memory_pct=round(self._mem_ema, 2),
            gpu_pct=round(self._gpu_ema, 2),
            health_score=round(score, 4),
            batch_size=self._batch_size,
            avg_latency_ms=round(avg_lat, 2),
            p99_latency_ms=round(p99_lat, 2),
        )

    def get_health(self) -> HealthReport:
        if self._last_report is None:
            self.tick()
        return self._last_report  # type: ignore[return-value]

    def get_batch_size(self) -> int:
        return self._batch_size

    def record_latency(self, ms: float) -> None:
        """Record a single request latency sample (milliseconds)."""
        self._latencies.append(ms)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _classify(self, cpu: float, mem: float, gpu: float) -> HealthStatus:
        if cpu >= self.CPU_CRITICAL or mem >= self.MEM_CRITICAL or gpu >= self.GPU_CRITICAL:
            return HealthStatus.CRITICAL
        if cpu >= self.CPU_DEGRADED or mem >= self.MEM_DEGRADED or gpu >= self.GPU_DEGRADED:
            return HealthStatus.DEGRADED
        return HealthStatus.OK

    def _compute_score(self, cpu: float, mem: float, gpu: float) -> float:
        """Weighted health score: CPU 40%, memory 30%, GPU 30%."""
        cpu_s = max(0.0, 1.0 - cpu / 100)
        mem_s = max(0.0, 1.0 - mem / 100)
        gpu_s = max(0.0, 1.0 - gpu / 100)
        return 0.40 * cpu_s + 0.30 * mem_s + 0.30 * gpu_s

    def _latency_stats(self) -> tuple[float, float]:
        if not self._latencies:
            return 0.0, 0.0
        sorted_lats = sorted(self._latencies)
        avg = sum(sorted_lats) / len(sorted_lats)
        p99_idx = max(0, int(len(sorted_lats) * 0.99) - 1)
        return avg, sorted_lats[p99_idx]


    def check(self) -> "HealthReport":
        """Alias for get_health() — used by engine_status endpoint."""
        self.tick()
        return self.get_health()


# ── Patch HealthReport with to_dict ──────────────────────────────────────────

_orig_init = HealthReport.__init__

def _health_report_to_dict(self) -> dict:
    return {
        "status":        self.status.value,
        "cpu_pct":       round(self.cpu_pct, 1),
        "memory_pct":    round(self.memory_pct, 1),
        "gpu_pct":       round(self.gpu_pct, 1),
        "health_score":  round(self.health_score, 3),
        "batch_size":    self.batch_size,
        "avg_latency_ms": round(self.avg_latency_ms, 2),
        "p99_latency_ms": round(self.p99_latency_ms, 2),
        "timestamp":     self.timestamp,
        "notes":         self.notes,
    }

HealthReport.to_dict = _health_report_to_dict
