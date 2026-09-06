# PubCast AI — orchestrator.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/orchestrator.py
-----------------------
Conversation orchestrator for PubCast AI.
Re-exports ConversationOrchestrator from the implementation file.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from .schemas import ParticipantRole, SayEvent, DoneEvent, ErrorEvent

logger = logging.getLogger("pubcast.orchestrator")


class ConversationOrchestrator:
    """
    Coordinates multi-participant conversations in a room.
    Routes human messages to AI bots and handles turn-taking.
    """

    def __init__(self):
        self._rooms: Dict[str, List[Dict[str, Any]]] = {}
        self._running = False

    async def start_room(self, room_id: str) -> None:
        self._rooms.setdefault(room_id, [])
        logger.info("Orchestrator: room %s started", room_id)

    async def stop_room(self, room_id: str) -> None:
        self._rooms.pop(room_id, None)

    async def handle_message(self, room_id: str, participant_id: str,
                              text: str, role: ParticipantRole = ParticipantRole.HUMAN) -> None:
        messages = self._rooms.setdefault(room_id, [])
        messages.append({
            "participant_id": participant_id,
            "text": text,
            "role": role.value,
            "timestamp": time.time(),
        })
        if len(messages) > 200:
            self._rooms[room_id] = messages[-200:]

    def list_active_rooms(self) -> List[str]:
        return list(self._rooms.keys())

    def get_history(self, room_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        messages = self._rooms.get(room_id, [])
        return messages[-limit:]


__all__ = ["ConversationOrchestrator"]
