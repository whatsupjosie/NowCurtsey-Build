from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
import os, json, hashlib, hmac

# Local paths (mirror main.py layout)
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = DATA_DIR / "media"
RECORDINGS_DIR = MEDIA_DIR / "recordings"
EXPORTS_DIR = DATA_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _ffmpeg() -> str:
    ff = os.getenv("PUBCAST_FFMPEG") or shutil.which("ffmpeg")
    if not ff:
        raise HTTPException(status_code=503, detail="ffmpeg not available on server")
    return ff


def _ffprobe() -> Optional[str]:
    return os.getenv("PUBCAST_FFPROBE") or shutil.which("ffprobe")


def _human_size(num: int) -> str:
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _human_duration(sec: float) -> str:
    try:
        sec = float(sec)
    except Exception:
        return ""
    m, s = divmod(int(sec + 0.5), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


async def _probe_meta(path: Path) -> Dict[str, Any]:
    """Return simple metadata via ffprobe if available."""
    fp = _ffprobe()
    if not fp:
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            fp,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=6.0)
        if not out:
            return {}
        js = json.loads(out.decode("utf-8", "ignore"))
        meta: Dict[str, Any] = {}
        fmt = js.get("format") or {}
        dur = fmt.get("duration")
        if dur:
            try:
                durf = float(dur)
                meta["duration"] = durf
                meta["duration_str"] = _human_duration(durf)
            except Exception:
                pass
        meta["bit_rate"] = fmt.get("bit_rate")
        streams = []
        for st in js.get("streams", []) or []:
            kind = st.get("codec_type")
            if kind == "video":
                streams.append({
                    "type": "video",
                    "codec": st.get("codec_name"),
                    "width": st.get("width"),
                    "height": st.get("height"),
                    "fps": st.get("avg_frame_rate"),
                })
            elif kind == "audio":
                streams.append({
                    "type": "audio",
                    "codec": st.get("codec_name"),
                    "sample_rate": st.get("sample_rate"),
                    "channels": st.get("channels"),
                })
        meta["streams"] = streams
        return meta
    except Exception:
        return {}


def _tags_path() -> Path:
    return MEDIA_DIR / "media_tags.json"


def _load_tags() -> Dict[str, Any]:
    try:
        p = _tags_path()
        if not p.exists():
            return {"tags": {}, "ratings": {}}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"tags": {}, "ratings": {}}


def _save_tags(state: Dict[str, Any]) -> None:
    p = _tags_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def require_admin(request: Request) -> None:
    key = os.getenv("PUBCAST_ADMIN_KEY", "").strip()
    require_auth = os.getenv("PUBCAST_REQUIRE_AUTH", "false").strip().lower() in ("1", "true", "yes")
    supplied = request.headers.get("x-admin-key") or request.headers.get("X-Admin-Key")
    if key and supplied == key:
        return
    if require_auth:
        # Try Bearer JWT
        try:
            from modules.security.auth import SecurityManager  # type: ignore
        except Exception:
            SecurityManager = None  # type: ignore
        try:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if SecurityManager and auth and auth.lower().startswith("bearer "):
                payload = SecurityManager.decode_token(auth.split(" ", 1)[1].strip())
                enforce_roles = os.getenv("PUBCAST_ENFORCE_ROLES", "true").strip().lower() in ("1", "true", "yes")
                if enforce_roles:
                    allowed = {"producer", "editor", "admin", "super_admin"}
                    if str(getattr(payload, 'role', '')).lower() not in allowed:
                        raise HTTPException(status_code=403, detail="forbidden")
                return
        except Exception:
            pass
        # Try X-API-Key
        try:
            api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
            if api_key:
                keys_path = DATA_DIR / "security" / "api_keys.json"
                if keys_path.exists():
                    state = json.loads(keys_path.read_text(encoding="utf8"))
                    for k in state.get("keys", []):
                        if k.get("is_active"):
                            pref = (k.get("prefix") or "")
                            if api_key.startswith(pref):
                                h = hashlib.sha256(api_key.encode()).hexdigest()
                                if hmac.compare_digest(h, k.get("key_hash", "")):
                                    return
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="auth_required")
    return


router = APIRouter(prefix="/api/media", tags=["Media Management"])


@router.get("")
async def list_media(include_metadata: bool = Query(False), limit: int = Query(100, ge=1, le=1000)):
    exts = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"}
    paths: List[Tuple[Path, os.stat_result]] = []
    for root, _, files in os.walk(RECORDINGS_DIR):
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in exts:
                try:
                    st = p.stat()
                except Exception:
                    continue
                paths.append((p, st))
    paths.sort(key=lambda t: t[1].st_mtime, reverse=True)

    tag_state = _load_tags()
    tags = tag_state.get("tags", {})
    ratings = tag_state.get("ratings", {})

    items: List[Dict[str, Any]] = []
    for p, st in paths[:limit]:
        rel = str(p.relative_to(DATA_DIR)).replace("\\", "/")
        media_id = _media_id(rel)
        item: Dict[str, Any] = {
            "name": p.name,
            "path": rel,
            "bytes": st.st_size,
            "size": _human_size(st.st_size),
            "modified": st.st_mtime,
            "tags": tags.get(media_id, []),
            "rating": ratings.get(media_id),
        }
        if include_metadata:
            meta = await _probe_meta(p)
            if meta:
                item.update({
                    "duration": meta.get("duration"),
                    "duration_str": meta.get("duration_str"),
                    "bitrate": meta.get("bit_rate"),
                })
                # summarize first streams
                vids = [s for s in meta.get("streams", []) if s.get("type") == "video"]
                auds = [s for s in meta.get("streams", []) if s.get("type") == "audio"]
                if vids:
                    v = vids[0]
                    res = f"{v.get('width')}x{v.get('height')}" if v.get("width") else None
                    item["video"] = {"codec": v.get("codec"), "resolution": res, "fps": v.get("fps")}
                if auds:
                    a = auds[0]
                    item["audio"] = {"codec": a.get("codec"), "sample_rate": a.get("sample_rate"), "channels": a.get("channels")}
        # thumbnails/previews if present
        th = p.with_suffix(".jpg")
        if th.exists():
            item["thumbnail"] = str(th.relative_to(DATA_DIR)).replace("\\", "/")
        pv = p.with_name(p.stem + "__preview.mp4")
        if pv.exists():
            item["preview"] = str(pv.relative_to(DATA_DIR)).replace("\\", "/")
        items.append(item)

    return {"items": items, "total": len(items), "limit": limit}


