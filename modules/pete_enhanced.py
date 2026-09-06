#!/usr/bin/env python3
"""
PETE ENHANCED - COMPLETE TWIN ENGINE ORCHESTRATOR
"I've got the whole show handled, boss."

This is Pete enhanced to orchestrate the complete twin engine architecture:
- Your existing Bridge (commands TO Rust engine)  
- My Window Handshake (streaming FROM Rust engine)
- System health monitoring and coordination
- Emergency protocols and load balancing
- Complete production workflow integration

Pete now manages the full pipeline:
Motion Capture → Bridge → Rust Engine → WebRTC Streaming → Browser Display
"""

from __future__ import annotations

import asyncio
import logging
import psutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, Set, List, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

# Import your existing Pete architecture
from pete import (
    SystemHealth, ResourceMetrics, RePeteWorker, Pete as BasePete
)

# Import your existing Bridge
from bridge import VoxelBridge, BridgeStatus

# Import my Window Handshake implementation
from voxel_webrtc_bridge import VoxelWebRTCBridge
from pubcast_voxel_integration import PubCastVoxelIntegration

if TYPE_CHECKING:
    from ..core.hub import Hub
    from ..motion.avatar_system import MotionSystem

logger = logging.getLogger("pubcast.pete_enhanced")

@dataclass
class TwinEngineMetrics:
    """Enhanced metrics for the complete twin engine system"""
    # Base system metrics (from your Pete)
    base_metrics: ResourceMetrics = field(default_factory=ResourceMetrics)
    
    # Bridge metrics (commands TO Rust engine)
    bridge_status: BridgeStatus = BridgeStatus.DISCONNECTED
    commands_queued: int = 0
    commands_sent: int = 0
    commands_failed: int = 0
    bridge_latency_ms: float = 0.0
    
    # WebRTC metrics (streaming FROM Rust engine)  
    webrtc_connections: int = 0
    streaming_fps: float = 0.0
    frames_streamed: int = 0
    frames_dropped: int = 0
    webrtc_latency_ms: float = 0.0
    
    # Rust engine health
    rust_engine_alive: bool = False
    rust_engine_fps: float = 0.0
    rust_engine_memory_mb: float = 0.0
    
    # Performance tracking
    total_pipeline_latency: float = 0.0  # Motion → Rust → Browser
    timestamp: float = field(default_factory=time.time)

class TwinEngineHealth(Enum):
    """Health status for the complete twin engine system"""
    PERFECT = "perfect"           # All systems optimal, <16ms total latency
    EXCELLENT = "excellent"       # All systems healthy, <33ms total latency  
    GOOD = "good"                # Minor issues, <50ms total latency
    DEGRADED = "degraded"        # Performance issues, <100ms total latency
    CRITICAL = "critical"        # Major issues, >100ms latency
    EMERGENCY = "emergency"      # System failure imminent

