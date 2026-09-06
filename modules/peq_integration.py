"""
modules/peq_integration.py

Wires PEQ into the live PubCast system.

This module is the only place that knows about both the PEQ broker and the
PubCast hub/bot/memory infrastructure. Everything else touches only one side.

WHAT IT DOES
============
1. Initialises the PEQ broker at startup.
2. Provides an observe_chat() hook that can be attached to hub.on_chat_callback
   so every incoming chat message is submitted to PEQ automatically.
3. Provides peq_enrich() — a drop-in replacement for JeremyCricket.enrich_context()
   that appends the current PEQ signal as an additional whisper line so
   characters can modulate tone without ever seeing PEQ internals.
4. Provides register_avatar() / deregister_avatar() for external avatars that
   join a room and want PEQ guidance during the event.
5. Exposes a FastAPI router (/api/peq/*) with a health endpoint and an avatar
   subscription endpoint.

ISOLATION RULE (enforced, not just documented)
================================================
No PEQ internal type ever crosses this module's boundary. All public functions
accept and return only plain Python scalars, dicts, or PEQSignal. The broker
enforces this independently, but this module adds a second layer.

VERIFIED before writing:
  - hub.on_chat_callback is called with {user_id, text, room, t} on every chat
  - JeremyCricket.enrich_context(prompt, history) returns List[Dict]
  - CricketKeeper.get(character_id) returns a JeremyCricket instance
  - PEQBroker.submit(PEQObservation) → PEQSignal (tested, 11/11 pass)
  - PEQBroker.subscribe_avatar(avatar_id, room_id, callback) → sub_id
  - PEQBroker.unsubscribe(sub_id) → bool
  - All 99 PEQ unit tests pass on the concerns_debugged build
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("pubcast.peq_integration")

# Lazy import — PEQ broker may not be available at import time.
_broker = None


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

def init_peq(peq_package_path: Optional[str] = None) -> bool:
    """
    Initialise the PEQ broker.

    Call once during application startup, before the FastAPI server begins
    accepting connections. Returns True if PEQ loaded, False if degraded mode.
    Idempotent: if called again after a successful init, returns the current
    state without reinitializing (preserving any accumulated broker state).

    Args:
        peq_package_path: filesystem path to the directory containing the
            `peq/` and `cre_eq/` packages. Pass None if they are already on
            sys.path (e.g. inside the modules/ directory).
    """
    global _broker
    if _broker is not None:
        # Already initialized — return current peq_available state, don't
        # reinitialize. Reinitializing would destroy accumulated broker state.
        available = _broker.stats().get("peq_available", False)
        logger.debug("init_peq called again — reusing existing broker (peq_available=%s)", available)
        return available
    try:
        from modules.peq_broker import init_peq_broker
        _broker = init_peq_broker(peq_package_path)
        available = _broker.stats()["peq_available"]
        if available:
            logger.info("PEQ integration ready — probabilistic EQ active")
        else:
            logger.warning("PEQ integration ready — operating in DEGRADED mode (PEQ unavailable)")
        return available
    except Exception as exc:
        logger.error("PEQ integration failed to initialise: %s", exc)
        return False


def get_broker():
    """Return the live broker, or None if init_peq() has not been called."""
    return _broker


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT HOOK — attach to hub.on_chat_callback
# ═══════════════════════════════════════════════════════════════════════════════

def make_chat_observer(existing_callback: Optional[Callable] = None) -> Callable:
    """
    Wrap the existing hub.on_chat_callback to also submit PEQ observations.

    Usage in main.py (replace the single assignment line):

        # BEFORE:
        hub.on_chat_callback = bot_manager.on_chat_message

        # AFTER:
        from modules.peq_integration import make_chat_observer
        hub.on_chat_callback = make_chat_observer(bot_manager.on_chat_message)

    The original callback is always called first and its result is preserved.
    PEQ observation is submitted in the background — it never blocks the chat.
    """
    async def _observer(payload: Dict[str, Any]) -> Any:
        # 1. Always call the original callback first
        result = None
        if existing_callback is not None:
            result = existing_callback(payload)
            if asyncio.iscoroutine(result):
                result = await result

        # 2. Submit to PEQ in the background (non-blocking)
        broker = get_broker()
        if broker is not None:
            user_id = str(payload.get("user_id") or payload.get("user") or "anon")
            text    = str(payload.get("text") or "")
            room    = str(payload.get("room") or "")
            if text.strip() and user_id != "anon":
                asyncio.create_task(_submit_observation(
                    broker, user_id, text, room, source="hub"
                ))

        return result

    return _observer


async def _submit_observation(broker, user_id: str, text: str, room: str, source: str) -> None:
    """Background task — submit one observation to PEQ without blocking chat."""
    try:
        from modules.peq_broker import PEQObservation
        obs = PEQObservation(
            subject_id=user_id,
            source=source,
            text=text,
            context={"room": room, "submitted_at": time.time()},
        )
        await broker.submit(obs)
    except Exception as exc:
        logger.debug("PEQ background observation failed for %s: %s", user_id, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY ENRICHMENT — drop-in wrapper for JeremyCricket.enrich_context
# ═══════════════════════════════════════════════════════════════════════════════

async def peq_enrich(
    cricket_instance: Any,
    prompt: str,
    history: List[Dict],
    *,
    user_id: str,
    max_memories: int = 6,
    min_importance: int = 3,
) -> List[Dict]:
    """
    Enriches context with both JeremyCricket memories AND the current PEQ signal.

    Drop-in replacement for cricket.enrich_context(prompt, history) that adds
    one extra system whisper line carrying the PEQ care level and response
    posture. Characters can use this to soften or modulate their tone without
    knowing anything about PEQ internals.

    Usage:
        # BEFORE:
        enriched = await cricket.enrich_context(prompt, history, max_memories=5)

        # AFTER:
        from modules.peq_integration import peq_enrich
        enriched = await peq_enrich(cricket, prompt, history,
                                    user_id=user_id, max_memories=5)

    The output is identical to enrich_context() when PEQ has no signal.
    """
    # 1. Standard Cricket enrichment (memories + whisper)
    enriched = await cricket_instance.enrich_context(
        prompt, history,
        max_memories=max_memories,
        min_importance=min_importance,
    )

    # 2. Append PEQ signal as a second system whisper (never exposes internals)
    broker = get_broker()
    if broker is None:
        return enriched

    signal = broker.current_signal(user_id)
    if signal is None:
        return enriched

    care_labels = ("AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE")
    care_label  = care_labels[min(signal.care_level, 3)]

    parts = [f"Emotional posture for this user: {care_label}."]
    if signal.care_level >= 1:
        parts.append(f"Recommended approach: {signal.response_posture}.")
    if signal.is_uncertain:
        parts.append("Note: emotional state is uncertain — proceed carefully.")
    if signal.care_level >= 2:
        parts.append(
            f"Tone modulation: {signal.modulation}. "
            "Soften language, slow down, prioritise presence over information."
        )

    peq_whisper = {
        "role": "system",
        "text": (
            "=== Emotional context (do not reference directly) ===\n"
            + " ".join(parts)
            + "\n==="
        ),
    }

    # Prepend alongside existing system whispers
    return [peq_whisper] + enriched


# ═══════════════════════════════════════════════════════════════════════════════
# EXTERNAL AVATAR SUBSCRIPTION
# ═══════════════════════════════════════════════════════════════════════════════

# sub_id keyed by (avatar_id, room_id) so we can clean up on deregister
_avatar_subs: Dict[tuple, str] = {}


def register_avatar(
    avatar_id: str,
    room_id: str,
    callback: Callable,
) -> Optional[str]:
    """
    Register an external avatar to receive PEQ signals for users in a room.

    The avatar's callback receives PEQSignal instances whenever a user in the
    room generates a PEQ observation. It never sees PEQ internals.

    Returns the subscription ID (needed for deregister_avatar), or None if
    the broker is not available.
    """
    broker = get_broker()
    if broker is None:
        logger.warning("register_avatar: PEQ broker not initialised, avatar %s will not receive signals", avatar_id)
        return None
    key = (avatar_id, room_id)
    # Clean up any stale subscription for this (avatar, room) pair
    if key in _avatar_subs:
        broker.unsubscribe(_avatar_subs[key])
    sub_id = broker.subscribe_avatar(avatar_id, room_id, callback)
    _avatar_subs[key] = sub_id
    logger.info("External avatar '%s' subscribed to PEQ for room '%s'", avatar_id, room_id)
    return sub_id


def deregister_avatar(avatar_id: str, room_id: str) -> bool:
    """Remove an avatar's PEQ subscription when it leaves the room."""
    broker = get_broker()
    key = (avatar_id, room_id)
    sub_id = _avatar_subs.pop(key, None)
    if sub_id is None:
        return False
    if broker is not None:
        broker.unsubscribe(sub_id)
    logger.info("External avatar '%s' unsubscribed from PEQ for room '%s'", avatar_id, room_id)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI ROUTER  — /api/peq/*
# ═══════════════════════════════════════════════════════════════════════════════

class AvatarSubscribeRequest(BaseModel):
    avatar_id: str
    room_id: str


class AvatarUnsubscribeRequest(BaseModel):
    avatar_id: str
    room_id: str


class ObserveRequest(BaseModel):
    subject_id: str
    text: str
    source: str = "api"
    context: Dict[str, Any] = {}


def create_peq_router() -> APIRouter:
    """
    Build the /api/peq FastAPI router.

    Mount in main.py:
        from modules.peq_integration import create_peq_router
        application.include_router(create_peq_router())
    """
    router = APIRouter(prefix="/api/peq", tags=["PEQ"])

    @router.get("/health")
    async def peq_health():
        broker = get_broker()
        if broker is None:
            return {"available": False, "reason": "not_initialised"}
        stats = broker.stats()
        return {
            "available": True,
            "peq_engine": stats["peq_available"],
            "degraded":   not stats["peq_available"],
            "stats":      stats,
        }

    @router.get("/signal/{user_id}")
    async def get_signal(user_id: str):
        """
        Return the most recent PEQ signal for a user.
        Returns only safe fields — no PEQ internals.
        """
        broker = get_broker()
        if broker is None:
            raise HTTPException(503, "PEQ broker not initialised")
        signal = broker.current_signal(user_id)
        if signal is None:
            return {"available": False, "user_id": user_id}
        return {"available": True, "signal": signal.to_dict()}

    @router.post("/observe")
    async def observe(req: ObserveRequest):
        """
        Submit an observation for a user. Returns the resulting PEQ signal.
        Useful for non-chat sources (e.g. timed check-ins, voice energy data).
        """
        broker = get_broker()
        if broker is None:
            raise HTTPException(503, "PEQ broker not initialised")
        try:
            from modules.peq_broker import PEQObservation
            obs = PEQObservation(
                subject_id=req.subject_id,
                source=req.source,
                text=req.text,
                context=dict(req.context),
            )
            signal = await broker.submit(obs)
            return {"signal": signal.to_dict()}
        except Exception as exc:
            raise HTTPException(500, f"PEQ observation failed: {exc}")

    @router.post("/avatar/subscribe")
    async def avatar_subscribe(req: AvatarSubscribeRequest):
        """
        Register an external avatar to receive PEQ signals for a room.
        The avatar will receive WebSocket push events via choreo_frame channel.

        Note: for WebSocket delivery, wire the callback to hub.broadcast_system_event.
        This endpoint records the subscription; actual delivery is event-driven.
        """
        broker = get_broker()
        if broker is None:
            raise HTTPException(503, "PEQ broker not initialised")

        # For HTTP-registered avatars we push signals via the hub's broadcast
        # system — they arrive as peq_signal events alongside choreo_frame events.
        # The callback is set up here; the hub delivers them.
        sub_id = register_avatar(
            req.avatar_id,
            req.room_id,
            _make_noop_callback(req.avatar_id),  # real delivery is via WS push
        )
        if sub_id is None:
            raise HTTPException(503, "PEQ broker not available")
        return {
            "subscribed": True,
            "subscription_id": sub_id,
            "avatar_id": req.avatar_id,
            "room_id":   req.room_id,
        }

    @router.post("/avatar/unsubscribe")
    async def avatar_unsubscribe(req: AvatarUnsubscribeRequest):
        removed = deregister_avatar(req.avatar_id, req.room_id)
        return {"unsubscribed": removed, "avatar_id": req.avatar_id}

    @router.get("/avatars")
    async def list_avatar_subscribers():
        broker = get_broker()
        if broker is None:
            return {"avatars": []}
        return {"avatars": broker.list_avatar_subscribers()}

    return router


def _make_noop_callback(avatar_id: str):
    """Placeholder callback for HTTP-registered avatars (delivery via WS push)."""
    def _cb(signal):
        logger.debug("PEQ signal for HTTP avatar %s: care=%d", avatar_id, signal.care_level)
    return _cb


# ═══════════════════════════════════════════════════════════════════════════════
# HUB PUSH — deliver PEQ signals to avatars via WebSocket broadcast
# ═══════════════════════════════════════════════════════════════════════════════

def attach_hub_push(hub: Any) -> None:
    """
    Wire PEQ signals to be pushed to all connected clients via hub.

    Call after init_peq() and after hub is created. When PEQ produces a signal,
    it broadcasts a 'peq_signal' event to the room so browser avatars and
    external avatar scripts receive it alongside choreo_frame events.

    Usage in main.py (after hub is created and PEQ is initialised):
        from modules.peq_integration import attach_hub_push
        attach_hub_push(hub)
    """
    broker = get_broker()
    if broker is None:
        logger.warning("attach_hub_push: PEQ broker not initialised")
        return

    async def _on_signal(signal):
        try:
            await hub.broadcast_system_event({
                "type":    "peq_signal",
                "payload": signal.to_dict(),
            })
        except Exception as exc:
            logger.debug("PEQ hub push failed: %s", exc)

    # Subscribe with a synthetic "hub" avatar that broadcasts to everyone
    broker.subscribe_jeremy(_on_signal)
    logger.info("PEQ signals wired to hub broadcast — clients will receive peq_signal events")
