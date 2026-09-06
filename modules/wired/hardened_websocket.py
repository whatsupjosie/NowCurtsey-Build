"""
Hardened WebSocket handler for PubCast AI.
Drop-in replacement with input validation, rate limiting, and error recovery.

Usage:
    Replace the websocket_endpoint in main.py with this implementation.
"""

import json
import logging
from typing import Optional
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect, WebSocketException
from pydantic import ValidationError

from schemas import validate_websocket_message, ErrorEventResponse, PongMessage
from rate_limiter import RateLimiter
from orchestrator_hardening import OrchestratorHardener

logger = logging.getLogger("pubcast.websocket")


class HardenedWebSocketHandler:
    """
    Manages WebSocket connections with hardening applied.
    """
    
    def __init__(
        self,
        orchestrator,
        rate_limiter: RateLimiter,
        hardener: OrchestratorHardener,
        ping_interval: float = 30.0,
    ):
        """
        Args:
            orchestrator: The WiredOrchestrator instance
            rate_limiter: RateLimiter instance
            hardener: OrchestratorHardener instance
            ping_interval: Seconds between heartbeat pings
        """
        self.orchestrator = orchestrator
        self.rate_limiter = rate_limiter
        self.hardener = hardener
        self.ping_interval = ping_interval
    
    async def handle_connection(
        self,
        websocket: WebSocket,
        room_id: str,
        user_id: str,
    ):
        """
        Main WebSocket connection handler.
        
        Args:
            websocket: FastAPI WebSocket
            room_id: Room to join
            user_id: User identifier
        """
        try:
            await websocket.accept()
            logger.info(f"User {user_id} connected to room {room_id}")
            
            # Send welcome message
            await websocket.send_json({
                "type": "connected",
                "user_id": user_id,
                "room_id": room_id,
                "message": f"Connected as {user_id} in room {room_id}",
            })
            
            # Main message loop
            while True:
                try:
                    data = await websocket.receive_text()
                    
                    # Parse and validate JSON
                    try:
                        message_dict = json.loads(data)
                    except json.JSONDecodeError as e:
                        await self._send_error(
                            websocket,
                            "Invalid JSON",
                            error_code="invalid_json"
                        )
                        continue
                    
                    # Validate against schema
                    try:
                        msg_type, validated_msg = validate_websocket_message(message_dict)
                    except ValueError as e:
                        await self._send_error(
                            websocket,
                            str(e),
                            error_code="validation_error"
                        )
                        continue
                    
                    # Rate limiting check
                    allowed, reason = self.rate_limiter.is_allowed(
                        user_id=user_id,
                        room_id=room_id
                    )
                    if not allowed:
                        await self._send_error(
                            websocket,
                            f"Rate limit exceeded ({reason})",
                            error_code=reason
                        )
                        continue
                    
                    # Route to handler
                    if msg_type == "chat":
                        await self._handle_chat_message(
                            websocket, room_id, user_id, validated_msg
                        )
                    elif msg_type == "ping":
                        await self._handle_ping(websocket, validated_msg)
                    elif msg_type == "feedback":
                        await self._handle_feedback(websocket, user_id, validated_msg)
                    elif msg_type == "correction":
                        await self._handle_correction(websocket, user_id, validated_msg)
                    elif msg_type == "set_persona":
                        await self._handle_set_persona(websocket, user_id, validated_msg)
                    else:
                        await self._send_error(
                            websocket,
                            f"Unknown message type: {msg_type}",
                            error_code="unknown_type"
                        )
                
                except WebSocketDisconnect:
                    logger.info(f"User {user_id} disconnected from room {room_id}")
                    break
                except Exception as e:
                    logger.error(
                        f"Error handling message for {user_id}: {str(e)}",
                        exc_info=True
                    )
                    try:
                        await self._send_error(
                            websocket,
                            "Internal server error",
                            error_code="internal_error"
                        )
                    except Exception:
                        break
        
        except Exception as e:
            logger.error(f"WebSocket error for {user_id}: {str(e)}", exc_info=True)
            try:
                await websocket.close(code=1011, reason="Internal server error")
            except Exception:
                pass
    
    async def _handle_chat_message(self, websocket, room_id, user_id, message):
        """Handle incoming chat message."""
        text = message.text
        logger.info(f"Chat from {user_id} in {room_id}: {text[:50]}...")
        
        try:
            # Execute orchestration with timeout and error recovery
            async def orchestration():
                async for event in self.orchestrator.handle_message(
                    room_id=room_id,
                    user_id=user_id,
                    message=text
                ):
                    # Send stream events to client
                    if event.get('event_type') == 'stream':
                        await websocket.send_json({
                            "type": "stream",
                            "agent_id": event.get('agent_id'),
                            "chunk": event.get('payload', ''),
                        })
                    elif event.get('event_type') == 'complete':
                        await websocket.send_json({
                            "type": "complete",
                            "agent_id": event.get('agent_id'),
                            "message_id": event.get('message_id'),
                        })
                    elif event.get('event_type') == 'error':
                        await websocket.send_json({
                            "type": "error",
                            "error": event.get('payload', {}).get('error', 'Unknown error'),
                            "agent_id": event.get('agent_id'),
                        })
            
            await self.hardener.execute_orchestration(
                orchestration(),
                error_handler=self._create_error_handler(websocket)
            )
        
        except asyncio.TimeoutError:
            await self._send_error(
                websocket,
                "Response generation timed out. Please try again.",
                error_code="orchestration_timeout"
            )
        except Exception as e:
            logger.error(f"Orchestration failed: {str(e)}", exc_info=True)
            await self._send_error(
                websocket,
                "Failed to generate response",
                error_code="orchestration_error"
            )
    
    async def _handle_ping(self, websocket, message):
        """Handle heartbeat ping."""
        pong = PongMessage(timestamp=datetime.now().timestamp())
        await websocket.send_json(pong.model_dump())
    
    async def _handle_feedback(self, websocket, user_id, message):
        """Handle user feedback."""
        logger.info(
            f"Feedback from {user_id}: response_id={message.response_id}, "
            f"positive={message.positive}"
        )
        
        try:
            # Pass to learning layer
            if hasattr(self.orchestrator, 'learning_layer'):
                self.orchestrator.learning_layer.record_feedback(
                    user_id=user_id,
                    intent_name="user_feedback",
                    response=message.response_id,
                    positive=message.positive
                )
            
            await websocket.send_json({
                "type": "feedback_ack",
                "response_id": message.response_id,
            })
        except Exception as e:
            logger.error(f"Feedback handling failed: {str(e)}")
            await self._send_error(websocket, "Failed to record feedback")
    
    async def _handle_correction(self, websocket, user_id, message):
        """Handle intent correction."""
        logger.info(
            f"Correction from {user_id}: message_id={message.message_id}, "
            f"correct_intent={message.correct_intent}"
        )
        
        try:
            if hasattr(self.orchestrator, 'learning_layer'):
                self.orchestrator.learning_layer.record_correction(
                    user_id=user_id,
                    message=message.message_id,
                    correct_intent=message.correct_intent,
                    original_intent=message.original_intent or ""
                )
            
            await websocket.send_json({
                "type": "correction_ack",
                "message_id": message.message_id,
            })
        except Exception as e:
            logger.error(f"Correction handling failed: {str(e)}")
            await self._send_error(websocket, "Failed to record correction")
    
    async def _handle_set_persona(self, websocket, user_id, message):
        """Handle persona selection."""
        logger.info(f"Persona change for {user_id}: {message.persona_name}")
        
        try:
            # Validate persona exists
            if hasattr(self.orchestrator, 'persona_registry'):
                if message.persona_name not in self.orchestrator.persona_registry.personas:
                    await self._send_error(
                        websocket,
                        f"Unknown persona: {message.persona_name}",
                        error_code="unknown_persona"
                    )
                    return
            
            # Set session persona
            if hasattr(self.orchestrator, 'set_session_persona'):
                self.orchestrator.set_session_persona(
                    user_id=user_id,
                    persona_name=message.persona_name
                )
            
            await websocket.send_json({
                "type": "persona_set",
                "persona_name": message.persona_name,
            })
        except Exception as e:
            logger.error(f"Persona setting failed: {str(e)}")
            await self._send_error(websocket, "Failed to set persona")
    
    async def _send_error(
        self,
        websocket: WebSocket,
        error_msg: str,
        error_code: str = "error",
        recoverable: bool = True
    ):
        """Send error response to client."""
        response = ErrorEventResponse(
            error=error_msg,
            error_code=error_code,
            recoverable=recoverable
        )
        try:
            await websocket.send_json(response.model_dump())
        except Exception as e:
            logger.error(f"Failed to send error response: {str(e)}")
    
    def _create_error_handler(self, websocket):
        """Create error handler for orchestration."""
        async def handler(error: str):
            await self._send_error(
                websocket,
                f"Processing failed: {error}",
                error_code="processing_error"
            )
        return handler


# Import asyncio after function definitions
import asyncio