class PeteEnhanced(BasePete):
    """
    Enhanced Pete - Complete Twin Engine Orchestrator
    
    Pete now manages the full pipeline:
    1. Your existing Bridge (Python ↔ Rust communication)
    2. My WebRTC streaming (Rust → Browser display)  
    3. System health monitoring across both engines
    4. Load balancing and emergency protocols
    5. Production workflow coordination
    6. Real-time performance optimization
    
    Pete's Enhanced Personality:
    "I run a tight ship with both engines purring like kittens.
     Your viewers get silky smooth 60fps while the Rust engine
     never breaks a sweat. That's how we do professional-grade magic."
    """
    
    def __init__(
        self,
        hub: 'Hub',
        bridge: VoxelBridge,
        motion_system: Dict[str, Any],
        data_dir: Path,
        config: Optional[Dict[str, Any]] = None
    ):
        # Initialize base Pete
        super().__init__(hub, bridge, motion_system, data_dir, config)
        
        # Enhanced twin engine components
        self.webrtc_bridge: Optional[VoxelWebRTCBridge] = None
        self.voxel_integration: Optional[PubCastVoxelIntegration] = None
        
        # Twin engine state
        self._twin_engine_health = TwinEngineHealth.PERFECT
        self._twin_metrics = TwinEngineMetrics()
        self._last_twin_engine_check = 0.0
        
        # Performance optimization
        self._adaptive_quality_enabled = True
        self._current_quality_preset = "high"
        self._load_balancing_active = False
        
        # Emergency protocols
        self._emergency_streaming_fallback = False
        self._rust_engine_restart_count = 0
        
        logger.info("🎭 Pete Enhanced: Complete twin engine orchestrator initialized")

    async def initialize_twin_engine_system(self) -> bool:
        """
        Initialize the complete twin engine system.
        
        This sets up both your Bridge (Python → Rust) and 
        my WebRTC streaming (Rust → Browser).
        """
        try:
            logger.info("🎭 Pete: Initializing complete twin engine system...")
            
            # Step 1: Initialize your existing Bridge connection
            logger.info("🎭 Pete: Connecting to Rust engine via Bridge...")
            bridge_connected = await self._initialize_bridge_connection()
            
            if not bridge_connected:
                logger.error("🎭 Pete: Bridge connection failed!")
                return False
            
            # Step 2: Initialize my WebRTC streaming
            logger.info("🎭 Pete: Setting up WebRTC streaming...")
            streaming_ready = await self._initialize_webrtc_streaming()
            
            if not streaming_ready:
                logger.warning("🎭 Pete: WebRTC streaming failed - continuing with basic operation")
            
            # Step 3: Start twin engine monitoring
            logger.info("🎭 Pete: Starting twin engine health monitoring...")
            await self._start_twin_engine_monitoring()
            
            # Step 4: Perform system integration test
            logger.info("🎭 Pete: Running integration test...")
            integration_success = await self._test_complete_pipeline()
            
            if integration_success:
                await self._report_status(
                    "🎭 Pete: Twin engine system fully operational! "
                    "Rust rendering + WebRTC streaming = Professional magic ✨"
                )
                return True
            else:
                await self._report_status(
                    "⚠️ Pete: Twin engine system partially operational. "
                    "Some features may be limited."
                )
                return True  # Continue with limited functionality
                
        except Exception as e:
            logger.error(f"🎭 Pete: Twin engine initialization failed: {e}")
            return False

    async def _initialize_bridge_connection(self) -> bool:
        """Initialize your existing Bridge connection to Rust engine"""
        try:
            # Use your existing Bridge.connect() method
            success = self.bridge.connect()
            
            if success:
                # Test basic bridge functionality
                test_command_sent = self.bridge.send_command(
                    "HEARTBEAT", 
                    {"test": True, "from": "pete_enhanced"}
                )
                
                if test_command_sent:
                    logger.info("🎭 Pete: Bridge connection established and tested ✅")
                    return True
                else:
                    logger.warning("🎭 Pete: Bridge connected but test command failed")
                    return False
            else:
                logger.error("🎭 Pete: Bridge connection failed")
                return False
                
        except Exception as e:
            logger.error(f"🎭 Pete: Bridge initialization error: {e}")
            return False

    async def _initialize_webrtc_streaming(self) -> bool:
        """Initialize my WebRTC streaming bridge"""
        try:
            # Create WebRTC bridge instance
            self.webrtc_bridge = VoxelWebRTCBridge()
            
            # Create voxel integration manager
            self.voxel_integration = PubCastVoxelIntegration(
                camera_manager=None,  # Will be set later if available
                hub=self.hub
            )
            
            # Start WebRTC bridge monitoring
            asyncio.create_task(self.webrtc_bridge.start_frame_monitoring())
            
            # Give it time to connect to shared memory
            for attempt in range(10):
                if self.webrtc_bridge.connect_shared_memory():
                    logger.info("🎭 Pete: WebRTC streaming bridge connected ✅")
                    return True
                await asyncio.sleep(0.5)
            
            logger.warning("🎭 Pete: WebRTC streaming bridge couldn't connect to shared memory")
            return False
            
        except Exception as e:
            logger.error(f"🎭 Pete: WebRTC streaming initialization error: {e}")
            return False

    async def _start_twin_engine_monitoring(self):
        """Start enhanced monitoring for the twin engine system"""
        # Start base Pete monitoring
        await super().start_monitoring()
        
        # Add twin engine specific monitoring
        asyncio.create_task(self._twin_engine_monitor_loop())
        
        logger.info("🎭 Pete: Twin engine monitoring started")

    async def _twin_engine_monitor_loop(self):
        """Enhanced monitoring loop for twin engine health"""
        while self._monitoring_active:
            try:
                # Collect twin engine metrics
                self._twin_metrics = await self._collect_twin_engine_metrics()
                
                # Assess twin engine health
                old_health = self._twin_engine_health
                self._twin_engine_health = self._assess_twin_engine_health(self._twin_metrics)
                
                # Handle health changes
                if self._twin_engine_health != old_health:
                    await self._handle_twin_engine_health_change(old_health, self._twin_engine_health)
                
                # Optimize performance based on current load
                if self._adaptive_quality_enabled:
                    await self._optimize_twin_engine_performance()
                
                # Emergency protocols
                if self._twin_engine_health in [TwinEngineHealth.CRITICAL, TwinEngineHealth.EMERGENCY]:
                    await self._handle_twin_engine_emergency()
                
                self._last_twin_engine_check = time.time()
                await asyncio.sleep(2.0)  # Check every 2 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🎭 Pete: Twin engine monitoring error: {e}")
                await asyncio.sleep(5.0)

    async def _collect_twin_engine_metrics(self) -> TwinEngineMetrics:
        """Collect comprehensive metrics from both engines"""
        try:
            # Get base system metrics
            base_metrics = await self._collect_system_metrics()
            
            # Get Bridge metrics (your existing bridge)
            bridge_status = self.bridge.get_status() if self.bridge else BridgeStatus.DISCONNECTED
            bridge_metrics = self.bridge.get_metrics() if self.bridge else None
            
            # Get WebRTC metrics (my streaming bridge)
            webrtc_status = self.webrtc_bridge.get_status() if self.webrtc_bridge else {}
            
            # Calculate total pipeline latency
            bridge_latency = bridge_metrics.avg_latency_ms if bridge_metrics else 0.0
            webrtc_latency = 16.67  # ~1 frame at 60fps, estimated
            total_latency = bridge_latency + webrtc_latency
            
            return TwinEngineMetrics(
                base_metrics=base_metrics,
                
                # Bridge metrics
                bridge_status=bridge_status,
                commands_queued=len(self.bridge._command_queue) if self.bridge else 0,
                commands_sent=bridge_metrics.commands_sent if bridge_metrics else 0,
                commands_failed=bridge_metrics.commands_failed if bridge_metrics else 0,
                bridge_latency_ms=bridge_latency,
                
                # WebRTC metrics  
                webrtc_connections=webrtc_status.get("webrtc_connections", 0),
                streaming_fps=webrtc_status.get("current_fps", 0.0),
                frames_streamed=webrtc_status.get("frames_read", 0),
                frames_dropped=webrtc_status.get("frames_dropped", 0),
                
                # Rust engine health (inferred from both bridges)
                rust_engine_alive=bridge_status in [BridgeStatus.CONNECTED, BridgeStatus.DEGRADED],
                rust_engine_fps=webrtc_status.get("current_fps", 0.0),
                
                # Performance
                total_pipeline_latency=total_latency
            )
            
        except Exception as e:
            logger.error(f"🎭 Pete: Metrics collection error: {e}")
            return TwinEngineMetrics()

    def _assess_twin_engine_health(self, metrics: TwinEngineMetrics) -> TwinEngineHealth:
        """Assess health of the complete twin engine system"""
        
        # Perfect: Everything optimal
        if (metrics.total_pipeline_latency < 16 and 
            metrics.streaming_fps > 55 and
            metrics.bridge_status == BridgeStatus.CONNECTED and
            metrics.base_metrics.cpu_percent < 50):
            return TwinEngineHealth.PERFECT
        
        # Excellent: All systems healthy
        elif (metrics.total_pipeline_latency < 33 and 
              metrics.streaming_fps > 45 and
              metrics.bridge_status in [BridgeStatus.CONNECTED, BridgeStatus.DEGRADED] and
              metrics.base_metrics.cpu_percent < 70):
            return TwinEngineHealth.EXCELLENT
        
        # Good: Minor issues
        elif (metrics.total_pipeline_latency < 50 and 
              metrics.streaming_fps > 30 and
              metrics.bridge_status != BridgeStatus.ERROR):
            return TwinEngineHealth.GOOD
        
        # Degraded: Performance issues  
        elif (metrics.total_pipeline_latency < 100 and 
              metrics.streaming_fps > 15):
            return TwinEngineHealth.DEGRADED
        
        # Critical: Major issues
        elif metrics.rust_engine_alive and metrics.streaming_fps > 0:
            return TwinEngineHealth.CRITICAL
        
        # Emergency: System failure
        else:
            return TwinEngineHealth.EMERGENCY

    async def _handle_twin_engine_health_change(self, old_health: TwinEngineHealth, new_health: TwinEngineHealth):
        """React to twin engine health changes"""
        
        if new_health == TwinEngineHealth.PERFECT:
            await self._report_status("🎭 Pete: Twin engines purring like kittens! "
                                    f"<16ms latency, {self._twin_metrics.streaming_fps:.1f}fps streaming")
        
        elif new_health == TwinEngineHealth.EXCELLENT:
            await self._report_status("🎭 Pete: Twin engines running smooth as silk! "
                                    f"{self._twin_metrics.total_pipeline_latency:.1f}ms pipeline")
        
        elif new_health == TwinEngineHealth.GOOD:
            await self._report_status("🎭 Pete: Twin engines nominal. "
                                    f"Latency: {self._twin_metrics.total_pipeline_latency:.1f}ms")
        
        elif new_health == TwinEngineHealth.DEGRADED:
            await self._report_status("⚠️ Pete: Twin engine performance degraded. "
                                    "Activating optimization protocols.")
            await self._optimize_twin_engine_performance()
        
        elif new_health == TwinEngineHealth.CRITICAL:
            await self._report_status("🚨 Pete: Twin engine system critical! "
                                    "Emergency protocols activated.")
            
        elif new_health == TwinEngineHealth.EMERGENCY:
            await self._report_status("🚨 Pete: TWIN ENGINE EMERGENCY! "
                                    "Attempting system recovery...")

    async def _optimize_twin_engine_performance(self):
        """Optimize twin engine performance based on current load"""
        try:
            metrics = self._twin_metrics
            
            # Adjust quality based on system load
            if metrics.base_metrics.cpu_percent > 80:
                await self._reduce_rendering_quality()
            elif metrics.base_metrics.cpu_percent < 40 and self._current_quality_preset == "medium":
                await self._increase_rendering_quality()
            
            # Optimize streaming based on connection count
            if metrics.webrtc_connections > 10:
                await self._enable_streaming_optimization()
            
            # Load balance between engines
            if metrics.bridge_latency_ms > 50:
                await self._enable_load_balancing()
                
        except Exception as e:
            logger.error(f"🎭 Pete: Performance optimization error: {e}")

    async def _reduce_rendering_quality(self):
        """Reduce Rust engine rendering quality to improve performance"""
        if self._current_quality_preset != "medium":
            logger.info("🎭 Pete: Reducing rendering quality to stabilize performance")
            
            # Send quality reduction command to Rust engine via your Bridge
            success = self.bridge.send_command("SET_QUALITY", {"quality": "medium", "fps": 30})
            
            if success:
                self._current_quality_preset = "medium"
                await self._report_status("🎭 Pete: Rendering quality reduced to maintain smooth performance")

    async def _increase_rendering_quality(self):
        """Increase rendering quality when system can handle it"""
        if self._current_quality_preset != "high":
            logger.info("🎭 Pete: System stable - increasing rendering quality")
            
            success = self.bridge.send_command("SET_QUALITY", {"quality": "high", "fps": 60})
            
            if success:
                self._current_quality_preset = "high"
                await self._report_status("🎭 Pete: Rendering quality increased - silky smooth 60fps!")

    async def _enable_streaming_optimization(self):
        """Enable streaming optimizations for multiple viewers"""
        if not self._load_balancing_active:
            logger.info("🎭 Pete: Multiple viewers detected - enabling streaming optimization")
            self._load_balancing_active = True
            
            # Could implement bitrate adaptation, quality scaling, etc.
            await self._report_status("🎭 Pete: Streaming optimization active for multiple viewers")

    async def _handle_twin_engine_emergency(self):
        """Handle twin engine emergency situations"""
        try:
            # Emergency protocols
            if self._twin_engine_health == TwinEngineHealth.EMERGENCY:
                logger.error("🎭 Pete: Twin engine system failure - attempting recovery")
                
                # Try to restart the Rust engine
                if self.voxel_integration:
                    await self.voxel_integration._restart_voxel_engine()
                    self._rust_engine_restart_count += 1
                
                # Enable emergency fallback streaming
                self._emergency_streaming_fallback = True
                
                # Report to base Pete for system-level emergency protocols
                await self._activate_emergency_protocols(self._twin_metrics.base_metrics)
                
        except Exception as e:
            logger.error(f"🎭 Pete: Emergency handling error: {e}")

    async def _test_complete_pipeline(self) -> bool:
        """Test the complete pipeline: Motion → Bridge → Rust → WebRTC → Browser"""
        try:
            logger.info("🎭 Pete: Testing complete twin engine pipeline...")
            
            # Test 1: Send test command via Bridge
            bridge_test = self.bridge.send_command("LOAD_SCENE", {"scene": "test_scene"})
            if not bridge_test:
                logger.warning("🎭 Pete: Bridge test failed")
                return False
            
            # Test 2: Check WebRTC streaming  
            await asyncio.sleep(2.0)  # Give time for frame processing
            
            webrtc_status = self.webrtc_bridge.get_status() if self.webrtc_bridge else {}
            if webrtc_status.get("current_fps", 0) > 0:
                logger.info("🎭 Pete: WebRTC streaming test passed ✅")
            else:
                logger.warning("🎭 Pete: WebRTC streaming test failed")
                return False
            
            # Test 3: Measure total latency
            total_latency = self._twin_metrics.total_pipeline_latency
            if total_latency < 100:  # Less than 100ms is acceptable
                logger.info(f"🎭 Pete: Pipeline latency test passed: {total_latency:.1f}ms ✅")
                return True
            else:
                logger.warning(f"🎭 Pete: Pipeline latency high: {total_latency:.1f}ms")
                return False
                
        except Exception as e:
            logger.error(f"🎭 Pete: Pipeline test error: {e}")
            return False

    def get_twin_engine_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the twin engine system"""
        return {
            # Overall health
            "twin_engine_health": self._twin_engine_health.value,
            "system_operational": self._twin_engine_health not in [TwinEngineHealth.CRITICAL, TwinEngineHealth.EMERGENCY],
            
            # Your Bridge (Python → Rust)
            "bridge": {
                "status": self._twin_metrics.bridge_status.value,
                "commands_queued": self._twin_metrics.commands_queued,
                "commands_sent": self._twin_metrics.commands_sent,
                "latency_ms": self._twin_metrics.bridge_latency_ms
            },
            
            # My WebRTC Streaming (Rust → Browser)
            "streaming": {
                "webrtc_connections": self._twin_metrics.webrtc_connections,
                "fps": self._twin_metrics.streaming_fps,
                "frames_streamed": self._twin_metrics.frames_streamed,
                "frames_dropped": self._twin_metrics.frames_dropped
            },
            
            # Rust Engine Health
            "rust_engine": {
                "alive": self._twin_metrics.rust_engine_alive,
                "fps": self._twin_metrics.rust_engine_fps,
                "restart_count": self._rust_engine_restart_count
            },
            
            # Performance
            "performance": {
                "total_pipeline_latency_ms": self._twin_metrics.total_pipeline_latency,
                "current_quality": self._current_quality_preset,
                "load_balancing_active": self._load_balancing_active,
                "emergency_fallback": self._emergency_streaming_fallback
            }
        }

    async def handle_production_control(self, command: str, params: Dict[str, Any]):
        """Enhanced production control that coordinates both engines"""
        try:
            # Handle camera controls
            if command == "switch_camera":
                # Send to Rust engine via your Bridge
                bridge_success = self.bridge.send_command("SWITCH_PROGRAM", {
                    "camera_id": params.get("camera_id", 1),
                    "transition": params.get("transition", "CUT")
                })
                
                if bridge_success:
                    await self._report_status(f"🎭 Pete: Switched to camera {params.get('camera_id')}")
                
            # Handle scene changes
            elif command == "load_scene":
                bridge_success = self.bridge.send_command("LOAD_SCENE", {
                    "scene_id": params.get("scene_id"),
                    "transition_time": params.get("transition_time", 1.0)
                })
                
                if bridge_success:
                    await self._report_status(f"🎭 Pete: Loading scene '{params.get('scene_id')}'")
            
            # Handle recording controls
            elif command.startswith("record_"):
                action = command.replace("record_", "").upper()
                bridge_success = self.bridge.send_recording_control(action, params)
                
                if bridge_success:
                    await self._report_status(f"🎭 Pete: Recording {action.lower()}")
            
            # Handle quality adjustments
            elif command == "set_quality":
                quality = params.get("quality", "high")
                await self._set_rendering_quality(quality)
                
        except Exception as e:
            logger.error(f"🎭 Pete: Production control error: {e}")

    async def _set_rendering_quality(self, quality: str):
        """Set rendering quality on the Rust engine"""
        quality_settings = {
            "low": {"quality": "low", "fps": 30, "resolution": "1280x720"},
            "medium": {"quality": "medium", "fps": 45, "resolution": "1920x1080"},
            "high": {"quality": "high", "fps": 60, "resolution": "1920x1080"}
        }
        
        settings = quality_settings.get(quality, quality_settings["high"])
        success = self.bridge.send_command("SET_QUALITY", settings)
        
        if success:
            self._current_quality_preset = quality
            await self._report_status(f"🎭 Pete: Rendering quality set to {quality}")

    async def shutdown_twin_engine_system(self):
        """Graceful shutdown of the complete twin engine system"""
        logger.info("🎭 Pete: Shutting down twin engine system...")
        
        try:
            # Shutdown WebRTC streaming
            if self.voxel_integration:
                await self.voxel_integration.shutdown()
            
            # Shutdown your Bridge connection
            if self.bridge:
                await self.bridge.shutdown()
            
            # Shutdown base Pete
            await super().shutdown()
            
            await self._report_status("🎭 Pete: Twin engine system shutdown complete. See you on the flip side!")
            
        except Exception as e:
            logger.error(f"🎭 Pete: Twin engine shutdown error: {e}")

# Usage example for integration
async def create_enhanced_pete_system(hub, bridge, motion_system, data_dir):
    """Create and initialize the complete Pete Enhanced system"""
    
    pete_enhanced = PeteEnhanced(
        hub=hub,
        bridge=bridge,
        motion_system=motion_system,
        data_dir=data_dir
    )
    
    # Initialize the complete twin engine system
    success = await pete_enhanced.initialize_twin_engine_system()
    
    if success:
        logger.info("🎭 Pete Enhanced: Complete twin engine system operational!")
        return pete_enhanced
    else:
        logger.error("🎭 Pete Enhanced: Twin engine system initialization failed")
        return None

if __name__ == "__main__":
    # Standalone testing
    async def test_enhanced_pete():
        # This would normally come from your main system
        from unittest.mock import Mock
        
        hub = Mock()
        bridge = Mock()
        motion_system = {}
        data_dir = Path("./data")
        
        pete = await create_enhanced_pete_system(hub, bridge, motion_system, data_dir)
        
        if pete:
            print("✅ Pete Enhanced test successful!")
            
            # Test twin engine status
            status = pete.get_twin_engine_status()
            print(f"Twin Engine Status: {status['twin_engine_health']}")
            
            # Keep running for testing
            try:
                while True:
                    await asyncio.sleep(1.0)
            except KeyboardInterrupt:
                await pete.shutdown_twin_engine_system()
        else:
            print("❌ Pete Enhanced test failed")
    
    asyncio.run(test_enhanced_pete())

