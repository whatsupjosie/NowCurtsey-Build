"""
DISTRIBUTED ENGINE NODE
=======================
Unified engine that can run as:
- Twin Engine (PRIMARY): Full power, handles video broadcast + computation
- Camera Engine (NODE): Single instance, processes own footage, can assist primary

Each camera runs a lightweight version of this engine, contributing
processing power during emergency backup scenarios.

"Audio Never Sacrificed" - Core principle

Copyright (c) 2024-2025 Rear View Foresight LLC
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import psutil
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from modules.irm import IRMController, IRMSensor, IRMActuator, HealthStatus, HealthReport
from modules.circuit_breaker import CircuitBreaker, CircuitOpenError, get_breaker
from modules.bridge import TwinEngineBridge, UDPBridge, MessageType, BridgeMessage

logger = logging.getLogger(__name__)


# =============================================================================
# ENGINE CONFIGURATION
# =============================================================================

class EngineMode(str, Enum):
    """Engine operating mode"""
    TWIN = "twin"          # Primary engine - full power
    CAMERA = "camera"      # Camera node - single instance
    STANDBY = "standby"    # Ready but not processing
    ASSISTANCE = "assistance"  # Helping primary engine


class EngineRole(str, Enum):
    """Current role in distributed system"""
    PRIMARY = "primary"              # Main processing
    BACKUP_50 = "backup_50"          # 50% backup load
    BACKUP_100 = "backup_100"        # 100% backup load
    STANDBY = "standby"              # Ready but idle
    QUALITY_REDUCED = "quality_reduced"  # Running at reduced quality


class SystemState(str, Enum):
    """Overall distributed system state"""
    NORMAL = "normal"        # All green
    ELEVATED = "elevated"    # Cam3 assisting
    CRITICAL = "critical"    # Cam2+3 assisting
    EMERGENCY = "emergency"  # All cameras helping
    RECOVERY = "recovery"    # Returning to normal
    FAILURE = "failure"      # System down


@dataclass
class EngineConfig:
    """Configuration for an engine node"""
    engine_id: str
    mode: EngineMode = EngineMode.CAMERA
    
    # Network
    primary_host: str = "127.0.0.1"
    primary_port: int = 9000
    listen_port: int = 9001
    
    # Processing limits
    max_batch_size: int = 10000
    min_batch_size: int = 500
    default_batch_size: int = 2500
    
    # Quality settings
    target_fps: int = 60
    quality_level: int = 100  # 0-100
    
    # Emergency thresholds
    assist_threshold_50: float = 75.0
    assist_threshold_100: float = 85.0
    emergency_threshold: float = 95.0
    
    # Timing
    heartbeat_interval: float = 1.0
    health_check_interval: float = 0.2


@dataclass
class EngineMetrics:
    """Real-time metrics for an engine"""
    engine_id: str
    timestamp: float = field(default_factory=time.time)
    
    # Resource usage
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    gpu_percent: float = 0.0
    
    # Processing
    processing_load: float = 0.0
    batch_size: int = 2500
    fps: float = 60.0
    frame_time_ms: float = 16.6
    
    # Health
    health_score: float = 100.0
    role: EngineRole = EngineRole.STANDBY
    last_heartbeat: float = 0.0
    
    # Audio (never sacrificed)
    audio_latency_ms: float = 0.0
    audio_dropouts: int = 0
    audio_quality: float = 100.0
    
    # Streams
    active_streams: int = 0
    dropped_frames: int = 0
    
    def calculate_load(self) -> float:
        """Calculate processing load from metrics"""
        # Weighted combination
        load = (
            self.cpu_percent * 0.4 +
            self.memory_percent * 0.2 +
            self.gpu_percent * 0.3 +
            (100.0 - self.health_score) * 0.1
        )
        return min(100.0, max(0.0, load))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'engine_id': self.engine_id,
            'timestamp': self.timestamp,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'gpu_percent': self.gpu_percent,
            'processing_load': self.processing_load,
            'batch_size': self.batch_size,
            'fps': self.fps,
            'health_score': self.health_score,
            'role': self.role.value,
            'audio_quality': self.audio_quality,
            'active_streams': self.active_streams
        }


# =============================================================================
# WORK UNIT FOR DISTRIBUTED PROCESSING
# =============================================================================

@dataclass
class WorkUnit:
    """A unit of work that can be distributed across engines"""
    work_id: str
    work_type: str  # "voxel_render", "mesh_generate", "audio_process", "video_encode"
    priority: int = 5  # 1 = highest, 10 = lowest
    data: bytes = b""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    deadline_ms: float = 100.0  # Must complete within
    
    # Routing
    source_engine: str = ""
    target_engine: str = ""
    
    # Result
    completed: bool = False
    result: Optional[bytes] = None
    error: Optional[str] = None


# =============================================================================
# DISTRIBUTED ENGINE NODE
# =============================================================================

class DistributedEngineNode:
    """
    A single node in the distributed processing system.
    Can operate as primary (twin engine) or secondary (camera engine).
    """
    
    def __init__(self, config: EngineConfig):
        self.config = config
        self.engine_id = config.engine_id
        self.mode = config.mode
        self.role = EngineRole.STANDBY
        self.state = SystemState.NORMAL
        
        # Metrics
        self.metrics = EngineMetrics(engine_id=config.engine_id)
        self._metrics_lock = threading.Lock()
        
        # IRM for adaptive performance
        self.irm = IRMController(
            window_size=10,
            min_batch=config.min_batch_size,
            max_batch=config.max_batch_size,
            default_batch=config.default_batch_size
        )
        
        # Circuit breaker for fault tolerance
        self.circuit_breaker = get_breaker(
            f"engine_{config.engine_id}",
            failure_threshold=5,
            recovery_timeout=30.0
        )
        
        # Communication
        self.bridge: Optional[TwinEngineBridge] = None
        self._udp_socket: Optional[socket.socket] = None
        
        # Work queue
        self._work_queue: asyncio.Queue = asyncio.Queue()
        self._pending_work: Dict[str, WorkUnit] = {}
        
        # Connected nodes (for primary engine)
        self._connected_nodes: Dict[str, EngineMetrics] = {}
        self._node_lock = threading.Lock()
        
        # State
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        # Callbacks
        self._on_state_change: List[Callable[[SystemState, SystemState], None]] = []
        self._on_work_complete: List[Callable[[WorkUnit], None]] = []
        
        logger.info(f"DistributedEngineNode created: {config.engine_id} ({config.mode.value})")
    
    # =========================================================================
    # LIFECYCLE
    # =========================================================================
    
    async def start(self) -> None:
        """Start the engine node"""
        if self._running:
            return
        
        logger.info(f"Starting engine node: {self.engine_id}")
        
        # Initialize bridge based on mode
        if self.mode == EngineMode.TWIN:
            self.bridge = TwinEngineBridge(
                use_shared_memory=True,
                use_udp=True,
                udp_local_port=self.config.primary_port
            )
        else:
            self.bridge = TwinEngineBridge(
                use_shared_memory=False,
                use_udp=True,
                udp_local_port=self.config.listen_port,
                udp_remote_port=self.config.primary_port
            )
        
        self.bridge.start()
        
        # Register message handlers
        self.bridge.on_message(MessageType.HEARTBEAT, self._handle_heartbeat)
        self.bridge.on_message(MessageType.COMMAND, self._handle_command)
        self.bridge.on_message(MessageType.METRICS, self._handle_metrics)
        
        self._running = True
        
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._metrics_loop()),
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._work_processor_loop()),
        ]
        
        if self.mode == EngineMode.TWIN:
            self._tasks.append(asyncio.create_task(self._load_balancer_loop()))
        
        # Set initial role
        if self.mode == EngineMode.TWIN:
            self.role = EngineRole.PRIMARY
        else:
            self.role = EngineRole.STANDBY
            # Announce to primary
            await self._announce_to_primary()
        
        logger.info(f"Engine node started: {self.engine_id} as {self.role.value}")
    
    async def stop(self) -> None:
        """Stop the engine node"""
        self._running = False
        
        # Cancel tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Stop bridge
        if self.bridge:
            self.bridge.stop()
        
        logger.info(f"Engine node stopped: {self.engine_id}")
    
    # =========================================================================
    # MESSAGE HANDLERS
    # =========================================================================
    
    def _handle_heartbeat(self, msg: BridgeMessage) -> None:
        """Handle heartbeat from another node"""
        payload = msg.payload
        node_id = payload.get('engine_id')
        if not node_id or node_id == self.engine_id:
            return
        
        with self._node_lock:
            if node_id not in self._connected_nodes:
                self._connected_nodes[node_id] = EngineMetrics(engine_id=node_id)
            
            node = self._connected_nodes[node_id]
            node.last_heartbeat = time.time()
            node.health_score = payload.get('health_score', 100.0)
            node.processing_load = payload.get('processing_load', 0.0)
            node.role = EngineRole(payload.get('role', 'standby'))
    
    def _handle_command(self, msg: BridgeMessage) -> None:
        """Handle command from primary engine"""
        payload = msg.payload
        cmd = payload.get('cmd')
        
        if cmd == 'set_role':
            new_role = EngineRole(payload.get('role', 'standby'))
            self._set_role(new_role)
        
        elif cmd == 'reduce_quality':
            level = payload.get('level', 50)
            self.config.quality_level = level
            logger.info(f"Quality reduced to {level}%")
        
        elif cmd == 'process_work':
            work_data = payload.get('work')
            if work_data:
                work = WorkUnit(**work_data)
                asyncio.create_task(self._process_work(work))
    
    def _handle_metrics(self, msg: BridgeMessage) -> None:
        """Handle metrics from another node"""
        payload = msg.payload
        node_id = payload.get('engine_id')
        if not node_id or node_id == self.engine_id:
            return
        
        with self._node_lock:
            if node_id in self._connected_nodes:
                node = self._connected_nodes[node_id]
                node.cpu_percent = payload.get('cpu_percent', 0.0)
                node.memory_percent = payload.get('memory_percent', 0.0)
                node.fps = payload.get('fps', 60.0)
                node.processing_load = payload.get('processing_load', 0.0)
    
    # =========================================================================
    # METRICS & HEALTH
    # =========================================================================
    
    async def _metrics_loop(self) -> None:
        """Collect and broadcast metrics"""
        while self._running:
            try:
                # Collect system metrics
                with self._metrics_lock:
                    self.metrics.timestamp = time.time()
                    self.metrics.cpu_percent = psutil.cpu_percent(interval=None)
                    self.metrics.memory_percent = psutil.virtual_memory().percent
                    
                    # Get IRM health
                    health = self.irm.get_health()
                    self.metrics.fps = health.fps
                    self.metrics.health_score = health.score
                    self.metrics.batch_size = self.irm.get_batch_size()
                    
                    # Calculate processing load
                    self.metrics.processing_load = self.metrics.calculate_load()
                    self.metrics.role = self.role
                    self.metrics.last_heartbeat = time.time()
                
                # Broadcast heartbeat
                if self.bridge:
                    self.bridge.send_heartbeat()
                
                await asyncio.sleep(self.config.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metrics loop error: {e}")
    
    async def _health_check_loop(self) -> None:
        """Monitor health and trigger state changes"""
        while self._running:
            try:
                # Feed IRM
                self.irm.tick(self.config.health_check_interval)
                
                # Check for dead nodes (primary only)
                if self.mode == EngineMode.TWIN:
                    await self._check_node_health()
                
                await asyncio.sleep(self.config.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
    
    async def _check_node_health(self) -> None:
        """Check health of connected nodes"""
        now = time.time()
        timeout = self.config.heartbeat_interval * 3
        
        with self._node_lock:
            dead_nodes = []
            for node_id, node in self._connected_nodes.items():
                if now - node.last_heartbeat > timeout:
                    dead_nodes.append(node_id)
                    logger.warning(f"Node {node_id} appears dead (no heartbeat)")
            
            for node_id in dead_nodes:
                del self._connected_nodes[node_id]
    
    # =========================================================================
    # LOAD BALANCING (PRIMARY ONLY)
    # =========================================================================
    
    async def _load_balancer_loop(self) -> None:
        """Monitor load and adjust system state (primary only)"""
        while self._running:
            try:
                load = self.metrics.processing_load
                
                # Determine required state
                new_state = self._calculate_required_state(load)
                
                if new_state != self.state:
                    await self._transition_to_state(new_state, load)
                
                await asyncio.sleep(self.config.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Load balancer error: {e}")
    
    def _calculate_required_state(self, load: float) -> SystemState:
        """Determine required system state based on load"""
        if self.state == SystemState.RECOVERY:
            # More aggressive threshold to leave recovery
            if load < 65.0:
                return SystemState.NORMAL
            return SystemState.RECOVERY
        
        if load >= self.config.emergency_threshold:
            return SystemState.EMERGENCY
        elif load >= 90.0:
            return SystemState.CRITICAL
        elif load >= self.config.assist_threshold_50:
            return SystemState.ELEVATED
        elif load < 65.0 and self.state != SystemState.NORMAL:
            return SystemState.RECOVERY
        
        return self.state if self.state == SystemState.NORMAL else SystemState.NORMAL
    
    async def _transition_to_state(self, new_state: SystemState, load: float) -> None:
        """Transition to new system state"""
        old_state = self.state
        self.state = new_state
        
        logger.info(f"System state: {old_state.value} -> {new_state.value} (load: {load:.1f}%)")
        
        # Execute transition actions
        if new_state == SystemState.ELEVATED:
            await self._engage_assistance(["camera_3"], EngineRole.BACKUP_50)
        
        elif new_state == SystemState.CRITICAL:
            await self._engage_assistance(["camera_3"], EngineRole.BACKUP_100)
            await self._engage_assistance(["camera_2"], EngineRole.BACKUP_50)
        
        elif new_state == SystemState.EMERGENCY:
            await self._engage_assistance(
                ["camera_1", "camera_2", "camera_3"],
                EngineRole.BACKUP_100
            )
            # Reduce quality to free resources
            await self._reduce_all_quality(50)
        
        elif new_state == SystemState.NORMAL:
            await self._disengage_all_assistance()
            await self._restore_quality()
        
        elif new_state == SystemState.RECOVERY:
            # Gradual return to normal
            await self._disengage_assistance(["camera_1"])
        
        # Fire callbacks
        for cb in self._on_state_change:
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")
    
    async def _engage_assistance(self, node_ids: List[str], role: EngineRole) -> None:
        """Request assistance from camera nodes"""
        for node_id in node_ids:
            if self.bridge:
                self.bridge.send_command('set_role', {'target': node_id, 'role': role.value})
            logger.info(f"Engaging {node_id} as {role.value}")
    
    async def _disengage_assistance(self, node_ids: List[str]) -> None:
        """Release camera nodes from assistance"""
        for node_id in node_ids:
            if self.bridge:
                self.bridge.send_command('set_role', {'target': node_id, 'role': 'standby'})
            logger.info(f"Disengaging {node_id}")
    
    async def _disengage_all_assistance(self) -> None:
        """Release all camera nodes"""
        with self._node_lock:
            node_ids = list(self._connected_nodes.keys())
        await self._disengage_assistance(node_ids)
    
    async def _reduce_all_quality(self, level: int) -> None:
        """Reduce quality on all nodes"""
        self.config.quality_level = level
        if self.bridge:
            self.bridge.send_command('reduce_quality', {'level': level})
    
    async def _restore_quality(self) -> None:
        """Restore full quality"""
        self.config.quality_level = 100
        if self.bridge:
            self.bridge.send_command('reduce_quality', {'level': 100})
    
    # =========================================================================
    # WORK DISTRIBUTION
    # =========================================================================
    
    async def _work_processor_loop(self) -> None:
        """Process work units from queue"""
        while self._running:
            try:
                # Get work with timeout
                try:
                    work = await asyncio.wait_for(
                        self._work_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process work
                await self._process_work(work)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Work processor error: {e}")
    
    async def _process_work(self, work: WorkUnit) -> None:
        """Process a single work unit"""
        start_time = time.time()
        
        try:
            if work.work_type == "voxel_render":
                result = await self._do_voxel_render(work)
            elif work.work_type == "mesh_generate":
                result = await self._do_mesh_generate(work)
            elif work.work_type == "audio_process":
                result = await self._do_audio_process(work)
            elif work.work_type == "video_encode":
                result = await self._do_video_encode(work)
            else:
                raise ValueError(f"Unknown work type: {work.work_type}")
            
            work.completed = True
            work.result = result
            
            # Record latency
            latency = (time.time() - start_time) * 1000
            self.irm.record_latency(latency)
            
        except Exception as e:
            work.error = str(e)
            logger.error(f"Work processing error: {e}")
        
        # Fire callbacks
        for cb in self._on_work_complete:
            try:
                cb(work)
            except Exception as e:
                logger.error(f"Work complete callback error: {e}")
    
    async def _do_voxel_render(self, work: WorkUnit) -> bytes:
        """Render voxels (placeholder for actual implementation)"""
        # This would call into the voxel world mesh generation
        await asyncio.sleep(0.001)  # Simulate work
        return b"rendered"
    
    async def _do_mesh_generate(self, work: WorkUnit) -> bytes:
        """Generate mesh (placeholder)"""
        await asyncio.sleep(0.002)
        return b"mesh"
    
    async def _do_audio_process(self, work: WorkUnit) -> bytes:
        """Process audio - NEVER SACRIFICED"""
        # Audio always gets highest priority
        await asyncio.sleep(0.001)
        return b"audio"
    
    async def _do_video_encode(self, work: WorkUnit) -> bytes:
        """Encode video"""
        await asyncio.sleep(0.005)
        return b"video"
    
    def submit_work(self, work: WorkUnit) -> None:
        """Submit work to be processed"""
        work.source_engine = self.engine_id
        self._work_queue.put_nowait(work)
    
    def distribute_work(self, work: WorkUnit, target_node: str) -> None:
        """Distribute work to another node (primary only)"""
        work.target_engine = target_node
        if self.bridge:
            self.bridge.send_command('process_work', {
                'target': target_node,
                'work': {
                    'work_id': work.work_id,
                    'work_type': work.work_type,
                    'priority': work.priority,
                    'data': work.data.hex() if work.data else "",
                    'metadata': work.metadata,
                    'deadline_ms': work.deadline_ms
                }
            })
    
    # =========================================================================
    # ROLE MANAGEMENT
    # =========================================================================
    
    def _set_role(self, role: EngineRole) -> None:
        """Set this node's role"""
        old_role = self.role
        self.role = role
        self.metrics.role = role
        
        logger.info(f"Role changed: {old_role.value} -> {role.value}")
        
        # Adjust processing based on role
        if role == EngineRole.BACKUP_100:
            # Full backup mode - dedicate all resources
            self.config.quality_level = 100
        elif role == EngineRole.BACKUP_50:
            # Partial backup - balance local and remote
            self.config.quality_level = 75
        elif role == EngineRole.STANDBY:
            # Standby - minimal processing
            self.config.quality_level = 100
    
    async def _announce_to_primary(self) -> None:
        """Announce this node to the primary engine"""
        if self.bridge:
            self.bridge.send_command('register_node', {
                'engine_id': self.engine_id,
                'mode': self.mode.value,
                'capabilities': ['voxel_render', 'mesh_generate', 'video_encode']
            })
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def get_metrics(self) -> EngineMetrics:
        """Get current metrics"""
        with self._metrics_lock:
            return EngineMetrics(
                engine_id=self.metrics.engine_id,
                timestamp=self.metrics.timestamp,
                cpu_percent=self.metrics.cpu_percent,
                memory_percent=self.metrics.memory_percent,
                processing_load=self.metrics.processing_load,
                batch_size=self.metrics.batch_size,
                fps=self.metrics.fps,
                health_score=self.metrics.health_score,
                role=self.metrics.role,
                audio_quality=self.metrics.audio_quality
            )
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get complete system status"""
        with self._node_lock:
            nodes = {nid: n.to_dict() for nid, n in self._connected_nodes.items()}
        
        return {
            'engine_id': self.engine_id,
            'mode': self.mode.value,
            'role': self.role.value,
            'state': self.state.value,
            'metrics': self.metrics.to_dict(),
            'connected_nodes': nodes,
            'work_queue_size': self._work_queue.qsize(),
            'quality_level': self.config.quality_level
        }
    
    def on_state_change(self, callback: Callable[[SystemState, SystemState], None]) -> None:
        """Register callback for state changes"""
        self._on_state_change.append(callback)
    
    def on_work_complete(self, callback: Callable[[WorkUnit], None]) -> None:
        """Register callback for work completion"""
        self._on_work_complete.append(callback)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_twin_engine(engine_id: str = "twin_engine") -> DistributedEngineNode:
    """Create primary twin engine"""
    config = EngineConfig(
        engine_id=engine_id,
        mode=EngineMode.TWIN,
        primary_port=9000,
        max_batch_size=20000,
        default_batch_size=5000
    )
    return DistributedEngineNode(config)


def create_camera_engine(
    camera_id: str,
    listen_port: int,
    primary_host: str = "127.0.0.1",
    primary_port: int = 9000
) -> DistributedEngineNode:
    """Create camera engine node"""
    config = EngineConfig(
        engine_id=camera_id,
        mode=EngineMode.CAMERA,
        primary_host=primary_host,
        primary_port=primary_port,
        listen_port=listen_port,
        max_batch_size=5000,
        default_batch_size=1000
    )
    return DistributedEngineNode(config)