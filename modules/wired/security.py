#!/usr/bin/env python3
"""
PUBCAST AI SECURITY LAYER
© 2024-2025 Rear View Foresight LLC

Input validation, sanitization, and basic auth for production.
Drop this into main.py and integrate the validators.

Usage:
    from security import validate_message, RateLimiter, TokenAuth
    
    limiter = RateLimiter(max_messages=30, window_seconds=60)
    if not limiter.is_allowed(user_id):
        return error_response("Rate limited")
"""

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from html import escape
from typing import Dict, Optional, Tuple

from pydantic import BaseModel, Field, validator, ValidationError

logger = logging.getLogger("pubcast.security")


# ============================================================================
# MESSAGE SCHEMAS (Pydantic Models)
# ============================================================================

class MessageType(str, Enum):
    """Valid WebSocket message types"""
    CHAT = "chat"
    FEEDBACK = "feedback"
    CORRECTION = "correction"
    PING = "ping"
    SET_PERSONA = "set_persona"


class ChatMessage(BaseModel):
    """User chat message"""
    type: MessageType = MessageType.CHAT
    text: str = Field(..., min_length=1, max_length=10000)

    @validator("text")
    def sanitize_and_check(cls, v: str) -> str:
        """Sanitize and validate message text"""
        v = escape(v.strip())
        if len(v) > 20:
            for char in set(v):
                if v.count(char) > len(v) * 0.5:
                    raise ValueError("Message appears to be spam")
        return v


class FeedbackMessage(BaseModel):
    """User feedback on a response"""
    type: MessageType = MessageType.FEEDBACK
    response: str = Field(..., min_length=1, max_length=10000)
    positive: bool


class CorrectionMessage(BaseModel):
    """User correction for intent matching"""
    type: MessageType = MessageType.CORRECTION
    message: str = Field(..., min_length=1, max_length=10000)
    correct_intent: str = Field(..., min_length=1, max_length=100)
    original_intent: Optional[str] = None

    @validator("correct_intent")
    def validate_intent_name(cls, v: str) -> str:
        """Intent names should be simple identifiers"""
        if not re.match(r"^[a-z_][a-z0-9_]{0,49}$", v, re.IGNORECASE):
            raise ValueError("Invalid intent name format")
        return v.lower()


class PingMessage(BaseModel):
    """Keep-alive ping"""
    type: MessageType = MessageType.PING


class SetPersonaMessage(BaseModel):
    """Request persona change"""
    type: MessageType = MessageType.SET_PERSONA
    persona_name: str = Field(..., min_length=1, max_length=100)

    @validator("persona_name")
    def validate_persona_name(cls, v: str) -> str:
        """Persona names must be safe identifiers"""
        if not re.match(r"^[a-z_][a-z0-9_\-]{0,49}$", v, re.IGNORECASE):
            raise ValueError("Invalid persona name format")
        return v.lower()


# Discriminated union of all message types
WebSocketMessage = ChatMessage | FeedbackMessage | CorrectionMessage | PingMessage | SetPersonaMessage


def parse_websocket_message(raw_data: str) -> Tuple[Optional[WebSocketMessage], Optional[str]]:
    """
    Parse and validate a WebSocket message.

    Returns:
        (message_object, error_string) — one will be None
    """
    try:
        raw = json.loads(raw_data)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {str(e)}"

    msg_type = raw.get("type")

    try:
        if msg_type == MessageType.CHAT:
            return ChatMessage(**raw), None
        elif msg_type == MessageType.FEEDBACK:
            return FeedbackMessage(**raw), None
        elif msg_type == MessageType.CORRECTION:
            return CorrectionMessage(**raw), None
        elif msg_type == MessageType.PING:
            return PingMessage(**raw), None
        elif msg_type == MessageType.SET_PERSONA:
            return SetPersonaMessage(**raw), None
        else:
            return None, f"Unknown message type: {msg_type}"
    except ValidationError as e:
        # Return first validation error in readable form
        first_error = e.errors()[0]
        field = first_error.get("loc", ["unknown"])[0]
        msg = first_error.get("msg", "Validation failed")
        return None, f"Invalid {field}: {msg}"


# ============================================================================
# RATE LIMITING
# ============================================================================

@dataclass
class RateLimit:
    """Individual user rate limit state"""
    user_id: str
    messages: list = field(default_factory=list)  # timestamps
    last_cleaned: float = field(default_factory=time.time)


class RateLimiter:
    """Token bucket rate limiter per user."""

    def __init__(
        self,
        max_messages_per_minute: int = 30,
        max_messages_per_day: int = 1000,
    ):
        self.max_per_minute = max_messages_per_minute
        self.max_per_day = max_messages_per_day
        self.buckets: Dict[str, RateLimit] = {}

    def is_allowed(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if user can send a message.

        Returns:
            (allowed: bool, reason: str or None)
        """
        if user_id not in self.buckets:
            self.buckets[user_id] = RateLimit(user_id=user_id)

        bucket = self.buckets[user_id]
        now = time.time()

        # Clean up old entries periodically
        if now - bucket.last_cleaned > 60:
            bucket.messages = [
                t for t in bucket.messages
                if now - t < 86400  # Keep last 24 hours
            ]
            bucket.last_cleaned = now

        # Check per-minute limit
        recent_minute = [t for t in bucket.messages if now - t < 60]
        if len(recent_minute) >= self.max_per_minute:
            reset_time = int(recent_minute[0] + 60)
            return False, f"Rate limited. Try again after {datetime.fromtimestamp(reset_time)}"

        # Check per-day limit
        if len(bucket.messages) >= self.max_per_day:
            return False, "Daily limit exceeded. Try again tomorrow."

        # Record this message
        bucket.messages.append(now)
        return True, None


# ============================================================================
# TOKEN AUTHENTICATION
# ============================================================================

class TokenAuth:
    """Simple JWT-like token auth (can swap for proper JWT later)."""

    def __init__(self, secret: str, token_lifetime_hours: int = 24):
        self.secret = secret
        self.lifetime = timedelta(hours=token_lifetime_hours)
        self.tokens: Dict[str, dict] = {}  # token -> {user_id, expires_at}

    def generate_token(self, user_id: str) -> str:
        """Generate a session token for a user."""
        token = str(uuid.uuid4())
        self.tokens[token] = {
            "user_id": user_id,
            "expires_at": datetime.now() + self.lifetime,
        }
        logger.debug("Generated token for user %s", user_id)
        return token

    def validate_token(self, token: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a token.

        Returns:
            (valid: bool, user_id: str or None)
        """
        if token not in self.tokens:
            return False, None

        data = self.tokens[token]
        if datetime.now() > data["expires_at"]:
            del self.tokens[token]
            return False, None

        return True, data["user_id"]

    def revoke_token(self, token: str) -> bool:
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]
            return True
        return False


