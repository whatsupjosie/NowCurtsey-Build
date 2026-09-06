"""Approval bridge for Visual Patch Kit output.

The bridge is the first real incorporation hook: it takes an approved visual
patch/adaptive object proposal and persists it through the existing PubWorld
prop and optional voxel-set contracts. It does not run vision, animation, or
event-bus orchestration by itself.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .visual_patch_voxel_adapter import (
    adaptive_extension_to_pubworld_prop,
    pubworld_prop_to_voxel_set,
    visual_patch_to_pubworld_prop,
)


APPROVED_STATES = {"approved", "auto_approved"}
TARGETS = {"pubworld_prop", "voxel_set", "both"}


class VisualPatchApprovalError(ValueError):
    """Raised when a patch cannot be submitted into live storage."""


def submit_approved_visual_patch(
    data_dir: Path,
    request: Mapping[str, Any],
    *,
    create_prop_func: Callable[..., Any],
    save_voxel_set_func: Optional[Callable[..., Path]] = None,
    stage_voxels_func: Optional[Callable[[Any], Any]] = None,
    max_blocks: int = 50000,
) -> Dict[str, Any]:
    """Persist an approved patch/adaptive extension through PubWorld/voxel APIs."""

    body = dict(request)
    target = str(body.get("target") or body.get("submit_to") or "pubworld_prop").strip()
    if target not in TARGETS:
        raise VisualPatchApprovalError(f"target must be one of {sorted(TARGETS)}")

    approval = _approval(body)
    if not _is_approved(approval, body):
        raise VisualPatchApprovalError("visual patch must be approved before it can update PubWorld or voxel storage")

    patch_kind = _patch_kind(body)
    scene_id = _text(body.get("scene_id"), "scene_default")
    label = _optional_text(body.get("label") or body.get("name"))
    proposal = _proposal_payload(body)
    if patch_kind == "adaptive_extension":
        prop_payload = adaptive_extension_to_pubworld_prop(proposal, scene_id=scene_id, label=label, max_blocks=max_blocks)
        stable_id = _text(proposal.get("extension_id"), f"adaptive_ext_{int(time.time() * 1000)}")
    else:
        prop_payload = visual_patch_to_pubworld_prop(proposal, scene_id=scene_id, label=label, max_blocks=max_blocks)
        stable_id = _text(proposal.get("patch_id"), f"visual_patch_{int(time.time() * 1000)}")

    prop_result = None
    if target in {"pubworld_prop", "both"}:
        if create_prop_func is None:
            raise VisualPatchApprovalError("PubWorld prop creation is not available")
        prop_result = create_prop_func(
            Path(data_dir),
            scene_id=prop_payload["scene_id"],
            label=prop_payload["label"],
            description=prop_payload["description"],
            blocks=prop_payload["blocks"],
            variants=prop_payload.get("variants"),
        )

    voxel_path = None
    voxel_payload = None
    if target in {"voxel_set", "both"}:
        if save_voxel_set_func is None:
            raise VisualPatchApprovalError("voxel-set saving is not available")
        asset_id = _unique_asset_id(stable_id, body)
        voxel_payload = pubworld_prop_to_voxel_set(
            prop_payload,
            asset_id=asset_id,
            name=prop_payload["label"],
            approved_by_user=True,
        )
        voxel_path = save_voxel_set_func(Path(data_dir), voxel_payload)

    prop_dump = _dump_model(prop_result)
    response_blocks = prop_dump.get("blocks") if prop_dump else prop_payload["blocks"]
    stage_voxels = stage_voxels_func(response_blocks) if stage_voxels_func else None
    return {
        "ok": True,
        "patch_kind": patch_kind,
        "target": target,
        "approval": {
            "state": _approval_state(approval, body),
            "auto_approved": bool(body.get("auto_approve") or body.get("auto_approved")),
        },
        "pubworld_payload": prop_payload,
        "prop": prop_dump,
        "voxel_set": voxel_payload,
        "voxel_set_path": str(voxel_path) if voxel_path else None,
        "voxels": stage_voxels,
    }


def _approval(body: Mapping[str, Any]) -> Dict[str, Any]:
    approval = body.get("approval")
    return dict(approval) if isinstance(approval, Mapping) else {}


def _is_approved(approval: Mapping[str, Any], body: Mapping[str, Any]) -> bool:
    return _approval_state(approval, body) in APPROVED_STATES


def _approval_state(approval: Mapping[str, Any], body: Mapping[str, Any]) -> str:
    if body.get("auto_approve") is True or body.get("auto_approved") is True:
        return "auto_approved"
    return str(approval.get("state") or body.get("approval_state") or "").strip().lower()


def _patch_kind(body: Mapping[str, Any]) -> str:
    raw = str(body.get("patch_kind") or body.get("kind") or "").strip().lower()
    if raw in {"visual_patch", "patch", "body_patch", "costume_patch"}:
        return "visual_patch"
    if raw in {"adaptive_extension", "adaptive_prop", "object_extension", "prop_extension"}:
        return "adaptive_extension"
    if isinstance(body.get("adaptive_extension"), Mapping) or isinstance(body.get("extension"), Mapping):
        return "adaptive_extension"
    return "visual_patch"


def _proposal_payload(body: Mapping[str, Any]) -> Dict[str, Any]:
    for key in ("proposal", "patch", "visual_patch", "adaptive_extension", "extension"):
        value = body.get(key)
        if isinstance(value, Mapping):
            merged = dict(value)
            if "approval" not in merged and isinstance(body.get("approval"), Mapping):
                merged["approval"] = dict(body["approval"])
            return merged
    return dict(body)


def _dump_model(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _unique_asset_id(stable_id: str, body: Mapping[str, Any]) -> str:
    requested = str(body.get("asset_id") or "").strip()
    raw = requested or f"{stable_id}_{int(time.time() * 1000)}"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    return safe[:96] or f"visual_patch_{int(time.time())}"


def _text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


__all__ = ["VisualPatchApprovalError", "submit_approved_visual_patch"]
