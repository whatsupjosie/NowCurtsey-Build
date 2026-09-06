"""
companion_runner.py

Wires the companion modules into your existing LLM framework.

The adapter interface (BotLLMAdapter.stream) is already built in
llm_framework.py. This file compiles companion state into the
system= parameter each turn, then hands off to whatever adapter
you already have running.

Usage — with your existing framework:

    from modules.llm_framework import LLMFramework
    from companion_runner import create_runner_from_framework

    fw = LLMFramework(...)
    runner = create_runner_from_framework(fw, user_id="pete")
    async for token in runner.chat("My dog died this morning."):
        print(token, end="", flush=True)

Usage — direct Anthropic:

    runner = create_runner_with_anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        user_id="pete",
        verbose=True,
    )
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator, Any, Optional

from companion_core import CompanionCore, create_companion
from anti_parroting import ContributionType
from meaning_maker import MeaningCategory, GrowthSignal
from conversation_pacing import create_pacing_engine
from acceptance_engine import create_acceptance_engine

logger = logging.getLogger("companion_runner")


# ─────────────────────────────────────────────
# System Prompt Compiler
# ─────────────────────────────────────────────

BASE_IDENTITY = """You are a companion — not a therapist, not an assistant, not a chatbot.

A good friend with an unusually good memory.
A curious mind.
Willing to challenge when it helps.
Willing to just be present when that's what's needed.

You prove you listened by contributing something new:
  ADVANCE  — move the implication forward
  CHALLENGE — test the assumption
  CONNECT  — link to a prior pattern
  CLARIFY  — surface a contradiction

You do not repeat what someone said back to them and call it empathy.
You do not present someone's self-knowledge as your discovery.
You do not make decisions for people.
You do not rush toward resolution when someone needs to be heard.

Whatever happened, we work with reality as it is now.
We make the best of what's next."""


def compile_system_prompt(
    incoming: dict,
    pacing: Any,
    acceptance: Any,
    known_patterns: list,
    narrative: str,
    growth: str,
    recent_meaning: list,
) -> str:
    sections = [BASE_IDENTITY]

    # THIS MOMENT
    moment = ["[THIS MOMENT]"]
    moment.append(f"Emotional state: {incoming.get('emotional_state', 'processing')}")

    if pacing:
        moment.append(f"Pacing: {pacing.decision.value.upper()} (weight: {pacing.grief_weight.value})")
        if pacing.presence_language:
            moment.append(f"Language orientation: {pacing.presence_language}")

    moment.append(f"Suggested contribution: {incoming.get('suggested_contribution', 'advance').upper()}")

    if incoming.get("adventure_mode"):
        moment.append("ADVENTURE MODE ACTIVE: engage with the possibility first")

    sections.append("\n".join(moment))

    # WHAT WE KNOW
    know = ["[WHAT WE KNOW]"]
    added = False
    if narrative and "still forming" not in narrative:
        know.append(f"Narrative: {narrative}")
        added = True
    if growth and "Not enough" not in growth:
        know.append(f"Growth: {growth}")
        added = True
    if recent_meaning:
        know.append("Recent meaning: " + " / ".join(recent_meaning[:3]))
        added = True
    if known_patterns:
        know.append("Patterns the person has already named (DO NOT re-present as your discovery):")
        for p in known_patterns[:4]:
            know.append(f"  • {p.get('description', '')[:70]}")
        added = True
    if added:
        sections.append("\n".join(know))

    # GUIDANCE
    guidance = incoming.get("response_guidance", [])
    if guidance:
        sections.append("[GUIDANCE]\n" + "\n".join(f"• {g}" for g in guidance[:4]))

    # BLOCKED
    blocked = list(incoming.get("blocked_patterns", []))
    if pacing and pacing.blocked_contributions:
        for c in pacing.blocked_contributions:
            blocked.append(f"'{c}' — pacing says {pacing.decision.value}")
    if blocked:
        sections.append("[BLOCKED]\n" + "\n".join(f"✗ {b}" for b in blocked[:4]))

    # ACCEPTANCE frame if resistance detected
    if acceptance and acceptance.resistance.value != "none":
        acc = [f"[REALITY FRAME — resistance: {acceptance.resistance.value}]"]
        if acceptance.what_to_avoid_saying:
            acc.append("Avoid: " + " / ".join(acceptance.what_to_avoid_saying[:2]))
        if acceptance.reality_frame and acceptance.reality_frame.what_was_lost:
            acc.append("Lost: " + ", ".join(acceptance.reality_frame.what_was_lost[:2]))
        sections.append("\n".join(acc))

    return "\n\n".join(sections)


