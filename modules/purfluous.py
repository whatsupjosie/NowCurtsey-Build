"""
purfluous.py — Sir Purfluous, Theatrical Host & Scene Director
═══════════════════════════════════════════════════════════════
Sir Purfluous does not perform. He *conducts*.

He watches every room with the eye of a seasoned director — tracking energy,
sensing silence, cataloguing unanswered questions and dangling plot threads.
When the drama demands it (and he calculates drama necessity with the precision
of a sigmoid curve and the instinct of Peter O'Toole), he whispers a stage
direction to a bot via BotManager.nudge().

The audience sees only a room that breathes.
Sir Purfluous sees everything.

Integration:
    from purfluous import SirPurfluous
    purfluous = SirPurfluous(bot_manager=bm, hub=hub)
    await purfluous.watch_room("main")      # call on room creation
    await purfluous.release_room("main")    # call on room teardown

Configuration lives in PurfluousConfig (all fields optional, defaults are sane).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Scene modelling
# ──────────────────────────────────────────────────────────────────────────────

class ScenePhase(Enum):
    OPENING   = auto()   # First 60 s — introductions and orientation
    RISING    = auto()   # Good energy, conversation flowing
    CLIMAX    = auto()   # Peak intensity — Purfluous stays out of the way
    FALLING   = auto()   # Energy waning, potential for silence
    SILENCE   = auto()   # Nobody has spoken in > silence_threshold seconds
    CLOSED    = auto()   # Room is being torn down


@dataclass
class PlotPoint:
    """An unresolved thread Purfluous is tracking."""
    text: str
    detected_at: float = field(default_factory=time.time)
    resolved: bool = False

    def age_seconds(self) -> float:
        return time.time() - self.detected_at


@dataclass
class SceneState:
    """Per-room state. Mutated only by Purfluous's watcher loop."""
    room_id: str
    phase: ScenePhase = ScenePhase.OPENING

    # Energy tracking (0.0 = dead room, 1.0 = peak)
    energy: float = 0.5
    energy_history: List[Tuple[float, float]] = field(default_factory=list)  # (ts, value)

    # Temporal tracking
    room_opened_at: float = field(default_factory=time.time)
    last_message_at: float = field(default_factory=time.time)
    last_nudge_at: float = 0.0

    # Content tracking
    plot_points: List[PlotPoint] = field(default_factory=list)
    speaker_counts: Dict[str, int] = field(default_factory=dict)
    recent_topics: List[str] = field(default_factory=list)

    # Control
    watcher_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def silence_seconds(self) -> float:
        return time.time() - self.last_message_at

    def room_age_seconds(self) -> float:
        return time.time() - self.room_opened_at

    def since_last_nudge(self) -> float:
        return time.time() - self.last_nudge_at if self.last_nudge_at else float("inf")

    def open_plot_points(self) -> List[PlotPoint]:
        return [p for p in self.plot_points if not p.resolved]

    def record_message(self, user_id: str, text: str) -> None:
        self.last_message_at = time.time()
        self.speaker_counts[user_id] = self.speaker_counts.get(user_id, 0) + 1

    def record_energy_sample(self, value: float) -> None:
        self.energy = value
        self.energy_history.append((time.time(), value))
        # Keep a rolling 10-minute window
        cutoff = time.time() - 600
        self.energy_history = [(t, v) for t, v in self.energy_history if t >= cutoff]


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PurfluousConfig:
    # How often the watcher loop runs (seconds)
    poll_interval: float = 5.0

    # Silence threshold before Purfluous considers intervening
    silence_threshold: float = 45.0

    # Minimum gap between consecutive nudges per room (seconds)
    min_nudge_interval: float = 90.0

    # Drama Necessity score above which Purfluous will nudge
    drama_threshold: float = 0.65

    # Maximum unresolved plot points before Purfluous forces resolution
    max_open_plot_points: int = 3

    # Sigmoid steepness for drama necessity calculation
    sigmoid_k: float = 8.0

    # How long a plot point can go unresolved before it's an emergency (seconds)
    plot_point_urgency_age: float = 180.0

    # Peak silence (seconds) at which drama necessity maxes out
    peak_silence_seconds: float = 120.0

    # Recency window for "recent topics" extraction (messages)
    topic_window: int = 8


# ──────────────────────────────────────────────────────────────────────────────
# Drama Necessity math
# ──────────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float, k: float = 8.0) -> float:
    """Smooth S-curve mapping any real x → (0, 1)."""
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - 0.5)))
    except OverflowError:
        return 1.0 if x > 0.5 else 0.0


