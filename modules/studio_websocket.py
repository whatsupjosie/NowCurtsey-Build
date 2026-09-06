#!/usr/bin/env python3
# PubCast AI — studio_websocket.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
STUDIO CONTROL WEBSOCKET HANDLER
==================================
WebSocket bridge between the Studio Control Room HTML interface
and the Python backend (studio_control.py + Pete Enhanced).

This provides real-time bidirectional communication:
- JavaScript sends commands → Python executes
- Python sends state updates → JavaScript renders

Architecture:
    Browser <─ WebSocket ─> StudioWebSocketHandler <─> StudioControl <─> Pete
"""

from __future__ import annotations

import asyncio
import logging
import json
from typing import Dict, Any, Optional, Set
from datetime import datetime

try:
    from fastapi import WebSocket, WebSocketDisconnect
    from fastapi.websockets import WebSocketState
except ImportError:
    WebSocket = Any  # Fallback for type hints

from .studio_control import StudioControl, StudioState

logger = logging.getLogger("pubcast.studio_websocket")


class StudioWebSocketHandler:
    """
    WebSocket handler for Studio Control Room
    
    Manages WebSocket connections from the browser interface
    and routes commands to/from the StudioControl backend.
    """
    
    def __init__(self, studio_control: StudioControl):
        self.studio_control = studio_control
        self._active_connections: Set[WebSocket] = set()
        self._message_handlers: Dict[str, callable] = {}
        self._setup_message_handlers()
        
        logger.info("📡 Studio WebSocket Handler initialized")
    
    def _setup_message_handlers(self):
        """Register command handlers for incoming messages"""
        self._message_handlers = {
            'start_preflight': self._handle_start_preflight,
            'stop_recording': self._handle_stop_recording,
            'emergency_save': self._handle_emergency_save,
            'mute_all_but_dialogue': self._handle_mute_all_but_dialogue,
            'unmute_all': self._handle_unmute_all,
            'toggle_channel': self._handle_toggle_channel,
            'get_status': self._handle_get_status,
        }
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection"""
        await websocket.accept()
        self._active_connections.add(websocket)
        self.studio_control.register_ws_client(websocket)
        
        logger.info(f"📡 WebSocket connected ({len(self._active_connections)} active)")
        
        # Send initial state
        await self._send_initial_state(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Handle WebSocket disconnect"""
        if websocket in self._active_connections:
            self._active_connections.remove(websocket)
            self.studio_control.unregister_ws_client(websocket)
        
        logger.info(f"📡 WebSocket disconnected ({len(self._active_connections)} remaining)")
    
    async def handle_message(self, websocket: WebSocket, data: Dict[str, Any]):
        """Route incoming message to appropriate handler"""
        command = data.get('command')
        
        if not command:
            logger.warning(f"Invalid message received: {data}")
            return
        
        handler = self._message_handlers.get(command)
        if not handler:
            logger.warning(f"Unknown command: {command}")
            await self._send_error(websocket, f"Unknown command: {command}")
            return
        
        try:
            await handler(websocket, data)
        except Exception as e:
            logger.error(f"Error handling command '{command}': {e}", exc_info=True)
            await self._send_error(websocket, f"Command failed: {e}")
    
    # ─────────────────────────────────────────────
    # COMMAND HANDLERS
    # ─────────────────────────────────────────────
    
    async def _handle_start_preflight(self, websocket: WebSocket, data: Dict[str, Any]):
        """Start the 5-second preflight countdown"""
        logger.info("🎬 WebSocket command: start_preflight")
        success = await self.studio_control.run_preflight_sequence()
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'start_preflight',
            'success': success,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_stop_recording(self, websocket: WebSocket, data: Dict[str, Any]):
        """Stop active recording"""
        logger.info("⏹️ WebSocket command: stop_recording")
        await self.studio_control.stop_recording()
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'stop_recording',
            'success': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_emergency_save(self, websocket: WebSocket, data: Dict[str, Any]):
        """Trigger emergency save"""
        reason = data.get('reason', 'WebSocket command')
        logger.critical(f"🚨 WebSocket command: emergency_save - {reason}")
        await self.studio_control.trigger_emergency_save(reason)
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'emergency_save',
            'success': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_mute_all_but_dialogue(self, websocket: WebSocket, data: Dict[str, Any]):
        """Activate isolation mode (dialogue only)"""
        logger.info("🔇 WebSocket command: mute_all_but_dialogue")
        await self.studio_control.mute_all_but_dialogue()
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'mute_all_but_dialogue',
            'success': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_unmute_all(self, websocket: WebSocket, data: Dict[str, Any]):
        """Unmute all audio channels"""
        logger.info("🔊 WebSocket command: unmute_all")
        await self.studio_control.unmute_all_channels()
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'unmute_all',
            'success': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_toggle_channel(self, websocket: WebSocket, data: Dict[str, Any]):
        """Toggle individual audio channel"""
        channel_id = data.get('channel_id')
        active = data.get('active')
        
        if not channel_id or active is None:
            await self._send_error(websocket, "Missing channel_id or active parameter")
            return
        
        logger.info(f"🎚️ WebSocket command: toggle_channel - {channel_id} = {active}")
        await self.studio_control.update_audio_channel(channel_id, -60.0, active)
        
        await self._send_message(websocket, {
            'type': 'command_response',
            'command': 'toggle_channel',
            'success': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_get_status(self, websocket: WebSocket, data: Dict[str, Any]):
        """Get complete studio status"""
        status = self.studio_control.get_status_summary()
        
        await self._send_message(websocket, {
            'type': 'status_response',
            'status': status,
            'timestamp': datetime.now().isoformat()
        })
    
    # ─────────────────────────────────────────────
    # OUTGOING MESSAGES
    # ─────────────────────────────────────────────
    
    async def _send_initial_state(self, websocket: WebSocket):
        """Send initial state when client connects"""
        status = self.studio_control.get_status_summary()
        
        await self._send_message(websocket, {
            'type': 'initial_state',
            'status': status,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _send_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send message to specific WebSocket client"""
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    async def _send_error(self, websocket: WebSocket, error: str):
        """Send error message to client"""
        await self._send_message(websocket, {
            'type': 'error',
            'error': error,
            'timestamp': datetime.now().isoformat()
        })
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        disconnected = []
        
        for websocket in self._active_connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                else:
                    disconnected.append(websocket)
            except Exception as e:
                logger.error(f"Broadcast failed: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)


# ─────────────────────────────────────────────
# FASTAPI INTEGRATION
# ─────────────────────────────────────────────

def create_studio_websocket_endpoint(studio_control: StudioControl):
    """
    Create FastAPI WebSocket endpoint for Studio Control Room
    
    Usage in your FastAPI app:
    
        from studio_websocket import create_studio_websocket_endpoint
        
        studio_control = StudioControl(hub, pete, data_dir)
        studio_ws_handler = create_studio_websocket_endpoint(studio_control)
        
        @app.websocket("/ws/studio")
        async def websocket_studio(websocket: WebSocket):
            await studio_ws_handler.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_json()
                    await studio_ws_handler.handle_message(websocket, data)
            except WebSocketDisconnect:
                await studio_ws_handler.disconnect(websocket)
    """
    return StudioWebSocketHandler(studio_control)


# ─────────────────────────────────────────────
# EXAMPLE USAGE
# ─────────────────────────────────────────────

"""
Example integration with PubCast AI's hub system:

# In your main.py or hub.py:

from .studio_control import StudioControl
from studio_websocket import create_studio_websocket_endpoint
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

# Initialize Studio Control
studio_control = StudioControl(hub, pete, data_dir)
studio_ws_handler = create_studio_websocket_endpoint(studio_control)

@app.websocket("/ws/studio")
async def websocket_studio(websocket: WebSocket):
    await studio_ws_handler.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await studio_ws_handler.handle_message(websocket, data)
    except WebSocketDisconnect:
        await studio_ws_handler.disconnect(websocket)

# Serve the Studio Control Room HTML
@app.get("/studio")
async def get_studio():
    with open("studio_control_room.html") as f:
        return HTMLResponse(f.read())
"""
