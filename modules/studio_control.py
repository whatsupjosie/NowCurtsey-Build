#!/usr/bin/env python3
# PubCast AI — studio_control.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
STUDIO CONTROL ROOM - PYTHON BACKEND
=====================================
Integrates the "Iron Core" production control logic with PubCast AI.

This module provides:
- Audio matrix monitoring (5 channels)
- 5-second preflight countdown with hardware audit
- Emergency save protocols (Dead Man's Switch)
- WebSocket bridge to JavaScript control surface
- Integration with Pete's orchestration system

Architecture:
    JavaScript Control Surface → WebSocket → StudioControl → Pete → Voxel Engine
                                                ↓
                                          Audio System
                                          Emergency Save
                                          Hardware Audit
"""

from __future__ import annotations

import asyncio
import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime

if TYPE_CHECKING:
    from pete_enhanced import PeteEnhanced
    from pubcast.core.hub import Hub

logger = logging.getLogger("pubcast.studio_control")


class StudioState(Enum):
    """Studio operational states"""
    IDLE = "IDLE"           # No active session
    PREFLIGHT = "PREFLIGHT"  # 5-second countdown active
    LIVE = "LIVE"           # Recording/Broadcasting
    EMERGENCY = "EMERGENCY"  # Emergency save triggered
    OFFLINE = "OFFLINE"     # System unavailable


class AudioChannelStatus(Enum):
    """Audio channel health status"""
    OK = "OK"              # Normal operation
    WARNING = "WARNING"    # Signal issues detected
    CRITICAL = "CRITICAL"  # Major problems
    MUTED = "MUTED"       # Intentionally disabled
    GHOST = "GHOST"       # Unexpected active input


@dataclass
class AudioChannel:
    """Individual audio channel state"""
    channel_id: str
    name: str
    active: bool = True
    signal_db: float = -60.0
    status: AudioChannelStatus = AudioChannelStatus.OK
    device_id: Optional[str] = None
    last_peak_db: float = -60.0
    peak_timestamp: float = field(default_factory=time.time)
    
    def update_signal(self, db_level: float) -> None:
        """Update signal level and track peaks"""
        self.signal_db = db_level
        if db_level > self.last_peak_db:
            self.last_peak_db = db_level
            self.peak_timestamp = time.time()
        
        # Auto-update status based on signal
        if not self.active:
            self.status = AudioChannelStatus.MUTED
        elif db_level > -10:
            self.status = AudioChannelStatus.CRITICAL  # Clipping
        elif db_level < -80:
            self.status = AudioChannelStatus.WARNING  # No signal
        else:
            self.status = AudioChannelStatus.OK


@dataclass
class AudioMatrix:
    """Complete audio system state - The 5 Key Categories"""
    mic_inputs: AudioChannel = field(default_factory=lambda: AudioChannel(
        "mic_inputs", "Microphone Inputs"
    ))
    dialogue: AudioChannel = field(default_factory=lambda: AudioChannel(
        "dialogue", "Dialogue Track"
    ))
    studio_feed: AudioChannel = field(default_factory=lambda: AudioChannel(
        "studio_feed", "Studio Feed (SFX/Music)"
    ))
    system_audio: AudioChannel = field(default_factory=lambda: AudioChannel(
        "system_audio", "System Audio"
    ))
    room_noise: AudioChannel = field(default_factory=lambda: AudioChannel(
        "room_noise", "Room Noise", active=True, signal_db=-70.0
    ))
    
    def get_all_channels(self) -> List[AudioChannel]:
        """Get list of all audio channels"""
        return [
            self.mic_inputs,
            self.dialogue,
            self.studio_feed,
            self.system_audio,
            self.room_noise
        ]
    
    def get_channel(self, channel_id: str) -> Optional[AudioChannel]:
        """Get specific channel by ID"""
        for channel in self.get_all_channels():
            if channel.channel_id == channel_id:
                return channel
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            channel.channel_id: {
                "name": channel.name,
                "active": channel.active,
                "signal_db": channel.signal_db,
                "status": channel.status.value,
                "last_peak_db": channel.last_peak_db
            }
            for channel in self.get_all_channels()
        }


@dataclass
class PreflightCheck:
    """Individual preflight check result"""
    check_id: str
    name: str
    passed: bool = False
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class StudioControl:
    """
    Studio Control Room - The "Iron Core" Engine
    
    Handles:
    - Audio matrix monitoring
    - 5-second preflight countdown
    - Hardware audit (Gate Check, Ghost Mic detection)
    - Emergency save protocols
    - Integration with Pete's orchestration
    
    The philosophy is "Local-First Logic":
    Critical production control NEVER requires cloud AI.
    All core safety features work even if AI is offline.
    """
    
    def __init__(
        self,
        hub: 'Hub',
        pete: 'PeteEnhanced',
        data_dir: Path,
        config: Optional[Dict[str, Any]] = None
    ):
        self.hub = hub
        self.pete = pete
        self.data_dir = data_dir
        self.config = config or {}
        
        # Studio state
        self._state = StudioState.IDLE
        self._audio_matrix = AudioMatrix()
        self._preflight_checks: List[PreflightCheck] = []
        self._recording_start_time: Optional[float] = None
        self._last_emergency_save: float = 0.0
        
        # Hardware tracking
        self._detected_mic_count = 0
        self._required_mic_count = 1
        self._ghost_mics: List[str] = []
        
        # Emergency protocols
        self._emergency_save_dir = data_dir / "emergency_saves"
        self._emergency_save_dir.mkdir(exist_ok=True)
        self._dead_man_switch_interval = 60.0  # Auto-save every 60s during LIVE
        
        # WebSocket clients (for real-time updates to UI)
        self._ws_clients: List[Any] = []
        
        # Performance tracking
        self._last_audio_update = 0.0
        self._audio_update_interval = 0.1  # 10 Hz monitoring
        
        logger.info("🎛️ Studio Control Room initialized")
    
    @property
    def state(self) -> StudioState:
        """Get current studio state"""
        return self._state
    
    @property
    def audio_matrix(self) -> AudioMatrix:
        """Get current audio matrix state"""
        return self._audio_matrix
    
    async def run_preflight_sequence(self) -> bool:
        """
        Execute the 5-Second Countdown / Combat Check
        
        This is the production-critical gate check that runs
        before every recording session.
        
        Returns:
            True if all checks passed, False otherwise
        """
        logger.info("🎬 Starting 5-second preflight countdown...")
        self._state = StudioState.PREFLIGHT
        self._preflight_checks.clear()
        
        # Broadcast state change to UI
        await self._broadcast_state_update()
        
        # The 5-second countdown with AI voice cues
        for i in range(5, 0, -1):
            logger.info(f"⏱️ T-Minus {i}...")
            
            # Trigger AI voice cue through Pete
            await self._trigger_voice_cue(f"T minus {i}")
            
            # Run specific audits at designated seconds
            if i == 4:
                await self._check_the_gate()
            if i == 2:
                await self._check_ghost_mics()
            
            # Broadcast countdown to UI
            await self._broadcast_countdown(i)
            
            await asyncio.sleep(1.0)
        
        # Evaluate all checks
        all_passed = all(check.passed for check in self._preflight_checks)
        
        if all_passed:
            logger.info("✅ Preflight complete - ALL CHECKS PASSED")
            await self._start_recording()
            return True
        else:
            logger.warning("⚠️ Preflight complete - WARNINGS DETECTED")
            failed_checks = [c for c in self._preflight_checks if not c.passed]
            for check in failed_checks:
                logger.warning(f"  ❌ {check.name}: {check.message}")
            
            # Still start recording but with warnings
            await self._start_recording()
            return False
    
    async def _check_the_gate(self) -> "PreflightCheck":
        """
        Gate Check - Camera/Buffer Verification
        
        Compares physical hardware inputs to scene requirements.
        Detects phantom devices and configuration mismatches.
        """
        logger.info("🎥 Running Gate Check (Camera/Buffer verification)...")
        
        # TODO: Integrate with Pete's hardware monitoring
        # For now, simulate hardware detection
        self._detected_mic_count = 3  # Example: 3 USB/XLR inputs detected
        self._required_mic_count = 1  # Example: Script needs 1 mic
        
        if self._detected_mic_count > self._required_mic_count:
            excess = self._detected_mic_count - self._required_mic_count
            self._ghost_mics = [f"Input {i+2}" for i in range(excess)]
            
            check = PreflightCheck(
                "gate_check",
                "Gate Check",
                passed=False,
                message=f"Ghost devices detected: {', '.join(self._ghost_mics)}"
            )
            logger.warning(f"👻 Ghost Mics detected: {self._ghost_mics}")
        else:
            check = PreflightCheck(
                "gate_check",
                "Gate Check",
                passed=True,
                message=f"All {self._detected_mic_count} inputs matched scene requirements"
            )
        
        self._preflight_checks.append(check)
        await self._broadcast_check_result(check)
        return check
    
    async def _check_ghost_mics(self) -> "PreflightCheck":
        """
        Ghost Mic Detection - Audio Input Audit
        
        Scans for unexpected active audio inputs that could
        contaminate the recording.
        """
        logger.info("🎤 Running Ghost Mic detection...")
        
        # Scan all audio channels for unexpected signal
        ghost_channels = []
        for channel in self._audio_matrix.get_all_channels():
            if not channel.active and channel.signal_db > -70:
                ghost_channels.append(channel.name)
                channel.status = AudioChannelStatus.GHOST
        
        if ghost_channels:
            check = PreflightCheck(
                "ghost_mic_check",
                "Ghost Mic Detection",
                passed=False,
                message=f"Unexpected signal on: {', '.join(ghost_channels)}"
            )
            logger.warning(f"👻 Ghost signals: {ghost_channels}")
        else:
            check = PreflightCheck(
                "ghost_mic_check",
                "Ghost Mic Detection",
                passed=True,
                message="All audio inputs clean"
            )
        
        self._preflight_checks.append(check)
        await self._broadcast_check_result(check)
        return check
    
    async def _trigger_voice_cue(self, text: str) -> None:
        """
        Trigger AI voice announcement through Pete
        
        This could be:
        - Pete's voice
        - Detective Humphrey's noir narration
        - Any configured AI character
        """
        # TODO: Integrate with Pete's TTS system
        logger.info(f"🎭 Voice cue: '{text}'")
        # await self.pete.speak(text, voice="pete")
    
    async def _start_recording(self) -> None:
        """Transition from PREFLIGHT to LIVE recording"""
        logger.info("🔴 GOING LIVE - Recording started")
        self._state = StudioState.LIVE
        self._recording_start_time = time.time()
        
        # Activate Dead Man's Switch (periodic auto-save)
        self._dead_man_task = asyncio.create_task(self._dead_man_switch())
        
        await self._broadcast_state_update()
    
    async def stop_recording(self) -> None:
        """Stop recording and finalize save"""
        if self._state != StudioState.LIVE:
            logger.warning("Cannot stop recording - not in LIVE state")
            return
        
        duration = time.time() - (self._recording_start_time or 0)
        logger.info(f"⏹️ Recording stopped - Duration: {duration:.1f}s")
        
        self._state = StudioState.IDLE
        self._recording_start_time = None
        
        # Final save
        await self._save_recording("normal_stop")
        
        await self._broadcast_state_update()
    
    async def trigger_emergency_save(self, reason: str = "Manual trigger") -> None:
        """
        Emergency Save - The "Dead Man's Switch"
        
        Immediately flushes all buffers to disk with crash protection.
        This is the absolute last resort to preserve the recording.
        """
        logger.critical(f"🚨 EMERGENCY SAVE TRIGGERED: {reason}")
        self._state = StudioState.EMERGENCY
        
        # Broadcast emergency status immediately
        await self._broadcast_state_update()
        
        try:
            # Flush all audio/video buffers to disk
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = self._emergency_save_dir / f"emergency_{timestamp}"
            save_path.mkdir(exist_ok=True)
            
            # Save audio matrix state
            audio_state_file = save_path / "audio_matrix.json"
            with open(audio_state_file, 'w') as f:
                json.dump(self._audio_matrix.to_dict(), f, indent=2)
            
            # Save preflight check history
            preflight_file = save_path / "preflight_checks.json"
            with open(preflight_file, 'w') as f:
                json.dump([asdict(c) for c in self._preflight_checks], f, indent=2)
            
            # TODO: Integrate with Pete's recording system
            # await self.pete.emergency_flush_buffers(save_path)
            
            # Create recovery manifest
            manifest = {
                "timestamp": timestamp,
                "reason": reason,
                "state_before_emergency": self._state.value,
                "recording_duration": time.time() - (self._recording_start_time or 0),
                "audio_matrix": self._audio_matrix.to_dict(),
                "preflight_checks": [asdict(c) for c in self._preflight_checks]
            }
            
            manifest_file = save_path / "recovery_manifest.json"
            with open(manifest_file, 'w') as f:
                json.dump(manifest, f, indent=2)
            
            logger.info(f"✅ Emergency save complete: {save_path}")
            self._last_emergency_save = time.time()
            
        except Exception as e:
            logger.critical(f"💥 EMERGENCY SAVE FAILED: {e}", exc_info=True)
        
        finally:
            # Return to IDLE after emergency
            self._state = StudioState.IDLE
            await self._broadcast_state_update()
    
    async def _dead_man_switch(self) -> None:
        """
        Periodic auto-save during live recording
        
        Every N seconds (default 60s), automatically save current state.
        If the main system crashes, we have recent recovery points.
        """
        while self._state == StudioState.LIVE:
            await asyncio.sleep(self._dead_man_switch_interval)
            
            if self._state == StudioState.LIVE:
                logger.info("💾 Dead Man's Switch - Auto-save checkpoint")
                await self._save_recording("auto_checkpoint")
    
    async def _save_recording(self, save_type: str) -> None:
        """Save current recording state"""
        logger.info(f"💾 Saving recording ({save_type})...")
        
        # TODO: Integrate with Pete's recording pipeline
        # For now, just log the save
        duration = time.time() - (self._recording_start_time or 0)
        logger.info(f"📼 Recording saved: {duration:.1f}s duration")
    
    async def update_audio_channel(
        self,
        channel_id: str,
        signal_db: float,
        active: Optional[bool] = None
    ) -> None:
        """Update individual audio channel state"""
        channel = self._audio_matrix.get_channel(channel_id)
        if not channel:
            logger.warning(f"Unknown audio channel: {channel_id}")
            return
        
        channel.update_signal(signal_db)
        if active is not None:
            channel.active = active
        
        # Broadcast to UI if enough time has passed
        now = time.time()
        if now - self._last_audio_update > self._audio_update_interval:
            await self._broadcast_audio_update()
            self._last_audio_update = now
    
    async def mute_all_but_dialogue(self) -> None:
        """Isolation Mode - Mute everything except dialogue track"""
        logger.info("🔇 Isolation Mode activated - Dialogue only")
        
        for channel in self._audio_matrix.get_all_channels():
            if channel.channel_id != "dialogue":
                channel.active = False
                channel.status = AudioChannelStatus.MUTED
        
        await self._broadcast_audio_update()
    
    async def unmute_all_channels(self) -> None:
        """Restore all audio channels"""
        logger.info("🔊 All channels unmuted")
        
        for channel in self._audio_matrix.get_all_channels():
            channel.active = True
            if channel.status == AudioChannelStatus.MUTED:
                channel.status = AudioChannelStatus.OK
        
        await self._broadcast_audio_update()
    
    # ─────────────────────────────────────────────
    # WebSocket Broadcasting (UI Updates)
    # ─────────────────────────────────────────────
    
    def register_ws_client(self, client: Any) -> None:
        """Register WebSocket client for real-time updates"""
        self._ws_clients.append(client)
        logger.info(f"📡 WebSocket client registered ({len(self._ws_clients)} total)")
    
    def unregister_ws_client(self, client: Any) -> None:
        """Unregister WebSocket client"""
        if client in self._ws_clients:
            self._ws_clients.remove(client)
            logger.info(f"📡 WebSocket client disconnected ({len(self._ws_clients)} remaining)")
    
    async def _broadcast_state_update(self) -> None:
        """Broadcast studio state change to all clients"""
        message = {
            "type": "state_update",
            "state": self._state.value,
            "timestamp": time.time()
        }
        await self._broadcast(message)
    
    async def _broadcast_audio_update(self) -> None:
        """Broadcast audio matrix update to all clients"""
        message = {
            "type": "audio_update",
            "audio_matrix": self._audio_matrix.to_dict(),
            "timestamp": time.time()
        }
        await self._broadcast(message)
    
    async def _broadcast_countdown(self, seconds: int) -> None:
        """Broadcast countdown update"""
        message = {
            "type": "countdown",
            "seconds": seconds,
            "timestamp": time.time()
        }
        await self._broadcast(message)
    
    async def _broadcast_check_result(self, check: PreflightCheck) -> None:
        """Broadcast preflight check result"""
        message = {
            "type": "preflight_check",
            "check": asdict(check),
            "timestamp": time.time()
        }
        await self._broadcast(message)
    
    async def _broadcast(self, message: Dict[str, Any]) -> None:
        """Send message to all registered WebSocket clients"""
        if not self._ws_clients:
            return
        
        # TODO: Implement actual WebSocket send
        # For now, just log
        logger.debug(f"📡 Broadcasting: {message['type']}")
    
    async def start_preflight(self, room: str = "studio") -> Dict[str, Any]:
        """Compatibility wrapper used by main.py and the REST API."""
        success = await self.run_preflight_sequence()
        return {
            "room": room,
            "success": success,
            "state": self._state.value,
            "checks": [asdict(c) for c in self._preflight_checks],
        }

    async def emergency_save(self, reason: str = "Manual trigger") -> Dict[str, Any]:
        """Compatibility wrapper used by main.py and the REST API."""
        await self.trigger_emergency_save(reason=reason)
        return {
            "ok": True,
            "state": self._state.value,
            "reason": reason,
            "last_emergency_save": self._last_emergency_save,
        }

    def get_status_summary(self) -> Dict[str, Any]:
        """Get complete studio status for dashboard"""
        return {
            "state": self._state.value,
            "audio_matrix": self._audio_matrix.to_dict(),
            "preflight_checks": [asdict(c) for c in self._preflight_checks],
            "recording_duration": (
                time.time() - self._recording_start_time
                if self._recording_start_time else 0
            ),
            "ghost_mics": self._ghost_mics,
            "last_emergency_save": self._last_emergency_save
        }
