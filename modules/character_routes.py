# PubCast AI — character_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Character Engine API Routes
Manage character profiles and interactions
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from .route_security import current_identity

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CharacterSpeakRequest(BaseModel):
    """Request for character to speak."""
    character_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=10000)
    context: Optional[Dict[str, Any]] = None


# Global instances
_character_engine = None
_character_profiles = None


def set_character_instances(engine, profiles):
    """Set global character instances (called from main.py)."""
    global _character_engine, _character_profiles
    _character_engine = engine
    _character_profiles = profiles


@router.get("/list")
async def list_characters():
    """List all available characters."""
    if not _character_profiles:
        raise HTTPException(503, "Character system not initialized")
    
    try:
        characters = _character_profiles.list_characters()
        return {"characters": characters, "count": len(characters)}
    except Exception as e:
        raise HTTPException(500, f"Error listing characters: {e}")


@router.get("/{character_id}")
async def get_character(character_id: str = Path(..., min_length=1, max_length=128)):
    """Get character profile details."""
    if not _character_profiles:
        raise HTTPException(503, "Character system not initialized")
    
    try:
        profile = _character_profiles.get_character(character_id)
        if not profile:
            raise HTTPException(404, f"Character '{character_id}' not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error retrieving character: {e}")


@router.post("/speak")
async def character_speak(
    request: CharacterSpeakRequest,
    identity: Dict[str, Any] = Depends(current_identity),
):
    """Have a character generate a response."""
    if not _character_engine:
        raise HTTPException(503, "Character engine not initialized")
    
    try:
        response = await _character_engine.speak(
            request.character_id,
            request.message,
            context=request.context or {}
        )
        return {"character": request.character_id, "response": response}
    except Exception as e:
        raise HTTPException(500, f"Character speak error: {e}")


@router.get("/{character_id}/context")
async def get_character_context(character_id: str = Path(..., min_length=1, max_length=128)):
    """Get character's current context and state."""
    if not _character_engine:
        raise HTTPException(503, "Character engine not initialized")
    
    try:
        context = _character_engine.get_character_context(character_id)
        return {"character": character_id, "context": context}
    except Exception as e:
        raise HTTPException(500, f"Error getting context: {e}")