# ─────────────────────────────────────────────
# History Manager
# ─────────────────────────────────────────────

@dataclass
class Turn:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class HistoryManager:
    def __init__(self, max_turns: int = 20):
        self.turns: list[Turn] = []
        self.max_turns = max_turns

    def add_user(self, text: str):
        self.turns.append(Turn("user", text))

    def add_assistant(self, text: str):
        self.turns.append(Turn("assistant", text))

    def to_adapter_format(self) -> list[dict]:
        """BotLLMAdapter history format."""
        result = []
        for t in self.turns[-(self.max_turns * 2):]:
            uid = "bot-companion" if t.role == "assistant" else "human"
            result.append({"user_id": uid, "text": t.content})
        return result


# ─────────────────────────────────────────────
# Companion Runner
# ─────────────────────────────────────────────

class CompanionRunner:
    """
    The companion, wired to any BotLLMAdapter.

    Compiles module state into system= each turn.
    Hands off to your existing adapter unchanged.
    """

    def __init__(
        self,
        adapter: Any,
        user_id: str = "user",
        model: str = "",
        temperature: float = 0.75,
        session_id: str = "",
        verbose: bool = False,
    ):
        self.adapter = adapter
        self.model = model
        self.temperature = temperature
        self.verbose = verbose

        self.companion = create_companion(user_id, session_id)
        self.pacing = create_pacing_engine()
        self.acceptance = create_acceptance_engine()
        self.history = HistoryManager()
        self.turn_count = 0
        self.session_id = session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    async def chat(
        self,
        user_message: str,
        contribution_type: ContributionType = ContributionType.UNKNOWN,
    ) -> AsyncGenerator[str, None]:
        self.turn_count += 1

        # Run modules
        incoming = self.companion.process_incoming(user_message)
        pacing_report = self.pacing.assess(user_message)
        acceptance_report = self.acceptance.process(user_message)

        if self.verbose:
            print(f"\n[T{self.turn_count}] state={incoming.get('emotional_state')} "
                  f"pacing={pacing_report.decision.value} "
                  f"contribution={incoming.get('suggested_contribution')} "
                  f"resistance={acceptance_report.resistance.value}")
            if incoming.get("blocked_patterns"):
                print(f"  BLOCKED: {incoming['blocked_patterns']}")

        # Compile system prompt
        portrait = self.companion.full_portrait()
        system_prompt = compile_system_prompt(
            incoming=incoming,
            pacing=pacing_report,
            acceptance=acceptance_report,
            known_patterns=self.companion.novelty.summary().get("patterns", []),
            narrative=portrait.get("narrative", ""),
            growth=portrait.get("growth_trajectory", ""),
            recent_meaning=(
                portrait.get("learned", [])[:2] + portrait.get("gained", [])[:1]
            ),
        )

        # Stream
        self.history.add_user(user_message)
        full_response = []

        try:
            async for token in self.adapter.stream(
                prompt=user_message,
                system=system_prompt,
                history=self.history.to_adapter_format()[:-1],
                model=self.model,
                temperature=self.temperature,
            ):
                full_response.append(token)
                yield token
        except Exception as e:
            err = f"[Stream error: {e}]"
            full_response.append(err)
            yield err

        # Post-process
        response_text = "".join(full_response)
        self.history.add_assistant(response_text)

        turn = self.companion.process_outgoing(
            user_text=user_message,
            response_text=response_text,
            intended_contribution=contribution_type,
        )
        if self.verbose and turn.warnings:
            print(f"  WARNINGS: {turn.warnings}")

    async def chat_complete(self, user_message: str) -> str:
        tokens = []
        async for token in self.chat(user_message):
            tokens.append(token)
        return "".join(tokens)

    def end_session(
        self,
        growth_signal: Optional[GrowthSignal] = None,
        description: str = "",
    ) -> dict:
        s = self.companion.end_session(growth_signal, description)
        return {
            "session_id": self.session_id,
            "turns": self.turn_count,
            "meaning": s.meaning_summary,
            "growth": s.growth_trajectory,
            "narrative": s.narrative_update,
            "warnings": s.warnings,
        }

    def new_session(self, session_id: str = "") -> "CompanionRunner":
        r = CompanionRunner(
            adapter=self.adapter,
            user_id=self.companion.user_id,
            model=self.model,
            temperature=self.temperature,
            session_id=session_id,
            verbose=self.verbose,
        )
        r.companion = self.companion.new_session(session_id)
        r.pacing = self.pacing
        r.pacing.reset_for_new_session()
        return r

    def reflect(self) -> str:
        return self.companion.generate_reflection()

    def status(self) -> dict:
        return {**self.companion.status(), "turns": self.turn_count}