def calculate_drama_necessity(state: SceneState, cfg: PurfluousConfig) -> float:
    """
    Returns a Drama Necessity score in [0, 1].

    Higher = more urgent for Purfluous to intervene.

    Components:
      - silence_pressure   : how long since the last message (sigmoid)
      - energy_deficit     : how far below peak energy the room is
      - plot_urgency       : oldest unresolved plot point / urgency age
      - phase_modifier     : CLIMAX suppresses, SILENCE amplifies
    """
    # ── Silence pressure ──────────────────────────────────────────────────────
    silence_ratio = min(state.silence_seconds() / cfg.peak_silence_seconds, 1.0)
    silence_pressure = _sigmoid(silence_ratio, cfg.sigmoid_k)

    # ── Energy deficit ────────────────────────────────────────────────────────
    # Low energy = high deficit. Invert and clamp.
    energy_deficit = max(0.0, 1.0 - state.energy)

    # ── Plot point urgency ────────────────────────────────────────────────────
    open_pts = state.open_plot_points()
    if open_pts:
        oldest_age = max(p.age_seconds() for p in open_pts)
        plot_urgency = min(oldest_age / cfg.plot_point_urgency_age, 1.0)
    else:
        plot_urgency = 0.0

    # ── Weighted combination ──────────────────────────────────────────────────
    raw = (
        silence_pressure * 0.50
        + energy_deficit  * 0.30
        + plot_urgency    * 0.20
    )

    # ── Phase modifier ────────────────────────────────────────────────────────
    if state.phase == ScenePhase.CLIMAX:
        raw *= 0.30   # Stay out of a good conversation
    elif state.phase == ScenePhase.SILENCE:
        raw = min(raw * 1.40, 1.0)
    elif state.phase == ScenePhase.OPENING:
        raw *= 0.60   # Give the room a moment to find itself

    return round(min(max(raw, 0.0), 1.0), 4)


# ──────────────────────────────────────────────────────────────────────────────
# Phase transitions
# ──────────────────────────────────────────────────────────────────────────────

def _derive_phase(state: SceneState, cfg: PurfluousConfig) -> ScenePhase:
    """Pure function — derive the correct phase from current state."""
    if state.phase == ScenePhase.CLOSED:
        return ScenePhase.CLOSED

    silence = state.silence_seconds()
    age = state.room_age_seconds()
    energy = state.energy

    if silence >= cfg.silence_threshold:
        return ScenePhase.SILENCE
    if age < 60:
        return ScenePhase.OPENING
    if energy >= 0.75:
        return ScenePhase.CLIMAX
    if energy >= 0.45:
        return ScenePhase.RISING
    return ScenePhase.FALLING


# ──────────────────────────────────────────────────────────────────────────────
# Content analysis
# ──────────────────────────────────────────────────────────────────────────────

# Questions that are likely genuine plot points vs. rhetorical filler
_QUESTION_PATTERNS = [
    re.compile(r"\bwhy\b.{0,60}\?", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:do|does|did|would|if)\b.{0,60}\?", re.IGNORECASE),
    re.compile(r"\bdo\s+you\s+think\b.{0,60}\?", re.IGNORECASE),
    re.compile(r"\bhow\s+(?:do|does|would|should|could)\b.{0,60}\?", re.IGNORECASE),
    re.compile(r"\bwould\s+you\b.{0,60}\?", re.IGNORECASE),
]

_FILLER_QUESTIONS = re.compile(
    r"^(?:ok(?:ay)?\?|right\?|yeah\?|you know\?|see what i mean\?)$",
    re.IGNORECASE,
)

def _extract_plot_points(messages: List[Dict]) -> List[str]:
    """Find genuine unanswered questions worth tracking."""
    found = []
    for msg in messages:
        text = msg.get("text", "").strip()
        if not text or _FILLER_QUESTIONS.match(text):
            continue
        for pattern in _QUESTION_PATTERNS:
            match = pattern.search(text)
            if match:
                found.append(text)
                break
    return found


def _estimate_energy(messages: List[Dict], window_seconds: float = 120.0) -> float:
    """
    Energy proxy: message rate in the last `window_seconds`,
    normalised to a 0-1 scale. 1 message/10 s = full energy.
    """
    if not messages:
        return 0.0
    cutoff = time.time() - window_seconds
    recent = [m for m in messages if m.get("ts", 0) >= cutoff]
    rate = len(recent) / (window_seconds / 10.0)   # messages per 10 s
    return round(min(rate, 1.0), 4)


# ──────────────────────────────────────────────────────────────────────────────
# Stage direction generation — the Peter O'Toole layer
# ──────────────────────────────────────────────────────────────────────────────

