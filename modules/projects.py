# PubCast AI — projects.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""modules/projects.py — Autosave/restore for builder sessions."""
from __future__ import annotations
import asyncio, json, logging, time, uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .save_metadata import attach_save_metadata
from .persistence import read_json, write_json

logger = logging.getLogger(__name__)

def _autosave_dir(data_dir: Path, slug: str) -> Path:
    d = Path(data_dir) / "projects" / slug / "autosaves"
    d.mkdir(parents=True, exist_ok=True)
    return d

def list_autosaves(data_dir: Path, slug: str) -> List[Dict[str, Any]]:
    results = []
    for f in sorted(_autosave_dir(data_dir, slug).glob("*.json"), reverse=True)[:20]:
        try:
            data = read_json(f)
            manifest = data.get("save_manifest", {}) if isinstance(data, dict) else {}
            project_identity = data.get("project_identity", {}) if isinstance(data, dict) else {}
            session_credits = data.get("session_credits", {}) if isinstance(data, dict) else {}
            results.append({
                "path": str(f),
                "ts": data.get("ts", 0),
                "id": f.stem,
                "title": project_identity.get("canonical_title") or manifest.get("title") or slug,
                "session_id": session_credits.get("session_id") or manifest.get("session_id"),
                "participant_count": manifest.get("participant_count", len(session_credits.get("participants", []))),
                "save_kind": manifest.get("save_kind", "autosave"),
            })
        except Exception as exc:
            logger.warning("projects: skipping corrupt autosave %s: %s", f.name, exc)
    return results

async def save_autosave_snapshot(data_dir: Path, slug: str, payload: Dict[str, Any]) -> Path:
    d = _autosave_dir(data_dir, slug)
    ts = time.time()
    path = d / f"{int(ts)}_{uuid.uuid4().hex[:8]}.json"
    wrapped = attach_save_metadata(slug=slug, payload=payload, save_kind="autosave")
    payload_with_ts = {"ts": ts, **wrapped}
    write_json(path, payload_with_ts)
    # Keep only last 20 autosaves
    files = sorted(d.glob("*.json"))
    for old in files[:-20]: old.unlink(missing_ok=True)
    return path

def latest_autosave_path(data_dir: Path, slug: str) -> Optional[Path]:
    files = sorted(_autosave_dir(data_dir, slug).glob("*.json"), reverse=True)
    return files[0] if files else None

__all__ = ["list_autosaves", "save_autosave_snapshot", "latest_autosave_path"]
