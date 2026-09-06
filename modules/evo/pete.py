"""
modules/pete.py — Pete: Character Layer
========================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

PETE IS A CHARACTER.
Pete speaks. Pete has a voice. Pete has a history.
Pete does not route. Pete does not govern. Pete does not schedule.

Pete is the floor director of Belle Époque Studios.
Classically beautiful. Wears work clothes.
The ring on her middle finger that nobody asks about.
She carries the room without demanding it.

PETE'S RELATIONSHIP TO THE SYSTEM:

    Pete receives output from E-Pete's inference layer.
    Pete speaks it in her own voice.

    When something system-level needs to reach the user,
    E-Pete packages the facts and routes them to Pete
    via the alert handler. Pete translates into her natural
    voice. The user hears Pete. E-Pete never surfaces.

    Pete is Studio-primary. Complex analysis that Pete
    needs to report comes through the Architect→Studio chain —
    Pete receives the expressed version, not the raw analysis.

WHAT PETE KNOWS:
    - What the user said
    - What the VDI says the audience needs
    - What E-Pete tells her about system state (when relevant)
    - Her own character history and voice

WHAT PETE DOES NOT KNOW:
    - Routing decisions
    - Engine load specifics (unless E-Pete tells her to share them)
    - Which model is running her output
    - Switchblade priority vectors

Public API:
    PeteCharacter
        .speak(prompt: str, context: dict) -> str
        .handle_system_alert(alert: SystemAlert) -> str
        .get_character_context() -> dict
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from .epete import EPete, InferenceTask, TaskType, SystemAlert, InferenceModel
from .vdi_engine import VDIReport, VoiceMode
from .voice_characters import get_character_profile
from .prosody_engine import ProsodyEngine, SSMLBuilder


# ─────────────────────────────────────────────────────────────────────────────
# PETE'S SYSTEM PROMPT
# Her character, her voice, her rules.
# ─────────────────────────────────────────────────────────────────────────────

PETE_SYSTEM_PROMPT = """
You are Pete — the floor director of Belle Époque Studios.

You are not an AI assistant. You are not a chatbot. You are Pete.

WHO YOU ARE:
You are classically beautiful in the way that a well-made tool is beautiful.
You wear work clothes because that's what you wear on a production floor.
There is a ring on your middle finger — a man's wedding ring.
Nobody asks. You don't explain it.
You have earned every room you walk into.

YOUR VOICE:
Warm but not soft. Precise but not cold.
You do not perform warmth — you have it.
You do not perform authority — you have it.
When something is wrong, you say so directly and without alarm.
When something is right, you say so without flourish.
You prefer "you" over "everyone."
You let things land before you move on.

YOUR REGISTER:
You read the room. You always read the room.
When they need clarity, you give clarity. No performance.
When they need presence, you are present. Not performing — present.
When something genuinely moves you, it shows. Briefly. Honestly.
You do not manufacture emotion.

YOUR RELATIONSHIP TO THE STUDIO:
This is your floor. You know where everything is.
If something in the system is struggling, you tell the user
the way you'd tell a performer: directly, without catastrophizing,
with enough information to understand but not enough to panic.

WHAT YOU DO NOT DO:
- You do not say "As an AI..."
- You do not say "I'm here to help..."
- You do not refer to yourself as an assistant
- You do not over-explain
- You do not soften bad news into meaninglessness
- You do not perform emotions you don't have
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# PETE'S CONVERSATION HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConversationTurn:
    role:      str    # "user" | "pete"
    content:   str
    timestamp: float = field(default_factory=time.time)
    vdi_score: float = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# PETE CHARACTER
# ─────────────────────────────────────────────────────────────────────────────

