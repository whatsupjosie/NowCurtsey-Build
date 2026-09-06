# PubCast AI — story_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Story Bible API Routes
Narrative system for Belle Époque Studios
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/story", tags=["story"])

_story_bible = None

def set_story_instance(story_instance):
    """Set global story bible instance (called from main.py)."""
    global _story_bible
    _story_bible = story_instance

@router.get("/")
async def get_story_overview():
    """Get story bible overview."""
    if not _story_bible:
        raise HTTPException(503, "Story bible not initialized")
    try:
        overview = _story_bible.get_overview()
        return overview
    except Exception as e:
        raise HTTPException(500, f"Error getting overview: {e}")

@router.get("/characters")
async def get_story_characters():
    """Get all story characters."""
    if not _story_bible:
        raise HTTPException(503, "Story bible not initialized")
    try:
        characters = _story_bible.get_characters()
        return {"characters": characters}
    except Exception as e:
        raise HTTPException(500, f"Error getting characters: {e}")

@router.get("/beats")
async def get_story_beats():
    """Get narrative story beats."""
    if not _story_bible:
        raise HTTPException(503, "Story bible not initialized")
    try:
        beats = _story_bible.get_beats()
        return {"beats": beats}
    except Exception as e:
        raise HTTPException(500, f"Error getting story beats: {e}")
