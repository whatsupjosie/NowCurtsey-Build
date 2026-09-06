"""
modules/epete.py — E-Pete: Engine Pete, Inference Router & System Governor
===========================================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

E-PETE IS NOT A CHARACTER.
E-Pete does not speak.
E-Pete does not roleplay.
E-Pete does not have a personality.

E-Pete is the inference routing and system governance layer.
She decides which brain handles which task, when to escalate,
when to throttle, and when to alert the character layer about
system conditions that affect the user.

THREE LAYERS — CLEAR AUTHORITY:

    CHARACTER LAYER     Pete (Studio output, voice, persona)
                              ↑ receives formatted output
    ─────────────────────────────────────────────────────────
    ENGINE LAYER        E-Pete (THIS MODULE)
                        Routes. Governs. Escalates. Silent.
    ─────────────────────────────────────────────────────────
    INFERENCE LAYER     Studio  (Gemma small — expression)
                        Architect (Gemma large — reasoning)

E-PETE'S FIVE JOBS:

    A. ROUTING
       Decides: Studio / Architect / Architect→Studio chain
       Based on: task type, complexity, system load

    B. FLOW CONTROL
       Can delay, throttle, defer, or skip tasks
       Maintains pacing and system coherence

    C. SYSTEM AWARENESS
       Monitors: load, response timing, failures, IRM state
       Reads from: DistributedEngineNode, SwitchbladeGovernor

    D. ESCALATION
       If a system condition is dangerous or user-affecting,
       E-Pete formats a system alert and passes it to Pete
       (character layer) so Pete can inform the user naturally.
       Pete speaks it. E-Pete wrote the fact, not the words.

    E. DELEGATION
       Assigns tasks to inference layer.
       Does NOT perform inference itself.

PETE'S RELATIONSHIP TO E-PETE:

    Pete is Studio-primary.
    Pete receives E-Pete's routed output and speaks it.

    When something system-level needs to reach the user
    (bottleneck, slowdown, dangerous load state), E-Pete
    packages the facts and routes them to Pete via
    the SYSTEM_ALERT channel. Pete translates into
    her natural voice. The user hears Pete. E-Pete
    never surfaces.

INFERENCE MODELS (Zoidberg configuration):

    Studio:    Gemma small variant  — fast, expressive, conversational
    Architect: Gemma large variant  — slower, structured, analytical
    Concurrency cap: 1 concurrent GGUF call (Zoidberg GTX 960M constraint)

Public API:
    EPete
        .route(task: InferenceTask) -> RoutingDecision
        .execute(task: InferenceTask) -> InferenceResult
        .get_system_status() -> SystemStatus
        .register_alert_handler(handler: Callable) -> None
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class InferenceModel(str, Enum):
    STUDIO    = "studio"     # Gemma small — fast, expressive, conversational
    ARCHITECT = "architect"  # Gemma large — structured, analytical
    CHAIN     = "chain"      # Architect → Studio (reason then express)


# ─────────────────────────────────────────────────────────────────────────────
# TASK TYPES — what kind of work is being asked for
# ─────────────────────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    # Studio tasks — expression, conversation, persona
    CONVERSATION     = "conversation"     # Normal user interaction
    NARRATION        = "narration"        # Pete narrating/presenting
    REACTION         = "reaction"         # Pete reacting to something
    SYSTEM_ALERT     = "system_alert"     # E-Pete → Pete: tell user about system state

    # Architect tasks — analysis, planning, structure
    ANALYSIS         = "analysis"         # Deep reasoning required
    PLANNING         = "planning"         # Multi-step planning
    STRUCTURED_DATA  = "structured_data"  # JSON/structured output needed
    TROUBLESHOOT     = "troubleshoot"     # Debugging / diagnosis

    # Chain tasks — reason then express
    EXPLAIN          = "explain"          # Architect reasons, Studio expresses
    RECOMMEND        = "recommend"        # Architect evaluates, Studio delivers
    ESCALATION       = "escalation"       # Architect assesses risk, Studio alerts


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING POLICY — rules E-Pete uses to assign models
# ─────────────────────────────────────────────────────────────────────────────

# Default routing table — task type → preferred model
_DEFAULT_ROUTING: Dict[TaskType, InferenceModel] = {
    TaskType.CONVERSATION:    InferenceModel.STUDIO,
    TaskType.NARRATION:       InferenceModel.STUDIO,
    TaskType.REACTION:        InferenceModel.STUDIO,
    TaskType.SYSTEM_ALERT:    InferenceModel.STUDIO,    # Pete speaks it
    TaskType.ANALYSIS:        InferenceModel.ARCHITECT,
    TaskType.PLANNING:        InferenceModel.ARCHITECT,
    TaskType.STRUCTURED_DATA: InferenceModel.ARCHITECT,
    TaskType.TROUBLESHOOT:    InferenceModel.ARCHITECT,
    TaskType.EXPLAIN:         InferenceModel.CHAIN,
    TaskType.RECOMMEND:       InferenceModel.CHAIN,
    TaskType.ESCALATION:      InferenceModel.CHAIN,
}


# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE TASK — what E-Pete receives
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InferenceTask:
    """
    A unit of inference work submitted to E-Pete for routing.
    """
    task_id:      str
    task_type:    TaskType
    prompt:       str
    context:      Dict[str, Any]  = field(default_factory=dict)
    character:    str             = "pete"
    priority:     int             = 5              # 1=highest, 10=lowest
    deadline_ms:  float           = 5000.0         # Must complete within (ms)
    force_model:  Optional[InferenceModel] = None  # Override routing if set
    created_at:   float           = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING DECISION — what E-Pete decides
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """
    E-Pete's routing decision for an inference task.
    """
    task_id:        str
    assigned_model: InferenceModel
    reason:         str            # For logging only — never surfaces to user
    estimated_ms:   float          = 1000.0
    deferred:       bool           = False   # True = task was queued, not immediate
    degraded:       bool           = False   # True = running at reduced capacity
    timestamp:      float          = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE RESULT — what comes back from the model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    """
    Complete result of an inference execution.
    """
    task_id:        str
    model_used:     InferenceModel
    output:         str            # The model's text output
    character_output: str          = ""   # Pete-formatted version (if applicable)
    tokens_used:    int            = 0
    latency_ms:     float          = 0.0
    success:        bool           = True
    error:          Optional[str]  = None
    routing:        Optional[RoutingDecision] = None
    timestamp:      float          = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM STATUS — what E-Pete sees about the system
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SystemStatus:
    """
    Current system health as seen by E-Pete.
    Aggregated from IRM, distributed engine, and Switchblade.
    """
    # Load
    inference_load:     float = 0.0    # 0-100%
    render_load:        float = 0.0
    audio_healthy:      bool  = True

    # Queue
    pending_tasks:      int   = 0
    queue_depth_ms:     float = 0.0    # Estimated total queue time

    # Models
    studio_available:   bool  = True
    architect_available: bool = True
    active_model:       Optional[InferenceModel] = None

    # Engine state
    engine_state:       str   = "normal"   # normal/elevated/critical/emergency
    vdi_score:          float = 0.5
    identity_moment:    bool  = False

    # Alerts
    has_alert:          bool  = False
    alert_level:        str   = "none"     # none/info/warning/critical
    alert_message:      str   = ""

    timestamp:          float = field(default_factory=time.time)

    def is_degraded(self) -> bool:
        return self.engine_state in ("critical", "emergency")

    def needs_user_alert(self) -> bool:
        return self.alert_level in ("warning", "critical")


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM ALERT — packaged for Pete to deliver
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SystemAlert:
    """
    A system condition that needs to reach the user.
    E-Pete packages the facts. Pete translates into her voice.
    """
    level:        str    # info | warning | critical
    condition:    str    # machine-readable condition name
    facts:        Dict[str, Any] = field(default_factory=dict)
    pete_prompt:  str    = ""   # Prompt for Pete's character layer
    timestamp:    float  = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# E-PETE
# ─────────────────────────────────────────────────────────────────────────────

class EPete:
    """
    Engine Pete — Inference Router & System Governor.

    E-Pete is the silent authority between the character layer and
    the inference layer. She routes, governs, monitors, and escalates.
    She never speaks. She never appears. She runs the room from
    the inside so Pete can run it on the outside.

    Zoidberg constraint: 1 concurrent GGUF call.
    E-Pete enforces this via an asyncio.Semaphore(1).
    """

    def __init__(
        self,
        studio_model_id:    str = "gemma-studio",
        architect_model_id: str = "gemma-architect",
        llm_backend: Optional[Any] = None,   # LLM framework instance
    ):
        self.studio_model_id    = studio_model_id
        self.architect_model_id = architect_model_id
        self._llm               = llm_backend

        # Zoidberg: 1 concurrent GGUF call — hard constraint
        self._inference_semaphore = asyncio.Semaphore(1)

        # Task queue (priority queue via list + sort)
        self._task_queue: List[InferenceTask] = []
        self._queue_lock  = asyncio.Lock()

        # System state references (set via register_*)
        self._engine_node   = None   # DistributedEngineNode
        self._switchblade   = None   # SwitchbladeGovernor
        self._evo           = None   # EVOOrchestrator

        # Alert handlers (Pete's character layer registers here)
        self._alert_handlers: List[Callable[[SystemAlert], None]] = []

        # Metrics
        self._total_routed      = 0
        self._studio_count      = 0
        self._architect_count   = 0
        self._chain_count       = 0
        self._total_latency_ms  = 0.0
        self._failures          = 0

        # Alert deduplication — prevent spam
        # Maps condition -> last fire timestamp
        self._alert_last_fired: Dict[str, float] = {}
        self._alert_cooldown_s: float = 30.0  # Same alert won't fire within 30s

        # Running
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

        logger.info("[E-Pete] Initialized — Zoidberg concurrency cap: 1")

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def start(self) -> None:
        """Start E-Pete's background worker."""
        self._running = True
        self._worker_task = asyncio.create_task(self._queue_worker())
        logger.info("[E-Pete] Started")

    async def stop(self) -> None:
        """Stop E-Pete."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[E-Pete] Stopped")

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    def register_engine(self, engine_node: Any) -> None:
        """Register the DistributedEngineNode for system monitoring."""
        self._engine_node = engine_node
        logger.info("[E-Pete] Engine node registered")

    def register_switchblade(self, switchblade: Any) -> None:
        """Register the SwitchbladeGovernor for render state awareness."""
        self._switchblade = switchblade
        logger.info("[E-Pete] Switchblade registered")

    def register_evo(self, evo: Any) -> None:
        """Register the EVOOrchestrator for VDI state awareness."""
        self._evo = evo
        logger.info("[E-Pete] EVO Orchestrator registered")

    def register_alert_handler(
        self,
        handler: Callable[[SystemAlert], None]
    ) -> None:
        """
        Register a handler for system alerts.
        Pete's character layer registers here to receive
        system conditions formatted for user communication.
        """
        self._alert_handlers.append(handler)
        logger.info("[E-Pete] Alert handler registered")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def route(self, task: InferenceTask) -> RoutingDecision:
        """
        Determine routing for a task without executing it.
        Pure routing logic — synchronous, fast.
        """
        # Force model override
        if task.force_model:
            return RoutingDecision(
                task_id        = task.task_id,
                assigned_model = task.force_model,
                reason         = "force_override",
            )

        # Get system status for routing context
        status = self.get_system_status()

        # Base routing from policy table
        model = _DEFAULT_ROUTING.get(task.task_type, InferenceModel.STUDIO)

        # Load-based degradation
        degraded = False
        if status.is_degraded():
            # Under critical/emergency load — push everything to Studio
            # Studio is smaller/faster, protects the user experience
            if model == InferenceModel.ARCHITECT:
                model    = InferenceModel.STUDIO
                degraded = True
                logger.warning(
                    f"[E-Pete] Degraded routing: {task.task_type.value} → Studio "
                    f"(engine state: {status.engine_state})"
                )
            elif model == InferenceModel.CHAIN:
                model    = InferenceModel.STUDIO
                degraded = True

        # Identity moment: defer non-critical tasks
        deferred = False
        if status.identity_moment and task.priority > 3:
            deferred = True
            logger.debug(
                f"[E-Pete] Deferring task {task.task_id} — identity moment active"
            )

        # Estimate latency
        estimated_ms = self._estimate_latency(model, status)

        reason = (
            f"policy:{task.task_type.value}→{model.value}"
            + (" degraded" if degraded else "")
            + (" deferred" if deferred else "")
        )

        return RoutingDecision(
            task_id        = task.task_id,
            assigned_model = model,
            reason         = reason,
            estimated_ms   = estimated_ms,
            deferred       = deferred,
            degraded       = degraded,
        )

    async def execute(self, task: InferenceTask) -> InferenceResult:
        """
        Route and execute an inference task.
        Enforces Zoidberg's 1-concurrent-GGUF constraint.
        """
        decision = self.route(task)

        if decision.deferred:
            async with self._queue_lock:
                self._task_queue.append(task)
                self._task_queue.sort(key=lambda t: t.priority)
            return InferenceResult(
                task_id    = task.task_id,
                model_used = decision.assigned_model,
                output     = "",
                success    = True,
                routing    = decision,
                latency_ms = 0.0,
            )

        return await self._execute_with_semaphore(task, decision)

    async def submit(self, task: InferenceTask) -> None:
        """
        Submit a task to the queue without waiting for result.
        Result will be handled by registered callbacks.
        """
        async with self._queue_lock:
            self._task_queue.append(task)
            self._task_queue.sort(key=lambda t: t.priority)

    def get_system_status(self) -> SystemStatus:
        """
        Read current system status from all registered components.
        This is E-Pete's awareness of what's happening.
        """
        status = SystemStatus(timestamp=time.time())

        # Read from distributed engine
        if self._engine_node:
            try:
                es = self._engine_node.get_system_status()
                status.engine_state  = es.get("state", "normal")
                status.render_load   = self._engine_node.metrics.processing_load
            except Exception:
                pass

        # Read from EVO/Switchblade
        if self._evo:
            try:
                evo_state = self._evo.get_current_state()
                status.vdi_score      = evo_state.get("vdi_score", 0.5)
                status.identity_moment = evo_state.get("identity_moment", False)
            except Exception:
                pass

        # Queue depth
        status.pending_tasks   = len(self._task_queue)
        status.queue_depth_ms  = len(self._task_queue) * 1000.0  # rough estimate

        # Check for alert conditions
        status = self._evaluate_alerts(status)

        return status

    # =========================================================================
    # ALERT SYSTEM
    # =========================================================================

    def _evaluate_alerts(self, status: SystemStatus) -> SystemStatus:
        """
        Evaluate current system state for alert conditions.
        If a condition warrants user notification, package it
        and fire it to Pete's alert handlers.
        """
        alert_level   = "none"
        alert_message = ""
        condition     = ""
        facts         = {}

        if status.engine_state == "emergency":
            alert_level   = "critical"
            condition     = "engine_emergency"
            alert_message = "System under emergency load"
            facts         = {
                "engine_state": status.engine_state,
                "render_load":  round(status.render_load, 1),
                "pending":      status.pending_tasks,
            }
        elif status.engine_state == "critical":
            alert_level   = "warning"
            condition     = "engine_critical"
            alert_message = "System under heavy load"
            facts         = {
                "engine_state": status.engine_state,
                "render_load":  round(status.render_load, 1),
            }
        elif status.queue_depth_ms > 10000:
            alert_level   = "warning"
            condition     = "queue_deep"
            alert_message = "Inference queue backing up"
            facts         = {
                "pending_tasks":  status.pending_tasks,
                "queue_depth_ms": round(status.queue_depth_ms, 0),
            }

        status.has_alert    = alert_level != "none"
        status.alert_level  = alert_level
        status.alert_message = alert_message

        if status.has_alert:
            self._fire_alert(condition, alert_level, facts)

        return status

    def _fire_alert(
        self,
        condition:   str,
        level:       str,
        facts:       Dict[str, Any],
    ) -> None:
        """
        Package a system alert and send it to Pete's character layer.
        E-Pete writes the facts. Pete writes the words.

        Deduplication: same condition will not fire within alert_cooldown_s
        seconds. Prevents alert spam on persistent system issues.
        """
        # Cooldown check — don't spam the same alert
        now = time.time()
        last = self._alert_last_fired.get(condition, 0.0)
        if now - last < self._alert_cooldown_s:
            logger.debug(
                f"[E-Pete] Alert suppressed (cooldown): {condition} "
                f"— {self._alert_cooldown_s - (now - last):.0f}s remaining"
            )
            return
        self._alert_last_fired[condition] = now

        pete_prompt = self._build_pete_alert_prompt(condition, level, facts)

        alert = SystemAlert(
            level       = level,
            condition   = condition,
            facts       = facts,
            pete_prompt = pete_prompt,
        )

        for handler in self._alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"[E-Pete] Alert handler error: {e}")

        logger.warning(f"[E-Pete] Alert fired: {level}/{condition} — {facts}")

    def _build_pete_alert_prompt(
        self,
        condition: str,
        level:     str,
        facts:     Dict[str, Any],
    ) -> str:
        """
        Build a prompt for Pete's character layer to speak a system alert.
        Pete gets the facts and speaks them in her own voice.
        E-Pete does not write Pete's words — just the brief.
        """
        prompts = {
            "engine_emergency": (
                f"[SYSTEM — speak naturally as Pete, do not quote this] "
                f"The system is under emergency load. Render load: {facts.get('render_load')}%. "
                f"There are {facts.get('pending', 0)} tasks waiting. "
                f"Let the user know things may be slow. Be direct. Do not alarm unnecessarily."
            ),
            "engine_critical": (
                f"[SYSTEM — speak naturally as Pete, do not quote this] "
                f"The system is under heavy load ({facts.get('render_load')}%). "
                f"Warn the user that response times may be slower than usual."
            ),
            "queue_deep": (
                f"[SYSTEM — speak naturally as Pete, do not quote this] "
                f"There are {facts.get('pending_tasks')} tasks queued. "
                f"Let the user know there may be a delay before their next response."
            ),
        }
        return prompts.get(
            condition,
            f"[SYSTEM] Alert: {level} — {condition}. Facts: {facts}"
        )

    # =========================================================================
    # EXECUTION ENGINE
    # =========================================================================

    async def _execute_with_semaphore(
        self,
        task:     InferenceTask,
        decision: RoutingDecision,
    ) -> InferenceResult:
        """
        Execute inference with the Zoidberg semaphore.
        Only 1 GGUF call at a time. Period.

        CRITICAL: Chain tasks do NOT hold the semaphore across both calls.
        The semaphore is acquired and released per individual model call
        inside _execute_model_with_semaphore(). This prevents deadlock
        where a chain holds the slot for 4-6 seconds, blocking everything.

        The chain itself coordinates two sequential acquisitions — meaning
        another task CAN slip in between the Architect and Studio steps of
        a chain. This is intentional: it prevents starvation.
        """
        start = time.time()
        self._total_routed += 1

        try:
            if decision.assigned_model == InferenceModel.CHAIN:
                # Chain acquires semaphore per call internally — no outer lock
                output = await self._execute_chain(task)
                self._chain_count += 1
            elif decision.assigned_model == InferenceModel.ARCHITECT:
                async with self._inference_semaphore:
                    output = await self._execute_model(
                        task, self.architect_model_id
                    )
                self._architect_count += 1
            else:
                async with self._inference_semaphore:
                    output = await self._execute_model(
                        task, self.studio_model_id
                    )
                self._studio_count += 1

            latency = (time.time() - start) * 1000
            self._total_latency_ms += latency

            logger.debug(
                f"[E-Pete] Executed {task.task_id} | "
                f"model={decision.assigned_model.value} | "
                f"latency={latency:.0f}ms"
            )

            return InferenceResult(
                task_id    = task.task_id,
                model_used = decision.assigned_model,
                output     = output,
                latency_ms = latency,
                success    = True,
                routing    = decision,
            )

        except Exception as e:
            self._failures += 1
            logger.error(f"[E-Pete] Execution failed: {task.task_id} — {e}")
            return InferenceResult(
                task_id    = task.task_id,
                model_used = decision.assigned_model,
                output     = "",
                latency_ms = (time.time() - start) * 1000,
                success    = False,
                error      = str(e),
                routing    = decision,
            )

    async def _execute_model(
        self,
        task:     InferenceTask,
        model_id: str,
    ) -> str:
        """
        Execute a single model inference call.
        Integrates with LLM framework (Ollama/GGUF/Groq).
        """
        if self._llm is None:
            # Simulation mode — no LLM connected
            logger.debug(f"[E-Pete] Simulation: {model_id} processing {task.task_id}")
            await asyncio.sleep(0.05)
            return f"[{model_id}] Response to: {task.prompt[:50]}..."

        # Real LLM call — integrate with existing llm_framework.py
        try:
            if hasattr(self._llm, 'generate'):
                return await self._llm.generate(
                    model   = model_id,
                    prompt  = task.prompt,
                    context = task.context,
                )
            elif hasattr(self._llm, 'chat'):
                result = await self._llm.chat(
                    model    = model_id,
                    messages = [{"role": "user", "content": task.prompt}],
                )
                return result.get("message", {}).get("content", "")
            else:
                raise ValueError(f"LLM backend has no generate or chat method")
        except Exception as e:
            raise RuntimeError(f"LLM call failed [{model_id}]: {e}")

    async def _execute_chain(self, task: InferenceTask) -> str:
        """
        Architect → Studio chain execution.
        Architect reasons. Studio expresses.

        Each call acquires the semaphore independently.
        This means another queued task CAN execute between the two steps —
        that is intentional. It prevents the chain from locking out
        the entire inference queue for its full duration.

        The intermediate output (Architect result) is held in memory
        between the two semaphore acquisitions.
        """
        # Step 1: Architect reasons — acquires and releases semaphore
        architect_prompt = (
            f"Analyze the following and provide a structured assessment. "
            f"Be precise and factual. Output key points only.\n\n"
            f"{task.prompt}"
        )
        architect_task = InferenceTask(
            task_id   = f"{task.task_id}_arch",
            task_type = TaskType.ANALYSIS,
            prompt    = architect_prompt,
            context   = task.context,
            character = task.character,
        )
        async with self._inference_semaphore:
            architect_output = await self._execute_model(
                architect_task, self.architect_model_id
            )

        # Semaphore released here — other tasks can run between steps

        # Step 2: Studio expresses — acquires and releases semaphore
        studio_prompt = (
            f"You are {task.character}. "
            f"Communicate the following analysis naturally in your voice. "
            f"Do not reference that you received an analysis. Just speak.\n\n"
            f"Analysis: {architect_output}\n\n"
            f"Original context: {task.prompt}"
        )
        studio_task = InferenceTask(
            task_id   = f"{task.task_id}_studio",
            task_type = TaskType.NARRATION,
            prompt    = studio_prompt,
            context   = task.context,
            character = task.character,
        )
        async with self._inference_semaphore:
            return await self._execute_model(studio_task, self.studio_model_id)

    # =========================================================================
    # BACKGROUND WORKER
    # =========================================================================

    async def _queue_worker(self) -> None:
        """
        Process queued tasks in priority order.
        Runs continuously while E-Pete is active.
        """
        while self._running:
            try:
                task = None
                async with self._queue_lock:
                    if self._task_queue:
                        task = self._task_queue.pop(0)

                if task:
                    decision = self.route(task)
                    await self._execute_with_semaphore(task, decision)
                else:
                    await asyncio.sleep(0.05)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[E-Pete] Queue worker error: {e}")
                await asyncio.sleep(0.1)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _estimate_latency(
        self,
        model:  InferenceModel,
        status: SystemStatus,
    ) -> float:
        """Estimate response latency based on model and system load."""
        base = {
            InferenceModel.STUDIO:    800.0,
            InferenceModel.ARCHITECT: 2000.0,
            InferenceModel.CHAIN:     3000.0,
        }[model]

        # Load factor
        load_factor = 1.0 + (status.render_load / 100.0)
        # Queue factor
        queue_factor = 1.0 + (status.pending_tasks * 0.5)

        return base * load_factor * queue_factor

    def get_metrics(self) -> Dict[str, Any]:
        """Return E-Pete's operational metrics."""
        total = max(self._total_routed, 1)
        return {
            "total_routed":     self._total_routed,
            "studio_count":     self._studio_count,
            "architect_count":  self._architect_count,
            "chain_count":      self._chain_count,
            "failures":         self._failures,
            "avg_latency_ms":   round(self._total_latency_ms / total, 1),
            "studio_pct":       round(self._studio_count / total * 100, 1),
            "architect_pct":    round(self._architect_count / total * 100, 1),
            "pending_tasks":    len(self._task_queue),
        }
