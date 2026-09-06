"""
camera_boxer.py — Tiered camera resource donation system.

Reads real engine_stress from the C++ bridge (0.0–1.0 float, live per-frame).
When the twin voxel engine is under pressure, cameras donate processing capacity
in a fixed sacrifice order — lowest-priority first, never audio.

Sacrifice order (user spec):
  Tier 1  stress ≥ 0.65  camera 4 donates partial capacity
  Tier 2  stress ≥ 0.80  cameras 4 + 3 donate
  Tier 3  stress ≥ 0.92  cameras 4 + 3 + 2 donate
  Normal  stress < 0.65  full capacity restored

NEVER SACRIFICE:
  - Audio (always protected regardless of tier)
  - Camera 1 (program / live camera — never touches it)

Integration:
  boxer = CameraBoxer(bridge=voxel_bridge, epete=epete_instance)
  boxer.start()          # starts background polling loop
  boxer.stop()           # clean shutdown

  Or mount it through E-Pete after both are initialized:
  epete.register_camera_boxer(boxer)

Routes (install_camera_boxer_routes):
  GET  /api/boxer/status   → current tier, camera states, stress
  POST /api/boxer/override → force a tier or disable boxing
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.camera_boxer")


# ── Tiers ────────────────────────────────────────────────────────────────────

class BoxerTier(str, Enum):
    NORMAL    = "normal"     # Full capacity, no donation
    TIER_1    = "tier_1"     # Camera 4 donates partial
    TIER_2    = "tier_2"     # Cameras 4 + 3 donate
    TIER_3    = "tier_3"     # Cameras 4 + 3 + 2 donate
    OVERRIDE  = "override"   # Manual override active


# Stress thresholds — tunable without touching the logic
TIER_1_THRESHOLD = 0.65   # camera 4 starts donating
TIER_2_THRESHOLD = 0.80   # cameras 4 + 3
TIER_3_THRESHOLD = 0.92   # cameras 4 + 3 + 2

# Fidelity levels when a camera is donating
DONATE_PARTIAL   = 0.35   # partial donation
DONATE_FULL      = 0.15   # heavy donation
FULL_FIDELITY    = 1.00   # normal operation

# Hysteresis — require stress to drop this much below a threshold before recovering
# Prevents oscillation at threshold boundaries
HYSTERESIS       = 0.06

POLL_INTERVAL    = 0.25   # seconds between stress reads


# ── Camera state ─────────────────────────────────────────────────────────────

@dataclass
class CameraState:
    camera_id: str
    fidelity:  float = FULL_FIDELITY   # 0.0–1.0
    donating:  bool  = False
    protected: bool  = False            # True = never touched

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "fidelity":  round(self.fidelity, 2),
            "donating":  self.donating,
            "protected": self.protected,
        }


# ── Boxer ─────────────────────────────────────────────────────────────────────

class CameraBoxer:
    """
    Reads real engine_stress from the bridge and adjusts camera fidelity
    in a fixed sacrifice order. Audio is always excluded.

    Sacrifice order: 4 → (4+3) → (4+3+2). Camera 1 and audio never touched.
    """

    def __init__(
        self,
        bridge:  Any = None,   # VoxelBridge instance (must have _v3_shm or _v3_metrics)
        epete:   Any = None,   # EPete instance (optional — for notifying)
        cameras: Optional[List[str]] = None,
    ):
        self.bridge = bridge
        self.epete  = epete

        # Default camera registry matches twin_engine_service defaults:
        # main=cam1 (program), wide, closeup, overhead=cam4
        # User spec maps: "camera 4" → least priority (overhead/reserve)
        #                 "camera 1" → program feed (PROTECTED)
        cam_ids = cameras or ["main", "wide", "closeup", "overhead"]
        self._cameras: Dict[str, CameraState] = {}
        for cid in cam_ids:
            self._cameras[cid] = CameraState(camera_id=cid)

        # Camera 1 / main is always protected
        if "main" in self._cameras:
            self._cameras["main"].protected = True

        # Sacrifice order: highest index first
        # cam_ids[3]=overhead (cam4), cam_ids[2]=closeup (cam3), cam_ids[1]=wide (cam2)
        self._sacrifice_order: List[str] = [
            c for c in reversed(cam_ids[1:])   # skip first (protected)
            if c in self._cameras
        ]

        self._tier:       BoxerTier  = BoxerTier.NORMAL
        self._stress:     float      = 0.0
        self._override:   Optional[BoxerTier] = None
        self._running:    bool       = False
        self._task:       Optional[asyncio.Task] = None
        self._last_change: float     = 0.0

        logger.info(
            "[CameraBoxer] Ready — sacrifice order: %s | protected: %s | audio: always protected",
            self._sacrifice_order,
            [c for c, s in self._cameras.items() if s.protected],
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._poll_loop())
        logger.info("[CameraBoxer] Started — polling every %.2fs", POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("[CameraBoxer] Stopped")

    def set_override(self, tier: Optional[BoxerTier]) -> None:
        """Force a specific tier or clear override (None = resume auto)."""
        self._override = tier
        if tier is not None:
            self._apply_tier(BoxerTier.OVERRIDE, forced_tier=tier)
            logger.info("[CameraBoxer] Override → %s", tier)
        else:
            logger.info("[CameraBoxer] Override cleared — resuming auto")

    def status(self) -> Dict[str, Any]:
        return {
            "tier":           self._tier.value,
            "stress":         round(self._stress, 3),
            "override":       self._override.value if self._override else None,
            "cameras":        [s.to_dict() for s in self._cameras.values()],
            "sacrifice_order": self._sacrifice_order,
            "audio_protected": True,   # always
            "thresholds": {
                "tier_1": TIER_1_THRESHOLD,
                "tier_2": TIER_2_THRESHOLD,
                "tier_3": TIER_3_THRESHOLD,
                "hysteresis": HYSTERESIS,
            },
        }

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[CameraBoxer] Poll error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        stress = self._read_stress()
        self._stress = stress

        if self._override is not None:
            return   # manual override active — don't auto-adjust

        new_tier = self._calculate_tier(stress)
        if new_tier != self._tier:
            logger.info(
                "[CameraBoxer] Tier %s → %s (stress=%.1f%%)",
                self._tier.value, new_tier.value, stress * 100,
            )
            self._apply_tier(new_tier)
            self._last_change = time.time()

            # Notify E-Pete if wired
            if self.epete and hasattr(self.epete, "on_boxer_tier_change"):
                try:
                    self.epete.on_boxer_tier_change(new_tier, stress)
                except Exception:
                    pass

    def _read_stress(self) -> float:
        """Read real engine_stress from the C++ bridge."""
        if self.bridge is None:
            return 0.0
        # V3 SHM path — this is the live float E-Pete now has access to
        if hasattr(self.bridge, "_v3_metrics"):
            try:
                m = self.bridge._v3_metrics()
                return float(m.get("stress", 0.0))
            except Exception:
                pass
        # Fallback: IRM-derived stress from bridge metrics
        if hasattr(self.bridge, "get_metrics"):
            try:
                m = self.bridge.get_metrics()
                # IRM score is 0–100 inverted (100=healthy, 0=emergency)
                irm_score = m.get("irm_score", 100.0)
                return max(0.0, min(1.0, (100.0 - irm_score) / 100.0))
            except Exception:
                pass
        return 0.0

    def _calculate_tier(self, stress: float) -> BoxerTier:
        """
        Hysteresis: use different thresholds for rising vs falling stress
        to avoid oscillation at tier boundaries.
        """
        current = self._tier

        # Rising stress — use standard thresholds
        if stress >= TIER_3_THRESHOLD:
            return BoxerTier.TIER_3
        if stress >= TIER_2_THRESHOLD:
            return BoxerTier.TIER_2
        if stress >= TIER_1_THRESHOLD:
            return BoxerTier.TIER_1

        # Falling stress — apply hysteresis before recovering
        if current == BoxerTier.TIER_3 and stress < TIER_3_THRESHOLD - HYSTERESIS:
            return BoxerTier.TIER_2
        if current == BoxerTier.TIER_2 and stress < TIER_2_THRESHOLD - HYSTERESIS:
            return BoxerTier.TIER_1
        if current == BoxerTier.TIER_1 and stress < TIER_1_THRESHOLD - HYSTERESIS:
            return BoxerTier.NORMAL

        return current   # stay in current tier

    def _apply_tier(
        self,
        tier: BoxerTier,
        forced_tier: Optional[BoxerTier] = None,
    ) -> None:
        """
        Apply fidelity settings based on tier.

        Sacrifice order: camera 4 first, then 3, then 2. Never camera 1. Never audio.
        forced_tier is used when tier=OVERRIDE to specify which tier's settings to apply.
        """
        self._tier = tier
        effective = forced_tier if forced_tier is not None else tier

        # Reset all to full first
        for cam in self._cameras.values():
            if not cam.protected:
                cam.fidelity = FULL_FIDELITY
                cam.donating = False

        n = len(self._sacrifice_order)   # how many cameras are available to donate

        if effective == BoxerTier.TIER_1:
            # Camera 4 (sacrifice_order[0]) donates partial
            if n >= 1:
                cam = self._cameras.get(self._sacrifice_order[0])
                if cam and not cam.protected:
                    cam.fidelity = DONATE_PARTIAL
                    cam.donating = True
            logger.info("[CameraBoxer] TIER 1 — %s at %.0f%% fidelity (donating to engine)",
                        self._sacrifice_order[0] if n >= 1 else "—",
                        DONATE_PARTIAL * 100)

        elif effective == BoxerTier.TIER_2:
            # Cameras 4 + 3
            for i in range(min(2, n)):
                cam = self._cameras.get(self._sacrifice_order[i])
                if cam and not cam.protected:
                    cam.fidelity = DONATE_FULL if i == 0 else DONATE_PARTIAL
                    cam.donating = True
            names = self._sacrifice_order[:min(2, n)]
            logger.info("[CameraBoxer] TIER 2 — %s donating to engine", names)

        elif effective == BoxerTier.TIER_3:
            # Cameras 4 + 3 + 2 — full donation
            for i in range(min(3, n)):
                cam = self._cameras.get(self._sacrifice_order[i])
                if cam and not cam.protected:
                    cam.fidelity = DONATE_FULL
                    cam.donating = True
            names = self._sacrifice_order[:min(3, n)]
            logger.warning("[CameraBoxer] TIER 3 — %s all donating — audio still protected", names)

        elif effective == BoxerTier.NORMAL:
            logger.info("[CameraBoxer] Normal — all cameras at full capacity")

        # Audio is never touched — it's not in the camera registry
        # and this function has no path to affect it. By design.


# ── Route installation ────────────────────────────────────────────────────────

def install_camera_boxer_routes(app: Any, boxer: "CameraBoxer") -> None:
    """Mount /api/boxer/* routes onto the FastAPI app."""

    @app.get("/api/boxer/status")
    async def boxer_status() -> Dict[str, Any]:
        return boxer.status()

    @app.post("/api/boxer/override")
    async def boxer_override(payload: Dict[str, Any]) -> Dict[str, Any]:
        tier_str = payload.get("tier")
        if tier_str is None or tier_str == "auto":
            boxer.set_override(None)
            return {"ok": True, "override": None, "message": "Override cleared — auto mode"}
        try:
            tier = BoxerTier(tier_str)
            boxer.set_override(tier)
            return {"ok": True, "override": tier.value}
        except ValueError:
            return {
                "ok": False,
                "error": f"Unknown tier '{tier_str}'",
                "valid_tiers": [t.value for t in BoxerTier],
            }
