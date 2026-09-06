#!/usr/bin/env python3
# PubCast AI — mocap_integration.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
MOTION CAPTURE INTEGRATION FOR PUBCAST AI v7.0
===============================================
Real-time motion capture data streaming and avatar animation

Supports:
- Live mocap streaming (UDP/WebSocket)
- Multiple rig formats
- Avatar skeleton mapping
- Studio Control integration (mocap-triggered recording)
- Rust engine coordination via Pete Enhanced

Data Format (from frame-example.json):
{
  "ts": 1700000000000,          # Timestamp (ms)
  "rigId": "rig-01",            # Rig identifier
  "joints": {
    "hips": {"x": 0, "y": 0, "z": 0},
    "spine": {"x": 0, "y": 0.2, "z": 0},
    "left_knee": {"x": 0.15, "y": -0.4, "z": 0},
    ...
  }
}

Usage:
    from modules.mocap_integration import MocapStreamManager
    
    mocap = MocapStreamManager(hub, pete_enhanced)
    await mocap.start_stream("udp://localhost:9001")
    
    # Stream will automatically:
    # - Apply joint data to avatars
    # - Trigger Studio Control recording
    # - Send to Rust engine for rendering
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
import socket

if TYPE_CHECKING:
    from modules.hub import Hub
    from pete_enhanced import PeteEnhanced

logger = logging.getLogger("pubcast.mocap")


# ─────────────────────────────────────────────
# ENUMS AND DATA CLASSES
# ─────────────────────────────────────────────

class MocapStreamStatus(Enum):
    """Motion capture stream status"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


class MocapQuality(Enum):
    """Motion capture quality levels"""
    LOW = "low"           # 30 fps, basic joints
    MEDIUM = "medium"     # 60 fps, full skeleton
    HIGH = "high"         # 120 fps, full skeleton + fingers
    ULTRA = "ultra"       # 240 fps, full body + facial


@dataclass
class Joint:
    """3D joint position"""
    x: float
    y: float
    z: float
    
    # Optional rotation (quaternion)
    qx: Optional[float] = None
    qy: Optional[float] = None
    qz: Optional[float] = None
    qw: Optional[float] = None
    
    # Confidence (0.0 - 1.0)
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary"""
        d = {"x": self.x, "y": self.y, "z": self.z}
        if self.qx is not None:
            d.update({"qx": self.qx, "qy": self.qy, "qz": self.qz, "qw": self.qw})
        if self.confidence < 1.0:
            d["confidence"] = self.confidence
        return d


@dataclass
class MocapFrame:
    """Complete motion capture frame"""
    timestamp: int  # Milliseconds since epoch
    rig_id: str
    joints: Dict[str, Joint]
    
    # Frame metadata
    frame_number: Optional[int] = None
    fps: Optional[float] = None
    quality: MocapQuality = MocapQuality.MEDIUM
    
    # Additional tracking
    hands: Optional[Dict[str, Any]] = None
    face: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MocapFrame':
        """Parse from JSON dict"""
        joints = {}
        for joint_name, joint_data in data.get("joints", {}).items():
            joints[joint_name] = Joint(**joint_data)
        
        return cls(
            timestamp=data.get("ts", int(time.time() * 1000)),
            rig_id=data.get("rigId", "unknown"),
            joints=joints,
            frame_number=data.get("frameNumber"),
            fps=data.get("fps"),
            quality=MocapQuality(data.get("quality", "medium"))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "ts": self.timestamp,
            "rigId": self.rig_id,
            "joints": {name: joint.to_dict() for name, joint in self.joints.items()},
            "frameNumber": self.frame_number,
            "fps": self.fps,
            "quality": self.quality.value
        }


@dataclass
class MocapStreamMetrics:
    """Mocap stream performance metrics"""
    frames_received: int = 0
    frames_dropped: int = 0
    avg_fps: float = 0.0
    avg_latency_ms: float = 0.0
    last_frame_time: float = 0.0
    
    # Quality
    avg_joint_confidence: float = 1.0
    tracking_quality: MocapQuality = MocapQuality.MEDIUM


# ─────────────────────────────────────────────
# SKELETON MAPPINGS
# ─────────────────────────────────────────────

