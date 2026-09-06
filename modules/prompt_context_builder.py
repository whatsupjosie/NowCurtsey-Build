# PubCast AI - prompt_context_builder.py
# Copyright 2024-2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC - All Rights Reserved
# Feic Mo Chroi - See My Heart
"""Build compact natural-language memory context for model prompts."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .context_retriever import RetrievedMemory


class PromptContextBuilder:
    """Convert ranked memories into a bounded, human-readable prompt block."""

    def build(
        self,
        character_profile: Dict[str, Any],
        retrieved_memories: List[RetrievedMemory],
        max_tokens: int = 800,
    ) -> str:
        name = str(
            character_profile.get("display_name")
            or character_profile.get("name")
            or character_profile.get("character_id")
            or "this character"
        )
        role = str(character_profile.get("role") or "").strip()
        voice = str(character_profile.get("voice_notes") or character_profile.get("public_blurb") or "").strip()

        memories = sorted(retrieved_memories, key=lambda item: item.final_score, reverse=True)
        lines = self._render(name, role, voice, memories)
        while self._estimate_tokens("\n".join(lines)) > max_tokens and memories:
            memories = memories[:-1]
            lines = self._render(name, role, voice, memories)
        return "\n".join(lines).strip()

    def _render(
        self,
        name: str,
        role: str,
        voice: str,
        memories: Iterable[RetrievedMemory],
    ) -> List[str]:
        lines = [f"You are {name}."]
        if role:
            lines.append(f"Your role here: {role}.")
        if voice:
            lines.append("")
            lines.append(voice)
        if memories:
            lines.append("")
            lines.append("What you carry into this conversation:")
            for memory in memories:
                lines.append(f"- [{memory.age_description}] {memory.content}")
        lines.append("")
        lines.append("Respond as yourself. Let this inform you, but do not narrate the memory system.")
        return lines

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)


__all__ = ["PromptContextBuilder"]
