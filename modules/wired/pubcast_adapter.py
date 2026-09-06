"""
pubcast_adapter.py
==================
Bridges the existing PubCast Hub + BotManager into thinking_context's
ContextHost protocol so the two systems can coexist.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast_adapter")


class PubCastAdapter:
    """
    Wraps Hub (get_recent_history) and BotManager (nudge) into
    the ContextHost protocol that thinking_context expects.

    Pass this single object to thinking_context.mount() instead of
    passing hub and bot_manager separately.

    Usage in main.py:

        from modules.wired.pubcast_adapter import PubCastAdapter

        adapter = PubCastAdapter(hub, bot_manager)
        # Pass to thinking_context:
        # from thinking_context import mount as tc_mount
        # tc_mount(app, adapter, ...)

    Both Hub and BotManager already satisfy their respective protocols
    (HistoryProvider and NudgeTarget), so this is purely an adapter
    that composes them into one object.
    """

    def __init__(
        self,
        hub: Any,
        bot_manager: Any,
    ) -> None:
        self._hub = hub
        self._bm  = bot_manager
        logger.info("PubCastAdapter: wrapping hub=%s bot_manager=%s",
                     type(hub).__name__, type(bot_manager).__name__)

    async def get_recent_history(self, room: str, limit: int = 12) -> List[Dict[str, Any]]:
        """Delegates to Hub.get_recent_history (satisfies HistoryProvider)."""
        return await self._hub.get_recent_history(room, limit)

    async def nudge(self, room_id: str, hint: str) -> bool:
        """Delegates to BotManager.nudge (satisfies NudgeTarget)."""
        return await self._bm.nudge(room_id, hint)