# Standard skeleton joint names
STANDARD_SKELETON = [
    # Core
    "hips", "spine", "chest", "neck", "head",
    # Left arm
    "left_shoulder", "left_elbow", "left_wrist", "left_hand",
    # Right arm
    "right_shoulder", "right_elbow", "right_wrist", "right_hand",
    # Left leg
    "left_hip", "left_knee", "left_ankle", "left_foot",
    # Right leg
    "right_hip", "right_knee", "right_ankle", "right_foot"
]

# Avatar mapping (maps mocap joints to avatar bones)
AVATAR_SKELETON_MAPPING = {
    # Mocap joint name → Avatar bone name
    "hips": "root",
    "spine": "spine1",
    "chest": "spine2",
    "neck": "neck",
    "head": "head",
    "left_shoulder": "l_shoulder",
    "left_elbow": "l_elbow",
    "left_wrist": "l_wrist",
    "right_shoulder": "r_shoulder",
    "right_elbow": "r_elbow",
    "right_wrist": "r_wrist",
    "left_knee": "l_knee",
    "right_knee": "r_knee",
    # Add more mappings as needed
}


# ─────────────────────────────────────────────
# MOCAP STREAM RECEIVERS
# ─────────────────────────────────────────────

class UDPMocapReceiver:
    """
    Receives mocap frames via UDP
    
    Perfect for low-latency local streaming from mocap software
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 9001):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self._running = False
    
    async def start(self, frame_callback):
        """Start receiving frames"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        self.socket.setblocking(False)
        
        self._running = True
        logger.info(f"📡 UDP mocap receiver listening on {self.host}:{self.port}")
        
        while self._running:
            try:
                # Non-blocking receive
                data, addr = await asyncio.get_running_loop().sock_recvfrom(self.socket, 65536)
                
                # Parse JSON frame
                frame_data = json.loads(data.decode('utf-8'))
                frame = MocapFrame.from_dict(frame_data)
                
                # Call frame handler
                await frame_callback(frame)
                
            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid mocap frame JSON: {e}")
            except Exception as e:
                logger.error(f"UDP receive error: {e}")
                await asyncio.sleep(0.01)
    
    async def stop(self):
        """Stop receiving"""
        self._running = False
        if self.socket:
            self.socket.close()
        logger.info("📡 UDP mocap receiver stopped")


class WebSocketMocapReceiver:
    """
    Receives mocap frames via WebSocket
    
    Perfect for streaming from web-based mocap systems or remote sources
    """
    
    def __init__(self, url: str):
        self.url = url
        self.websocket = None
        self._running = False
    
    async def start(self, frame_callback):
        """Start receiving frames"""
        import websockets
        
        self._running = True
        logger.info(f"📡 WebSocket mocap receiver connecting to {self.url}")
        
        try:
            async with websockets.connect(self.url) as websocket:
                self.websocket = websocket
                logger.info("📡 WebSocket mocap connected")
                
                while self._running:
                    try:
                        # Receive frame
                        data = await websocket.recv()
                        
                        # Parse JSON
                        frame_data = json.loads(data)
                        frame = MocapFrame.from_dict(frame_data)
                        
                        # Call frame handler
                        await frame_callback(frame)
                        
                    except asyncio.CancelledError:
                        break
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid mocap frame JSON: {e}")
                    except Exception as e:
                        logger.error(f"WebSocket receive error: {e}")
                        await asyncio.sleep(0.01)
        
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
    
    async def stop(self):
        """Stop receiving"""
        self._running = False
        if self.websocket:
            await self.websocket.close()
        logger.info("📡 WebSocket mocap receiver stopped")


# ─────────────────────────────────────────────
# MAIN MOCAP MANAGER
# ─────────────────────────────────────────────