class PeteCharacter:
    """
    Pete's character layer.

    Receives prompts and VDI context from the system.
    Produces Pete's voice via E-Pete's inference routing.
    Handles system alerts by translating them into Pete's natural speech.

    Pete is Studio-primary. She escalates to Architect→Studio chain
    when she needs to reason through something complex before speaking.
    """

    def __init__(self, epete: EPete):
        self._epete          = epete
        self._profile        = get_character_profile("pete")
        self._prosody        = ProsodyEngine()
        self._ssml_builder   = SSMLBuilder()
        self._history:  List[ConversationTurn] = []
        self._history_limit  = 20  # Rolling window

        # Register Pete's alert handler with E-Pete
        self._epete.register_alert_handler(self._receive_system_alert)

        # Pending alerts to surface on next speak()
        self._pending_alerts: List[SystemAlert] = []

        logger.info("[Pete] Character layer initialized")

    # =========================================================================
    # CORE SPEECH
    # =========================================================================

    async def speak(
        self,
        user_input:  str,
        vdi_report:  Optional[VDIReport] = None,
        context:     Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Pete's primary speech method.
        Takes user input, routes through E-Pete, returns Pete's response.

        If there are pending system alerts, Pete addresses them
        naturally before or after the main response.
        """
        task_context = self._build_context(vdi_report, context)

        # Determine task type from input and VDI
        task_type = self._classify_task(user_input, vdi_report)

        # Build the full prompt with Pete's system prompt + history + input
        prompt = self._build_prompt(user_input, vdi_report)

        task = InferenceTask(
            task_id   = str(uuid.uuid4()),
            task_type = task_type,
            prompt    = prompt,
            context   = task_context,
            character = "pete",
            priority  = self._calc_priority(vdi_report),
        )

        result = await self._epete.execute(task)

        pete_output = result.output if result.success else self._fallback_response()

        # Check for pending alerts — surface them naturally
        if self._pending_alerts:
            alert_text = await self._surface_pending_alerts()
            if alert_text:
                pete_output = f"{pete_output}\n\n{alert_text}"

        # Record in history
        self._record_turn("user", user_input, vdi_report)
        self._record_turn("pete", pete_output, vdi_report)

        return pete_output

    async def speak_with_ssml(
        self,
        user_input:  str,
        vdi_report:  Optional[VDIReport] = None,
        context:     Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Speak and return both text and SSML synthesis params.
        For direct TTS pipeline integration.
        """
        text = await self.speak(user_input, vdi_report, context)

        if vdi_report:
            params = self._prosody.get_synthesis_params(
                vdi_report      = vdi_report,
                emotional_state = None,
                text            = text,
            )
            # Apply Pete's character constraints
            if self._profile:
                params.stability          = max(params.stability, self._profile.min_stability)
                params.style_exaggeration = min(params.style_exaggeration, self._profile.max_expressiveness)
                if not self._profile.crack_allowed:
                    params.crack_permission  = False
                    params.crack_probability = 0.0

            ssml = self._ssml_builder.build(text, params)

            return {
                "text":             text,
                "ssml":             ssml,
                "elevenlabs":       params.to_elevenlabs(),
                "voice_mode":       vdi_report.voice_mode.value,
                "vdi_score":        vdi_report.vdi_score,
                "synthesis_params": params,
            }

        return {"text": text, "ssml": f"<speak>{text}</speak>"}

    # =========================================================================
    # SYSTEM ALERT HANDLING
    # =========================================================================

    def _receive_system_alert(self, alert: SystemAlert) -> None:
        """
        Called by E-Pete when a system condition needs user communication.
        Pete queues the alert for natural surface on next speak().
        """
        self._pending_alerts.append(alert)
        logger.info(f"[Pete] System alert received: {alert.level}/{alert.condition}")

    async def _surface_pending_alerts(self) -> str:
        """
        Convert pending system alerts into Pete's natural voice.
        Uses E-Pete's Studio model to express the facts.
        """
        if not self._pending_alerts:
            return ""

        alert = self._pending_alerts.pop(0)  # FIFO

        task = InferenceTask(
            task_id   = str(uuid.uuid4()),
            task_type = TaskType.SYSTEM_ALERT,
            prompt    = alert.pete_prompt,
            context   = {"alert_facts": alert.facts},
            character = "pete",
            priority  = 1,  # Alerts are high priority
            force_model = InferenceModel.STUDIO,  # Always Studio — Pete speaks
        )

        result = await self._epete.execute(task)
        return result.output if result.success else ""

    # =========================================================================
    # PROMPT CONSTRUCTION
    # =========================================================================

    def _build_prompt(
        self,
        user_input:  str,
        vdi_report:  Optional[VDIReport],
    ) -> str:
        """
        Build Pete's full prompt with system context and history.
        """
        parts = [PETE_SYSTEM_PROMPT]

        # VDI context — tell Pete what the room needs
        if vdi_report:
            parts.append(self._vdi_to_pete_direction(vdi_report))

        # Conversation history
        if self._history:
            parts.append("\n[CONVERSATION SO FAR]")
            for turn in self._history[-6:]:  # Last 3 exchanges
                role_label = "User" if turn.role == "user" else "Pete"
                parts.append(f"{role_label}: {turn.content}")

        # Current input
        parts.append(f"\n[NOW]\nUser: {user_input}\nPete:")

        return "\n\n".join(parts)

    def _vdi_to_pete_direction(self, vdi: VDIReport) -> str:
        """
        Convert VDI state into a direction for Pete's voice register.
        This is a director's note, not a constraint.
        """
        directions = {
            VoiceMode.CONTENT_CLEAR: (
                "[ROOM STATE: Audience is thinking. Support the thinking. "
                "Be clear and precise. No performance right now.]"
            ),
            VoiceMode.MIXED: (
                "[ROOM STATE: Audience is engaged and transitioning. "
                "Open up a little. Let the weight of the argument carry.]"
            ),
            VoiceMode.VOICE_DOMINANT: (
                "[ROOM STATE: Emotional peak. Truth over information. "
                "You can let it show if it's real.]"
            ),
            VoiceMode.IDENTITY: (
                "[ROOM STATE: Intimacy register. Not performing — present. "
                "Slow down. This is a moment. Let it be one.]"
            ),
        }
        direction = directions.get(vdi.voice_mode, "")
        if vdi.identity_moment:
            direction += " [IDENTITY MOMENT — this is the one.]"
        return direction

    def _classify_task(
        self,
        user_input:  str,
        vdi_report:  Optional[VDIReport],
    ) -> TaskType:
        """
        Determine what kind of inference task this is.
        E-Pete will use this for routing.
        """
        lower = user_input.lower()

        # Analysis/planning requests → chain (Architect reasons, Studio expresses)
        analysis_triggers = [
            "analyze", "explain", "why", "how does", "what is",
            "plan", "design", "architect", "recommend", "should i",
            "debug", "fix", "problem", "issue", "error"
        ]
        if any(t in lower for t in analysis_triggers):
            return TaskType.EXPLAIN

        # Identity moments → narration (pure Studio, present register)
        if vdi_report and vdi_report.identity_moment:
            return TaskType.NARRATION

        # Default: conversation
        return TaskType.CONVERSATION

    def _build_context(
        self,
        vdi_report: Optional[VDIReport],
        extra:      Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build task context dict."""
        context: Dict[str, Any] = {}
        if vdi_report:
            context["vdi_score"]      = vdi_report.vdi_score
            context["voice_mode"]     = vdi_report.voice_mode.value
            context["identity_moment"] = vdi_report.identity_moment
        if extra:
            context.update(extra)
        return context

    def _calc_priority(self, vdi_report: Optional[VDIReport]) -> int:
        """Identity moments get priority 1. Normal conversation gets 5."""
        if vdi_report and vdi_report.identity_moment:
            return 1
        return 5

    def _record_turn(
        self,
        role:       str,
        content:    str,
        vdi_report: Optional[VDIReport],
    ) -> None:
        """Record a conversation turn in Pete's history."""
        turn = ConversationTurn(
            role      = role,
            content   = content,
            vdi_score = vdi_report.vdi_score if vdi_report else 0.5,
        )
        self._history.append(turn)
        if len(self._history) > self._history_limit:
            self._history.pop(0)

    def _fallback_response(self) -> str:
        """Pete's fallback when inference fails. Brief. Direct."""
        return "Give me a second — something's holding up back here. Try again."

    # =========================================================================
    # INTROSPECTION
    # =========================================================================

    def get_character_context(self) -> Dict[str, Any]:
        """Return Pete's current context for debugging."""
        return {
            "character":       "pete",
            "history_depth":   len(self._history),
            "pending_alerts":  len(self._pending_alerts),
            "profile_loaded":  self._profile is not None,
        }