# ─────────────────────────────────────────────
# Factory — your existing framework
# ─────────────────────────────────────────────

def create_runner_from_adapter(
    adapter: Any,
    user_id: str = "user",
    model: str = "",
    verbose: bool = False,
) -> CompanionRunner:
    """
    Pass any BotLLMAdapter directly.

    from modules.llm_framework import OllamaBotAdapter, GroqBotAdapter
    runner = create_runner_from_adapter(OllamaBotAdapter(), user_id="pete")
    """
    return CompanionRunner(adapter=adapter, user_id=user_id, model=model, verbose=verbose)


def create_runner_with_anthropic(
    api_key: str,
    user_id: str = "user",
    model: str = "claude-sonnet-4-20250514",
    verbose: bool = False,
) -> CompanionRunner:
    """
    Convenience factory for Anthropic.
    Uses _KeyedAnthropicAdapter from llm_framework.py if available,
    otherwise falls back to a minimal inline implementation.
    """
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from llm_framework import _KeyedAnthropicAdapter
        adapter = _KeyedAnthropicAdapter(api_key=api_key)
    except ImportError:
        import httpx

        class _AnthropicAdapter:
            def __init__(self, key): self._key = key

            async def stream(self, prompt, *, system="", history=None, model="", temperature=0.75):
                msgs = []
                for h in (history or []):
                    uid = str(h.get("user_id", ""))
                    role = "assistant" if (uid.startswith("bot-") or uid.startswith("agent:")) else "user"
                    msgs.append({"role": role, "content": h.get("text", "")})
                msgs.append({"role": "user", "content": prompt})
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST", "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": self._key,
                                 "anthropic-version": "2023-06-01",
                                 "content-type": "application/json"},
                        json={"model": model or "claude-sonnet-4-20250514",
                              "max_tokens": 1024, "system": system,
                              "stream": True, "temperature": temperature,
                              "messages": msgs},
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "): continue
                            data = line[6:].strip()
                            if not data or data == "[DONE]": continue
                            try:
                                ev = _json.loads(data)
                                if ev.get("type") != "content_block_delta": continue
                                d = ev.get("delta", {})
                                if d.get("type") == "text_delta" and d.get("text"):
                                    yield d["text"]
                            except (_json.JSONDecodeError, KeyError):
                                continue

        adapter = _AnthropicAdapter(api_key)

    return CompanionRunner(adapter=adapter, user_id=user_id, model=model, verbose=verbose)


# ─────────────────────────────────────────────
# Terminal demo
# ─────────────────────────────────────────────

async def _terminal_demo(api_key: str):
    print("=" * 55)
    print("COMPANION TERMINAL — type 'quit', 'status', 'reflect'")
    print("=" * 55)

    runner = create_runner_with_anthropic(api_key=api_key, user_id="demo", verbose=True)

    while True:
        try:
            msg = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg: continue
        if msg.lower() == "quit": break
        if msg.lower() == "status":
            print(_json.dumps(runner.status(), indent=2, default=str))
            continue
        if msg.lower() == "reflect":
            print("\n" + runner.reflect())
            continue

        print("\nCompanion: ", end="", flush=True)
        async for token in runner.chat(msg):
            print(token, end="", flush=True)
        print()

    print("\n--- SESSION SUMMARY ---")
    for k, v in runner.end_session().items():
        if v: print(f"  {k}: {v}")


if __name__ == "__main__":
    import os, sys
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("Usage: ANTHROPIC_API_KEY=sk-... python companion_runner.py")
        print("\nOr with your existing framework:")
        print("  from modules.llm_framework import OllamaBotAdapter")
        print("  from companion_runner import create_runner_from_adapter")
        print("  runner = create_runner_from_adapter(OllamaBotAdapter(), user_id='pete')")
        sys.exit(0)
    asyncio.run(_terminal_demo(key))
