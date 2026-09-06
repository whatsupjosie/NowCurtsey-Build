"""
modules/governance_waiting_room.py — Waiting Room / Airlock System
Rear View Foresight LLC — Feic Mo Chroí — 2026-04-18

Handles entry requests, approval flow, and real-time status polling.
"""
from __future__ import annotations
import time, uuid, logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .sir_purfluous_waiting_room import public_context as purfluous_public_context
from .route_security import current_identity, require_role

logger = logging.getLogger("pubcast.governance.waiting_room")

# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class EntryStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"

@dataclass
class WaitingRoomEntry:
    entry_id: str
    user_id: str
    display_name: str
    target_room: str
    consents: Dict[str, bool]
    status: EntryStatus = EntryStatus.PENDING
    requested_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    approved_by: Optional[str] = None
    deny_reason: Optional[str] = None

class EntryRequest(BaseModel):
    user_id: str
    display_name: str
    target_room: str
    consents: Dict[str, bool]

# ═══════════════════════════════════════════════════════════════════════════
# WAITING ROOM MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class WaitingRoomManager:
    def __init__(self, auto_approve: bool = False, auto_approve_delay: float = 2.0):
        self._entries: Dict[str, WaitingRoomEntry] = {}
        self._auto_approve = auto_approve
        self._auto_approve_delay = auto_approve_delay
        logger.info(f"Waiting room initialized (auto_approve={auto_approve})")
    
    def request_entry(self, user_id: str, display_name: str, target_room: str, consents: Dict[str, bool]) -> str:
        """Submit entry request, returns entry_id for polling."""
        entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        
        entry = WaitingRoomEntry(
            entry_id=entry_id,
            user_id=user_id,
            display_name=display_name,
            target_room=target_room,
            consents=consents,
        )
        
        self._entries[entry_id] = entry
        logger.info(f"Entry request: {display_name} → {target_room} [{entry_id}]")
        
        # Auto-approve if enabled
        if self._auto_approve:
            import asyncio
            asyncio.create_task(self._auto_approve_entry(entry_id))
        
        return entry_id
    
    async def _auto_approve_entry(self, entry_id: str):
        """Auto-approve after delay (for testing)."""
        import asyncio
        await asyncio.sleep(self._auto_approve_delay)
        
        if entry_id in self._entries and self._entries[entry_id].status == EntryStatus.PENDING:
            self.approve_entry(entry_id, "system_auto")
            logger.info(f"Auto-approved entry {entry_id}")
    
    def approve_entry(self, entry_id: str, approved_by: str = "host"):
        """Approve an entry request."""
        if entry_id not in self._entries:
            raise ValueError(f"Entry {entry_id} not found")
        
        entry = self._entries[entry_id]
        if entry.status != EntryStatus.PENDING:
            raise ValueError(f"Entry {entry_id} already processed")
        
        entry.status = EntryStatus.APPROVED
        entry.approved_at = time.time()
        entry.approved_by = approved_by
        logger.info(f"Approved: {entry.display_name} → {entry.target_room}")
    
    def deny_entry(self, entry_id: str, reason: str = ""):
        """Deny an entry request."""
        if entry_id not in self._entries:
            raise ValueError(f"Entry {entry_id} not found")
        
        entry = self._entries[entry_id]
        if entry.status != EntryStatus.PENDING:
            raise ValueError(f"Entry {entry_id} already processed")
        
        entry.status = EntryStatus.DENIED
        entry.deny_reason = reason
        logger.info(f"Denied: {entry.display_name} - {reason}")
    
    def get_entry(self, entry_id: str) -> Optional[WaitingRoomEntry]:
        """Get entry by ID."""
        return self._entries.get(entry_id)
    
    def get_pending_entries(self):
        """Get all pending entries (for host UI)."""
        return [e for e in self._entries.values() if e.status == EntryStatus.PENDING]

# Global manager (initialized in main.py)
_waiting_room: Optional[WaitingRoomManager] = None

def init_waiting_room(auto_approve: bool = False):
    """Initialize waiting room system."""
    global _waiting_room
    _waiting_room = WaitingRoomManager(auto_approve=auto_approve)
    return _waiting_room

def get_waiting_room() -> WaitingRoomManager:
    """Get waiting room manager instance."""
    if not _waiting_room:
        raise RuntimeError("Waiting room not initialized")
    return _waiting_room

# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/governance/waiting-room", tags=["Waiting Room"])

@router.post("/request")
async def request_entry(req: EntryRequest, identity: Dict[str, Any] = Depends(current_identity)):
    """Submit entry request to waiting room."""
    wm = get_waiting_room()
    
    entry_id = wm.request_entry(
        user_id=req.user_id,
        display_name=req.display_name,
        target_room=req.target_room,
        consents=req.consents,
    )
    
    return {
        "entry_id": entry_id,
        "status": "pending",
        "message": "Waiting for host approval",
    }

@router.get("/status/{entry_id}")
async def check_entry_status(entry_id: str):
    """Poll entry status (used by waiting_room.html)."""
    wm = get_waiting_room()
    
    entry = wm.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, f"Entry {entry_id} not found")
    
    response = {
        "entry_id": entry_id,
        "status": entry.status.value,
        "target_room": entry.target_room,
    }
    
    if entry.status == EntryStatus.APPROVED:
        response["approved_at"] = entry.approved_at
        response["approved_by"] = entry.approved_by
    
    elif entry.status == EntryStatus.DENIED:
        response["deny_reason"] = entry.deny_reason
    
    return response

@router.post("/{entry_id}/approve")
async def approve_entry(
    entry_id: str,
    approved_by: str = "host",
    identity: Dict[str, Any] = Depends(require_role("mod")),
):
    """Approve an entry (host only)."""
    wm = get_waiting_room()
    
    try:
        wm.approve_entry(entry_id, approved_by)
        return {"entry_id": entry_id, "status": "approved"}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.post("/{entry_id}/deny")
async def deny_entry(
    entry_id: str,
    reason: str = "",
    identity: Dict[str, Any] = Depends(require_role("mod")),
):
    """Deny an entry (host only)."""
    wm = get_waiting_room()
    
    try:
        wm.deny_entry(entry_id, reason)
        return {"entry_id": entry_id, "status": "denied", "reason": reason}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.get("/pending")
async def get_pending():
    """Get all pending entries (for host dashboard)."""
    wm = get_waiting_room()
    
    entries = wm.get_pending_entries()
    
    return {
        "pending": [
            {
                "entry_id": e.entry_id,
                "user_id": e.user_id,
                "display_name": e.display_name,
                "target_room": e.target_room,
                "requested_at": e.requested_at,
                "consents": e.consents,
            }
            for e in entries
        ],
        "count": len(entries),
    }

@router.get("/host")
async def get_waiting_room_host(state: str = "pending"):
    """Return UI-safe Sir Purfluous host context for the waiting room."""
    return purfluous_public_context(state)