class MocapStreamManager:
    """
    Manages motion capture streaming for PubCast AI
    
    Responsibilities:
    - Receive mocap frames from various sources
    - Apply joint data to avatars
    - Integrate with Studio Control (trigger recording on movement)
    - Send frames to Pete/Rust engine for rendering
    - Track stream quality and performance
    
    Integration Points:
    - Hub: Broadcast frames to WebSocket clients
    - Pete Enhanced: Send to Rust engine for rendering
    - Studio Control: Auto-trigger recording when mocap starts
    - Avatar System: Map joints to avatar skeleton
    """
    
    def __init__(
        self,
        hub: 'Hub',
        pete: Optional['PeteEnhanced'] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        self.hub = hub
        self.pete = pete
        self.config = config or {}
        
        # Stream state
        self.status = MocapStreamStatus.DISCONNECTED
        self.receiver: Optional[Any] = None
        self.current_rig_id: Optional[str] = None
        
        # Frame buffer
        self._frame_buffer: List[MocapFrame] = []
        self._max_buffer_size = self.config.get("max_buffer_size", 60)  # 1 second at 60fps
        
        # Metrics
        self.metrics = MocapStreamMetrics()
        
        # Avatar mapping
        self._active_avatar_id: Optional[str] = None
        self._skeleton_mapping = AVATAR_SKELETON_MAPPING.copy()
        
        # Recording integration
        self._auto_start_recording = self.config.get("auto_start_recording", True)
        self._recording_started = False
        
        logger.info("🎭 Mocap Stream Manager initialized")
    
    # ─────────────────────────────────────────────
    # STREAM CONTROL
    # ─────────────────────────────────────────────
    
    async def start_stream(self, source_url: str) -> bool:
        """
        Start receiving mocap stream
        
        Supported URLs:
        - udp://localhost:9001
        - ws://localhost:8080/mocap
        - wss://remote-server.com/mocap
        """
        if self.status == MocapStreamStatus.STREAMING:
            logger.warning("Mocap stream already active")
            return False
        
        logger.info(f"🎭 Starting mocap stream: {source_url}")
        self.status = MocapStreamStatus.CONNECTING
        
        try:
            # Parse URL
            if source_url.startswith("udp://"):
                # UDP stream
                parts = source_url.replace("udp://", "").split(":")
                host = parts[0]
                port = int(parts[1]) if len(parts) > 1 else 9001
                
                self.receiver = UDPMocapReceiver(host, port)
                
            elif source_url.startswith("ws://") or source_url.startswith("wss://"):
                # WebSocket stream
                self.receiver = WebSocketMocapReceiver(source_url)
                
            else:
                logger.error(f"Unsupported mocap source URL: {source_url}")
                self.status = MocapStreamStatus.ERROR
                return False
            
            # Start receiver
            self._receive_task = asyncio.create_task(self.receiver.start(self._on_frame_received))
            
            self.status = MocapStreamStatus.STREAMING
            logger.info("🎭 Mocap stream started successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start mocap stream: {e}", exc_info=True)
            self.status = MocapStreamStatus.ERROR
            return False
    
    async def stop_stream(self) -> None:
        """Stop mocap stream"""
        if self.receiver:
            await self.receiver.stop()
            self.receiver = None
        
        self.status = MocapStreamStatus.DISCONNECTED
        self._frame_buffer.clear()
        self._recording_started = False
        
        logger.info("🎭 Mocap stream stopped")
    
    # ─────────────────────────────────────────────
    # FRAME PROCESSING
    # ─────────────────────────────────────────────
    
    async def _on_frame_received(self, frame: MocapFrame) -> None:
        """
        Handle received mocap frame
        
        This is called for every frame received from the stream.
        """
        # Update metrics
        self.metrics.frames_received += 1
        current_time = time.time()
        
        if self.metrics.last_frame_time > 0:
            frame_delta = current_time - self.metrics.last_frame_time
            if frame_delta > 0:
                instant_fps = 1.0 / frame_delta
                # Exponential moving average
                self.metrics.avg_fps = (self.metrics.avg_fps * 0.9) + (instant_fps * 0.1)
        
        self.metrics.last_frame_time = current_time
        
        # Calculate latency
        latency_ms = (current_time * 1000) - frame.timestamp
        self.metrics.avg_latency_ms = (self.metrics.avg_latency_ms * 0.9) + (latency_ms * 0.1)
        
        # Update current rig
        self.current_rig_id = frame.rig_id
        
        # Add to buffer
        self._frame_buffer.append(frame)
        if len(self._frame_buffer) > self._max_buffer_size:
            self._frame_buffer.pop(0)
        
        # Auto-start recording on first movement
        if self._auto_start_recording and not self._recording_started:
            await self._trigger_recording_start()
        
        # Apply to avatar
        if self._active_avatar_id:
            await self._apply_frame_to_avatar(frame, self._active_avatar_id)
        
        # Send to Rust engine via Pete
        if self.pete:
            await self._send_frame_to_rust_engine(frame)
        
        # Broadcast to WebSocket clients
        await self._broadcast_frame(frame)
    
    async def _trigger_recording_start(self) -> None:
        """Trigger Studio Control to start recording"""
        logger.info("🎭 Mocap movement detected - triggering recording start")
        self._recording_started = True
        
        # TODO: Integrate with Studio Control
        # if self.studio_control:
        #     await self.studio_control.run_preflight_sequence()
    
    async def _apply_frame_to_avatar(self, frame: MocapFrame, avatar_id: str) -> None:
        """
        Apply mocap frame to avatar skeleton
        
        Maps mocap joints to avatar bones using skeleton mapping
        """
        # Map joints to avatar bones
        avatar_bones = {}
        for mocap_joint, avatar_bone in self._skeleton_mapping.items():
            if mocap_joint in frame.joints:
                joint = frame.joints[mocap_joint]
                avatar_bones[avatar_bone] = {
                    "position": [joint.x, joint.y, joint.z],
                    "rotation": [joint.qx, joint.qy, joint.qz, joint.qw] if joint.qx is not None else None
                }
        
        # TODO: Send to avatar system
        # await self.avatar_system.update_skeleton(avatar_id, avatar_bones)
        
        logger.debug(f"Applied frame to avatar {avatar_id}: {len(avatar_bones)} bones")
    
    async def _send_frame_to_rust_engine(self, frame: MocapFrame) -> None:
        """Send mocap frame to Rust engine via Pete"""
        if not self.pete:
            return
        
        # TODO: Pete integration
        # await self.pete.send_mocap_frame(frame.to_dict())
        
        logger.debug(f"Sent frame to Rust engine: {frame.frame_number}")
    
    async def _broadcast_frame(self, frame: MocapFrame) -> None:
        """Broadcast frame to WebSocket clients"""
        if not self.hub:
            return
        
        # Broadcast to all connected clients
        message = {
            "type": "mocap_frame",
            "frame": frame.to_dict(),
            "metrics": {
                "fps": round(self.metrics.avg_fps, 1),
                "latency_ms": round(self.metrics.avg_latency_ms, 1)
            }
        }
        
        # TODO: Hub broadcast
        # await self.hub.broadcast("mocap", message)
    
    # ─────────────────────────────────────────────
    # AVATAR CONTROL
    # ─────────────────────────────────────────────
    
    def set_active_avatar(self, avatar_id: str) -> None:
        """Set which avatar receives mocap data"""
        self._active_avatar_id = avatar_id
        logger.info(f"🎭 Active mocap avatar: {avatar_id}")
    
    def update_skeleton_mapping(self, mapping: Dict[str, str]) -> None:
        """Update mocap joint → avatar bone mapping"""
        self._skeleton_mapping.update(mapping)
        logger.info(f"🎭 Skeleton mapping updated: {len(mapping)} joints")
    
    # ─────────────────────────────────────────────
    # STATUS AND METRICS
    # ─────────────────────────────────────────────
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete mocap status"""
        return {
            "status": self.status.value,
            "rig_id": self.current_rig_id,
            "active_avatar": self._active_avatar_id,
            "recording_started": self._recording_started,
            "metrics": {
                "frames_received": self.metrics.frames_received,
                "frames_dropped": self.metrics.frames_dropped,
                "avg_fps": round(self.metrics.avg_fps, 1),
                "avg_latency_ms": round(self.metrics.avg_latency_ms, 1),
                "buffer_size": len(self._frame_buffer)
            }
        }
    
    def get_latest_frame(self) -> Optional[MocapFrame]:
        """Get most recent frame from buffer"""
        return self._frame_buffer[-1] if self._frame_buffer else None
    
    def get_frame_buffer(self, max_frames: int = 60) -> List[MocapFrame]:
        """Get recent frames from buffer"""
        return self._frame_buffer[-max_frames:]