def _media_id(path: str) -> str:
    import hashlib
    return hashlib.sha256(path.encode()).hexdigest()[:16]


@router.post("/{path:path}/tag")
async def tag_media(path: str, req: Dict[str, Any], request: Request):
    require_admin(request)
    tags_req = [str(t).strip().lower() for t in (req.get("tags") or []) if str(t).strip()]
    if not tags_req:
        raise HTTPException(status_code=400, detail="No tags provided")
    state = _load_tags()
    media_id = _media_id(path)
    existing = set(state.get("tags", {}).get(media_id, []))
    existing.update(tags_req)
    state.setdefault("tags", {})[media_id] = sorted(existing)
    _save_tags(state)
    return {"ok": True, "tags": state["tags"][media_id]}


@router.delete("/{path:path}/tag")
async def untag_media(path: str, tag: str, request: Request):
    require_admin(request)
    state = _load_tags()
    media_id = _media_id(path)
    existing = set(state.get("tags", {}).get(media_id, []))
    existing.discard(tag.strip().lower())
    if existing:
        state.setdefault("tags", {})[media_id] = sorted(existing)
    else:
        state.get("tags", {}).pop(media_id, None)
    _save_tags(state)
    return {"ok": True, "tags": sorted(existing)}


@router.post("/{path:path}/rate")
async def rate_media(path: str, req: Dict[str, Any], request: Request):
    require_admin(request)
    try:
        rating = int(req.get("rating"))
        if rating < 1 or rating > 5:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    state = _load_tags()
    state.setdefault("ratings", {})[_media_id(path)] = rating
    _save_tags(state)
    return {"ok": True, "rating": rating}


@router.delete("/{path:path}/rate")
async def unrate_media(path: str, request: Request):
    require_admin(request)
    state = _load_tags()
    state.get("ratings", {}).pop(_media_id(path), None)
    _save_tags(state)
    return {"ok": True}


@router.get("/search")
async def search_media(tags: Optional[str] = Query(None), rating_min: Optional[int] = Query(None, ge=1, le=5), query: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=500)):
    resp = await list_media(include_metadata=False, limit=1000)
    items = resp["items"]
    state = _load_tags()
    tags_map = state.get("tags", {})
    ratings = state.get("ratings", {})
    want = set()
    if tags:
        want = {t.strip().lower() for t in tags.split(",") if t.strip()}
    results: List[Dict[str, Any]] = []
    for it in items:
        mid = _media_id(it["path"])
        item_tags = set(tags_map.get(mid, []))
        item_rating = ratings.get(mid)
        if want and not want.issubset(item_tags):
            continue
        if rating_min is not None and (item_rating is None or item_rating < rating_min):
            continue
        if query and (query.lower() not in it["name"].lower()):
            continue
        it2 = dict(it)
        it2["tags"] = list(item_tags)
        it2["rating"] = item_rating
        results.append(it2)
    return {"results": results[:limit], "total": len(results)}


@router.post("/{path:path}/thumbnail")
async def generate_thumbnail(path: str, timestamp: float = Query(1.0), width: int = Query(480, ge=64, le=1920), request: Request = None):
    require_admin(request)
    src = (DATA_DIR / path).resolve()
    if not str(src).startswith(str(DATA_DIR.resolve())) or not src.is_file():
        raise HTTPException(status_code=404, detail="Source not found")
    out = src.with_suffix(".jpg")
    ff = _ffmpeg()
    # extract one frame
    cmd = [ff, "-y", "-ss", f"{timestamp:.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"thumbnail error: {exc}")
    if not out.exists():
        raise HTTPException(status_code=500, detail="thumbnail not created")
    return {"ok": True, "thumbnail": str(out.relative_to(DATA_DIR)).replace("\\", "/")}


@router.post("/{path:path}/proxy")
async def generate_proxy(path: str, width: int = Query(960, ge=160, le=1920), quality: str = Query("preview"), request: Request = None):
    require_admin(request)
    src = (DATA_DIR / path).resolve()
    if not str(src).startswith(str(DATA_DIR.resolve())) or not src.is_file():
        raise HTTPException(status_code=404, detail="Source not found")
    ff = _ffmpeg()
    quality_map = {"draft": (28, "ultrafast"), "preview": (23, "fast"), "high": (18, "medium")}
    if quality not in quality_map:
        raise HTTPException(status_code=400, detail="invalid quality")
    crf, preset = quality_map[quality]
    out = src.with_name(src.stem + f"__proxy_{quality}.mp4")
    cmd = [ff, "-y", "-i", str(src), "-vf", f"scale='min({width},iw)':-2", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.wait(), timeout=3600)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"proxy error: {exc}")
    if not out.exists():
        raise HTTPException(status_code=500, detail="proxy not created")
    return {"ok": True, "proxy": str(out.relative_to(DATA_DIR)).replace("\\", "/")}
