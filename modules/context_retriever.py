# PubCast AI - context_retriever.py
# Copyright 2024-2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC - All Rights Reserved
# Feic Mo Chroi - See My Heart
"""Keyword, importance, and recency retrieval for PubCast memory context."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import memory_engine


@dataclass
class RetrievedMemory:
    content: str
    source: str
    memory_type: str
    importance: float
    recency_score: float
    relevance_score: float
    final_score: float
    age_description: str


def _tokens(text: str) -> set[str]:
    return {part.strip(".,!?;:()[]{}\"'").lower() for part in text.split() if part.strip()}


def _age_description(ts: float) -> str:
    seconds = max(0.0, time.time() - float(ts or time.time()))
    if seconds < 3600:
        return "just now"
    if seconds < 86400:
        hours = max(1, int(seconds // 3600))
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if seconds < 604800:
        days = max(1, int(seconds // 86400))
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = max(1, int(seconds // 604800))
    return f"{weeks} week{'s' if weeks != 1 else ''} ago"


def _recency_score(ts: float) -> float:
    age_days = max(0.0, (time.time() - float(ts or time.time())) / 86400)
    return max(0.05, 1.0 - min(age_days / 30.0, 0.95))


class ContextRetriever:
    """Retrieve ranked memories without requiring external vector services."""

    def __init__(self, data_dir: Path, memory_system: Any = None) -> None:
        self.data_dir = Path(data_dir)
        self.memory_system = memory_system

    def retrieve(
        self,
        query: str,
        user_id: str,
        project_id: str,
        character_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[RetrievedMemory]:
        query_tokens = _tokens(query)
        candidates: List[Dict[str, Any]] = []

        if user_id:
            candidates.extend(memory_engine.recent_for_user(self.data_dir, user_id=user_id, limit=max(50, limit * 5)))
        if project_id:
            candidates.extend(
                memory_engine.recent_for_room(
                    self.data_dir,
                    project_id=project_id,
                    room_id=f"character_{character_id or user_id}",
                    limit=max(25, limit * 3),
                )
            )

        if self.memory_system is not None and character_id:
            for item in self.memory_system.search(character_id, query, max(25, limit * 3)):
                candidates.append(
                    {
                        "summary": item.get("content", ""),
                        "event_type": item.get("memory_type", "fact"),
                        "feature_id": item.get("source", "universal_memory"),
                        "ts": item.get("created_at", time.time()),
                        "payload": {"importance": item.get("importance", 0.5)},
                    }
                )

        seen: set[str] = set()
        ranked: List[RetrievedMemory] = []
        for candidate in candidates:
            content = str(candidate.get("summary") or "").strip()
            if not content:
                continue
            fingerprint = hashlib.sha1(content[:80].lower().encode("utf-8")).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            content_tokens = _tokens(content)
            overlap = len(query_tokens & content_tokens) if query_tokens else 1
            if query_tokens and overlap == 0:
                continue

            payload = candidate.get("payload") or {}
            importance = max(0.0, min(1.0, float(payload.get("importance", 0.5))))
            recency = _recency_score(float(candidate.get("ts") or time.time()))
            relevance = float(overlap)
            final = (relevance * 2.0) + (importance * 3.0) + recency
            ranked.append(
                RetrievedMemory(
                    content=content,
                    source=str(candidate.get("feature_id") or "memory_engine"),
                    memory_type=str(candidate.get("event_type") or "fact"),
                    importance=importance,
                    recency_score=round(recency, 3),
                    relevance_score=round(relevance, 3),
                    final_score=round(final, 3),
                    age_description=_age_description(float(candidate.get("ts") or time.time())),
                )
            )

        ranked.sort(key=lambda memory: memory.final_score, reverse=True)
        return ranked[: max(1, limit)]


__all__ = ["ContextRetriever", "RetrievedMemory"]