# ============================================================================
# REQUEST SIZE LIMITS
# ============================================================================

class SizeValidator:
    """Validate payload sizes to prevent DoS."""

    MAX_MESSAGE_SIZE = 10 * 1024  # 10 KB
    MAX_ROOM_ID = 256
    MAX_USER_ID = 256

    @staticmethod
    def validate_message_size(text: str) -> Tuple[bool, Optional[str]]:
        """Check if message is within size limits."""
        size = len(text.encode("utf-8"))
        if size > SizeValidator.MAX_MESSAGE_SIZE:
            return False, f"Message too large ({size} bytes, max {SizeValidator.MAX_MESSAGE_SIZE})"
        return True, None

    @staticmethod
    def validate_room_id(room_id: str) -> Tuple[bool, Optional[str]]:
        """Validate room ID format and size."""
        if len(room_id) > SizeValidator.MAX_ROOM_ID:
            return False, f"Room ID too long (max {SizeValidator.MAX_ROOM_ID} chars)"
        if not re.match(r"^[a-z0-9_\-]{1,256}$", room_id, re.IGNORECASE):
            return False, "Invalid room ID format"
        return True, None

    @staticmethod
    def validate_user_id(user_id: str) -> Tuple[bool, Optional[str]]:
        """Validate user ID format and size."""
        if len(user_id) > SizeValidator.MAX_USER_ID:
            return False, f"User ID too long (max {SizeValidator.MAX_USER_ID} chars)"
        if not re.match(r"^[a-z0-9_\-]{1,256}$", user_id, re.IGNORECASE):
            return False, "Invalid user ID format"
        return True, None


# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

async def handle_validated_message(
    message: WebSocketMessage,
    user_id: str,
    room_id: str,
    orchestrator,
    conversation_engine,
) -> Optional[dict]:
    """
    Route a validated message to the appropriate handler.

    Returns error dict if processing fails, None on success.
    """
    try:
        if isinstance(message, ChatMessage):
            # TODO: call orchestrator.handle_message
            return None

        elif isinstance(message, FeedbackMessage):
            # TODO: call conversation_engine.record_feedback
            return None

        elif isinstance(message, CorrectionMessage):
            # TODO: call conversation_engine.record_correction
            return None

        elif isinstance(message, PingMessage):
            # Pings are handled by WebSocket layer directly
            return None

        elif isinstance(message, SetPersonaMessage):
            # TODO: call persona_registry.set_session_persona
            return None

        else:
            return {"error": "Unknown message type"}

    except Exception as e:
        logger.error("Error processing message: %s", e, exc_info=True)
        return {"error": "Internal error"}


# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log_security_event(
    event_type: str,
    user_id: str,
    room_id: str,
    details: Optional[dict] = None,
):
    """Log security-relevant events for audit trail."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "user_id": user_id,
        "room_id": room_id,
    }
    if details:
        entry.update(details)
    logger.warning(json.dumps(entry))


# ============================================================================
# QUICK START INTEGRATION
# ============================================================================

"""
To integrate into main.py:

1. Add to imports:
    from security import (
        parse_websocket_message,
        RateLimiter,
        TokenAuth,
        SizeValidator,
        log_security_event,
    )

2. In startup():
    security_rate_limiter = RateLimiter(max_messages_per_minute=30)
    token_auth = TokenAuth(secret=os.getenv("SECRET_KEY", "dev-only"))

3. In websocket_endpoint():
    user_id = websocket.query_params.get("user_id", f"user_{uuid.uuid4().hex[:8]}")
    
    # Validate IDs
    valid, error = SizeValidator.validate_user_id(user_id)
    if not valid:
        await websocket.close(code=1008, reason=error)
        return
    
    valid, error = SizeValidator.validate_room_id(room_id)
    if not valid:
        await websocket.close(code=1008, reason=error)
        return

4. In message handling loop:
    # Parse + validate message
    message, error = parse_websocket_message(data)
    if error:
        await websocket.send_json({"type": "error", "error": error})
        continue
    
    # Rate limit check
    allowed, reason = security_rate_limiter.is_allowed(user_id)
    if not allowed:
        log_security_event("rate_limit_exceeded", user_id, room_id)
        await websocket.send_json({"type": "error", "error": reason})
        continue
    
    # Size validate
    if isinstance(message, ChatMessage):
        valid, error = SizeValidator.validate_message_size(message.text)
        if not valid:
            await websocket.send_json({"type": "error", "error": error})
            continue
    
    # Now process the validated message
    async for event in orchestrator.handle_message(room_id, user_id, message.text):
        ...
"""
