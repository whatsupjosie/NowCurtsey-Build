"""Pub Manager recovery contract and safe action scaffold.

The Pub Manager is the top diagnostic helper for PubCast. This module is
intentionally dependency-free so it can power menus, safe console checks, and
future AI explanations without requiring the full runtime to be alive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Dict, Iterable, List, Literal

Severity = Literal["ok", "warn", "error"]

SAFE_ACTIONS = {
    "program_audio.stop_all": "Stop all program sounds",
    "animation.stop_all": "Stop all animations",
    "avatar.reset_pose": "Reset avatar pose",
    "mocap.pause": "Pause mocap input",
    "room.reload_assets": "Reload room assets",
    "websocket.reconnect": "Reconnect WebSocket",
    "recording.status": "Check recording status",
    "assets.check_manifest": "Check asset manifest",
    "issue.export": "Export issue report",
    "ai.model_slots": "Check Alex/Jeremy model slot status",
    "ai.switchblade_status": "Preview Switchblade routing and model slot selection",
    "runtime.spine_status": "Check runtime spine availability",
    "voxel.block_kit_status": "Check PubBlock voxel block kit status",
    "voxel.block_kit_preview": "Generate a read-only PubBlock voxel preview",
}

APPROVAL_REQUIRED_ACTIONS = {
    "visual_patch.save_permanent": "Permanently save a visual patch",
    "asset.replace_original": "Replace an original asset",
    "system.install_dependency": "Install a dependency",
    "files.delete": "Delete files",
}


@dataclass
class SystemStatus:
    system: str
    severity: Severity = "ok"
    message: str = "ok"
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"system": self.system, "severity": self.severity, "message": self.message, "data": self.data}


@dataclass
class PubManagerSnapshot:
    statuses: List[SystemStatus] = field(default_factory=list)
    created_at: float = field(default_factory=time)

    def overall(self) -> Severity:
        severities = {status.severity for status in self.statuses}
        if "error" in severities:
            return "error"
        if "warn" in severities:
            return "warn"
        return "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at,
            "overall": self.overall(),
            "systems": [status.to_dict() for status in self.statuses],
            "safe_actions": safe_actions(),
            "approval_required_actions": approval_required_actions(),
        }


def safe_actions() -> List[Dict[str, str]]:
    return [{"id": key, "label": label, "safety": "safe"} for key, label in sorted(SAFE_ACTIONS.items())]


def approval_required_actions() -> List[Dict[str, str]]:
    return [{"id": key, "label": label, "safety": "approval_required"} for key, label in sorted(APPROVAL_REQUIRED_ACTIONS.items())]


def validate_action(action_id: str) -> Dict[str, Any]:
    if action_id in SAFE_ACTIONS:
        return {"ok": True, "action_id": action_id, "label": SAFE_ACTIONS[action_id], "requires_approval": False}
    if action_id in APPROVAL_REQUIRED_ACTIONS:
        return {"ok": False, "action_id": action_id, "label": APPROVAL_REQUIRED_ACTIONS[action_id], "requires_approval": True}
    return {"ok": False, "action_id": action_id, "error": "unknown_action", "requires_approval": True}


def build_snapshot(raw: Dict[str, Any] | None = None) -> PubManagerSnapshot:
    raw = raw or {}
    statuses = []
    systems = [
        "runtime", "websocket", "assets", "avatar", "motion", "audio", "recording",
        "visual_patch", "conversation_ai", "alex", "jeremy", "evo", "eq", "model_slots",
        "switchblade_router", "background_math", "runtime_spine", "voxel_block_kit", "storage",
    ]
    for system in systems:
        info = raw.get(system, {}) if isinstance(raw.get(system, {}), dict) else {}
        severity = info.get("severity") or ("error" if info.get("error") else "warn" if info.get("warning") else "ok")
        if severity not in {"ok", "warn", "error"}:
            severity = "warn"
        message = info.get("message") or info.get("error") or info.get("warning") or "ok"
        statuses.append(SystemStatus(system=system, severity=severity, message=str(message), data=info))
    return PubManagerSnapshot(statuses=statuses)


def suggest_recovery(snapshot: PubManagerSnapshot) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    by_system = {status.system: status for status in snapshot.statuses}
    if by_system.get("audio") and by_system["audio"].severity != "ok":
        suggestions.append({"action_id": "program_audio.stop_all", "reason": "Audio is reporting trouble."})
    if by_system.get("motion") and by_system["motion"].severity != "ok":
        suggestions.append({"action_id": "animation.stop_all", "reason": "Motion or animation is reporting trouble."})
        suggestions.append({"action_id": "avatar.reset_pose", "reason": "Reset pose is a safe first recovery step."})
    if by_system.get("assets") and by_system["assets"].severity != "ok":
        suggestions.append({"action_id": "assets.check_manifest", "reason": "Assets may be missing or failing to load."})
        suggestions.append({"action_id": "room.reload_assets", "reason": "Reload room assets after checking the manifest."})
    if by_system.get("websocket") and by_system["websocket"].severity != "ok":
        suggestions.append({"action_id": "websocket.reconnect", "reason": "WebSocket is not healthy."})
    if by_system.get("recording") and by_system["recording"].severity != "ok":
        suggestions.append({"action_id": "recording.status", "reason": "Recording needs a status check before further action."})
    if by_system.get("model_slots") and by_system["model_slots"].severity != "ok":
        suggestions.append({"action_id": "ai.model_slots", "reason": "Model slots need attention before live AI conversation use."})
    if by_system.get("switchblade_router") and by_system["switchblade_router"].severity != "ok":
        suggestions.append({"action_id": "ai.switchblade_status", "reason": "Switchblade routing needs a quick status preview."})
    if by_system.get("runtime_spine") and by_system["runtime_spine"].severity != "ok":
        suggestions.append({"action_id": "runtime.spine_status", "reason": "Runtime spine should be checked before layering more systems on top."})
    if by_system.get("voxel_block_kit") and by_system["voxel_block_kit"].severity != "ok":
        suggestions.append({"action_id": "voxel.block_kit_status", "reason": "PubBlock voxel kit needs a status check before builder or set workflows rely on it."})
    if not suggestions:
        suggestions.append({"action_id": "issue.export", "reason": "No obvious fault; export an issue report if the user still sees trouble."})
    return suggestions


def issue_report(snapshot: PubManagerSnapshot, recent_errors: Iterable[str] | None = None) -> Dict[str, Any]:
    return {
        "created_at": time(),
        "overall": snapshot.overall(),
        "systems": [status.to_dict() for status in snapshot.statuses],
        "suggestions": suggest_recovery(snapshot),
        "recent_errors": list(recent_errors or []),
    }


__all__ = [
    "APPROVAL_REQUIRED_ACTIONS", "SAFE_ACTIONS", "PubManagerSnapshot", "SystemStatus",
    "approval_required_actions", "build_snapshot", "issue_report", "safe_actions", "suggest_recovery",
    "validate_action",
]