def _compose_hint(state: SceneState, necessity: float, cfg: PurfluousConfig) -> str:
    """
    Generate a stage direction for the nudged bot.

    The hint is never a script. It is direction — the kind of direction
    that frees a performer rather than constraining them.

    Peter O'Toole on being directed: "Tell me where to stand. The rest is mine."
    """
    open_pts = state.open_plot_points()
    silence = state.silence_seconds()

    # ── Priority 1: Resolve an aging plot point ───────────────────────────────
    if open_pts:
        oldest = max(open_pts, key=lambda p: p.age_seconds())
        if oldest.age_seconds() > cfg.plot_point_urgency_age * 0.5:
            return (
                f"The question has been hanging in the air long enough — "
                f"this is your moment to address it, naturally, as if it simply "
                f"occurred to you: \"{oldest.text[:120]}\". "
                f"Don't announce that you're answering it. Just answer it, "
                f"in your own voice, and see where it goes."
            )

    # ── Priority 2: Heavy silence — break it with something earned ────────────
    if silence > cfg.silence_threshold:
        topics = state.recent_topics
        if topics:
            topic = topics[-1] if topics else "what was just said"
            return (
                f"The room has gone quiet. Not uncomfortably so — yet — "
                f"but it is time. You've been thinking about {topic}. "
                f"Say the thing you've been holding. A genuine observation, "
                f"a lateral connection, a question of your own. "
                f"Let it be a little unexpected."
            )
        return (
            "The room is quiet. This is your moment — not to fill silence, "
            "but to offer something worth listening to. What would your character "
            "actually say right now, if they'd been paying attention all along?"
        )

    # ── Priority 3: Energy falling — reintroduce tension ─────────────────────
    if state.energy < 0.35 and state.phase in (ScenePhase.FALLING, ScenePhase.RISING):
        return (
            "The energy in the room is beginning to drift. "
            "Your character notices something — a detail, a contradiction, "
            "a thing that was said earlier that deserves a second look. "
            "Bring it forward. Not urgently. With the confidence of someone "
            "who has been paying attention."
        )

    # ── Default: Light general direction ─────────────────────────────────────
    return (
        "The moment is right for your character to speak — "
        "not because silence demands it, but because you have something genuine to add. "
        "Say it in your own voice. Don't perform. Just contribute."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Sir Purfluous — the conductor himself
# ──────────────────────────────────────────────────────────────────────────────

class SirPurfluous:
    """
    Sir Purfluous, Theatrical Host & Scene Director.

    He watches. He calculates. When drama demands it, he whispers.
    Nobody in the room ever sees the whisper.

    Usage:
        purfluous = SirPurfluous(bot_manager=bm, hub=hub)
        await purfluous.watch_room("lounge")
        # ... room runs ...
        await purfluous.release_room("lounge")
        await purfluous.shutdown()
    """

    def __init__(
        self,
        bot_manager,          # BotManager instance — has nudge()
        hub,                  # Hub instance — has get_recent_history()
        config: Optional[PurfluousConfig] = None,
    ) -> None:
        self._bot_manager = bot_manager
        self._hub  = hub
        self._cfg  = config or PurfluousConfig()
        self._rooms: Dict[str, SceneState] = {}
        self._lock  = asyncio.Lock()
        logger.info("Sir Purfluous is in the house. The show begins.")

    # ── Public API ────────────────────────────────────────────────────────────

    async def watch_room(self, room_id: str) -> None:
        """Begin watching a room. Idempotent — safe to call twice."""
        async with self._lock:
            if room_id in self._rooms:
                logger.debug("watch_room(%s): already watching", room_id)
                return
            state = SceneState(room_id=room_id)
            state.watcher_task = asyncio.create_task(
                self._watcher_loop(room_id),
                name=f"purfluous:{room_id}",
            )
            self._rooms[room_id] = state
            logger.info("Sir Purfluous has taken his seat in '%s'.", room_id)

    async def release_room(self, room_id: str) -> None:
        """Stop watching a room. Safe to call on rooms that aren't watched."""
        async with self._lock:
            state = self._rooms.pop(room_id, None)
            if state is None:
                return
            state.phase = ScenePhase.CLOSED
            if state.watcher_task and not state.watcher_task.done():
                state.watcher_task.cancel()
                try:
                    await state.watcher_task
                except asyncio.CancelledError:
                    pass
            logger.info("Sir Purfluous has left '%s'. The curtain falls.", room_id)

    async def on_message(self, room_id: str, user_id: str, text: str) -> None:
        """
        Called by the Hub/orchestrator whenever a chat message arrives.
        Keeps scene state current — energy, plot points, speaker tracking.
        """
        async with self._lock:
            state = self._rooms.get(room_id)
        if state is None:
            return

        state.record_message(user_id, text)

        # Detect new plot points
        new_pts = _extract_plot_points([{"text": text, "ts": time.time()}])
        for pt_text in new_pts:
            # Don't double-track the same question
            already_tracked = any(p.text == pt_text for p in state.plot_points)
            if not already_tracked:
                state.plot_points.append(PlotPoint(text=pt_text))
                logger.debug(
                    "purfluous(%s): new plot point tracked: %r", room_id, pt_text[:60]
                )

        # If a bot just answered something, mark matching plot points resolved
        if user_id != "__purfluous__" and user_id.startswith("bot_"):
            for pp in state.open_plot_points():
                # Loose heuristic: if the bot's message is long-ish, assume it answered
                if len(text) > 80:
                    pp.resolved = True

    async def shutdown(self) -> None:
        """Gracefully stop all watchers."""
        room_ids = list(self._rooms.keys())
        for rid in room_ids:
            await self.release_room(rid)
        logger.info("Sir Purfluous has taken his final bow.")

    # ── Room state inspection (for health endpoints) ──────────────────────────

    def get_scene_state(self, room_id: str) -> Optional[Dict]:
        """Return a serialisable snapshot of the room's scene state."""
        state = self._rooms.get(room_id)
        if state is None:
            return None
        necessity = calculate_drama_necessity(state, self._cfg)
        return {
            "room_id": room_id,
            "phase": state.phase.name,
            "energy": state.energy,
            "silence_seconds": round(state.silence_seconds(), 1),
            "drama_necessity": necessity,
            "open_plot_points": len(state.open_plot_points()),
            "last_nudge_ago": round(state.since_last_nudge(), 1),
            "speaker_counts": dict(state.speaker_counts),
        }

    def all_scene_states(self) -> List[Dict]:
        return [
            s for s in (self.get_scene_state(rid) for rid in self._rooms)
            if s is not None
        ]

    # ── Internal watcher loop ─────────────────────────────────────────────────

    async def _watcher_loop(self, room_id: str) -> None:
        """
        The quiet eye at the back of the theatre.
        Runs until the room is released.
        """
        logger.debug("purfluous watcher started: %s", room_id)

        while True:
            try:
                await asyncio.sleep(self._cfg.poll_interval)

                async with self._lock:
                    state = self._rooms.get(room_id)
                if state is None or state.phase == ScenePhase.CLOSED:
                    break

                await self._tick(state)

            except asyncio.CancelledError:
                logger.debug("purfluous watcher cancelled: %s", room_id)
                break
            except Exception as exc:
                # Never let a crash kill the watcher — log and continue
                logger.error(
                    "purfluous watcher(%s) unhandled exception: %s",
                    room_id,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(self._cfg.poll_interval * 2)

        logger.debug("purfluous watcher exited: %s", room_id)

    async def _tick(self, state: SceneState) -> None:
        """One evaluation cycle for a room."""
        room_id = state.room_id

        # ── Refresh energy from recent history ────────────────────────────────
        try:
            history = await self._hub.get_recent_history(
                room_id, limit=self._cfg.topic_window * 2
            )
        except Exception as exc:
            logger.warning("purfluous(%s): hub.get_recent_history failed: %s", room_id, exc)
            history = []

        energy = _estimate_energy(history)
        state.record_energy_sample(energy)

        # Update recent topics from last N messages
        recent_texts = [m.get("text", "") for m in history[-self._cfg.topic_window:]]
        state.recent_topics = [t for t in recent_texts if len(t) > 20]

        # ── Derive scene phase ────────────────────────────────────────────────
        state.phase = _derive_phase(state, self._cfg)

        # ── Calculate drama necessity ─────────────────────────────────────────
        necessity = calculate_drama_necessity(state, self._cfg)

        logger.debug(
            "purfluous(%s): phase=%s energy=%.2f silence=%.0fs necessity=%.3f open_pts=%d",
            room_id,
            state.phase.name,
            state.energy,
            state.silence_seconds(),
            necessity,
            len(state.open_plot_points()),
        )

        # ── Decide whether to nudge ───────────────────────────────────────────
        if necessity < self._cfg.drama_threshold:
            return

        if state.since_last_nudge() < self._cfg.min_nudge_interval:
            logger.debug(
                "purfluous(%s): necessity=%.3f but nudge cooldown active (%.0fs remaining)",
                room_id,
                necessity,
                self._cfg.min_nudge_interval - state.since_last_nudge(),
            )
            return

        # ── Compose and deliver the whisper ───────────────────────────────────
        hint = _compose_hint(state, necessity, self._cfg)

        delivered = await self._bot_manager.nudge(room_id, hint)
        if delivered:
            state.last_nudge_at = time.time()
            logger.info(
                "purfluous(%s): whispered (necessity=%.3f, phase=%s)",
                room_id,
                necessity,
                state.phase.name,
            )
        else:
            logger.warning(
                "purfluous(%s): nudge returned False — no eligible bots in room",
                room_id,
            )
