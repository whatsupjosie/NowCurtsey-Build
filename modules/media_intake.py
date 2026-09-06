"""
modules/media_intake.py — PubCast media/code intake classifier.

This module accepts common studio media, phone recordings, still images, MIDI,
edit metadata, transcripts, and code/project files, stores them safely, and
returns a classification manifest. It does not promise decode/transcode support;
decode/transcode belongs to the next pipeline layer, usually FFmpeg for audio/video.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class IntakeFormat:
    extension: str
    kind: str
    label: str
    notes: str = ""


AUDIO_FORMATS: Dict[str, IntakeFormat] = {
    ".mp3": IntakeFormat(".mp3", "audio_asset", "MP3 audio"),
    ".wav": IntakeFormat(".wav", "audio_asset", "WAV audio"),
    ".wave": IntakeFormat(".wave", "audio_asset", "WAV audio"),
    ".m4a": IntakeFormat(".m4a", "audio_asset", "MPEG-4 audio", "Common iPhone Voice Memos / Apple audio format."),
    ".aac": IntakeFormat(".aac", "audio_asset", "AAC audio"),
    ".caf": IntakeFormat(".caf", "audio_asset", "Core Audio Format", "Apple/iOS audio container sometimes used by recorders."),
    ".aif": IntakeFormat(".aif", "audio_asset", "AIFF audio"),
    ".aiff": IntakeFormat(".aiff", "audio_asset", "AIFF audio"),
    ".flac": IntakeFormat(".flac", "audio_asset", "FLAC audio"),
    ".ogg": IntakeFormat(".ogg", "audio_asset", "Ogg audio"),
    ".oga": IntakeFormat(".oga", "audio_asset", "Ogg audio"),
    ".opus": IntakeFormat(".opus", "audio_asset", "Opus audio"),
    ".wma": IntakeFormat(".wma", "audio_asset", "Windows Media Audio"),
    ".amr": IntakeFormat(".amr", "audio_asset", "AMR voice recording", "Common older phone/voice-recorder format."),
    ".m4b": IntakeFormat(".m4b", "audio_asset", "MPEG-4 audiobook audio"),
    ".m4p": IntakeFormat(".m4p", "audio_asset", "Protected MPEG-4 audio", "Accepted for storage; DRM-protected files may not decode."),
    ".m4r": IntakeFormat(".m4r", "audio_asset", "MPEG-4 ringtone audio"),
}

MIDI_FORMATS: Dict[str, IntakeFormat] = {
    ".mid": IntakeFormat(".mid", "midi_asset", "MIDI sequence"),
    ".midi": IntakeFormat(".midi", "midi_asset", "MIDI sequence"),
    ".kar": IntakeFormat(".kar", "midi_asset", "Karaoke MIDI"),
}

VIDEO_FORMATS: Dict[str, IntakeFormat] = {
    ".mp4": IntakeFormat(".mp4", "video_asset", "MP4 video"),
    ".m4v": IntakeFormat(".m4v", "video_asset", "MPEG-4 video"),
    ".mov": IntakeFormat(".mov", "video_asset", "QuickTime MOV video"),
    ".webm": IntakeFormat(".webm", "video_asset", "WebM video"),
    ".mkv": IntakeFormat(".mkv", "video_asset", "Matroska video"),
    ".avi": IntakeFormat(".avi", "video_asset", "AVI video"),
    ".arv": IntakeFormat(".arv", "video_asset", "ARV video/file", "Accepted because field recordings may arrive with this extension; decoder support must be verified."),
    ".3gp": IntakeFormat(".3gp", "video_asset", "3GPP phone video"),
    ".3g2": IntakeFormat(".3g2", "video_asset", "3GPP2 phone video"),
    ".mpeg": IntakeFormat(".mpeg", "video_asset", "MPEG video"),
    ".mpg": IntakeFormat(".mpg", "video_asset", "MPEG video"),
    ".wmv": IntakeFormat(".wmv", "video_asset", "Windows Media Video"),
}

IMAGE_FORMATS: Dict[str, IntakeFormat] = {
    ".png": IntakeFormat(".png", "image_asset", "PNG image"),
    ".jpg": IntakeFormat(".jpg", "image_asset", "JPEG image"),
    ".jpeg": IntakeFormat(".jpeg", "image_asset", "JPEG image"),
    ".heic": IntakeFormat(".heic", "image_asset", "HEIC iPhone image", "Common iPhone photo format; decode support depends on installed libraries."),
    ".heif": IntakeFormat(".heif", "image_asset", "HEIF image", "Decode support depends on installed libraries."),
    ".webp": IntakeFormat(".webp", "image_asset", "WebP image"),
    ".gif": IntakeFormat(".gif", "image_asset", "GIF image/animation"),
    ".tif": IntakeFormat(".tif", "image_asset", "TIFF image"),
    ".tiff": IntakeFormat(".tiff", "image_asset", "TIFF image"),
    ".bmp": IntakeFormat(".bmp", "image_asset", "Bitmap image"),
}

SESSION_FORMATS: Dict[str, IntakeFormat] = {
    ".zip": IntakeFormat(".zip", "recording_bundle", "Recording/session bundle"),
    ".json": IntakeFormat(".json", "timeline_metadata", "JSON metadata"),
    ".edl": IntakeFormat(".edl", "edit_list", "Edit Decision List"),
    ".fcpxml": IntakeFormat(".fcpxml", "edit_list", "Final Cut Pro XML"),
    ".xml": IntakeFormat(".xml", "timeline_metadata", "XML metadata"),
}

CAPTION_TRANSCRIPT_FORMATS: Dict[str, IntakeFormat] = {
    ".srt": IntakeFormat(".srt", "caption_track", "SubRip captions"),
    ".vtt": IntakeFormat(".vtt", "caption_track", "WebVTT captions"),
    ".txt": IntakeFormat(".txt", "transcript", "Plain text transcript"),
    ".md": IntakeFormat(".md", "transcript", "Markdown transcript/notes"),
}

CODE_FORMATS: Dict[str, IntakeFormat] = {
    ".py": IntakeFormat(".py", "code_asset", "Python code"),
    ".js": IntakeFormat(".js", "code_asset", "JavaScript code"),
    ".ts": IntakeFormat(".ts", "code_asset", "TypeScript code"),
    ".jsx": IntakeFormat(".jsx", "code_asset", "React JSX code"),
    ".tsx": IntakeFormat(".tsx", "code_asset", "React TSX code"),
    ".html": IntakeFormat(".html", "code_asset", "HTML document"),
    ".css": IntakeFormat(".css", "code_asset", "CSS stylesheet"),
    ".yaml": IntakeFormat(".yaml", "code_asset", "YAML config"),
    ".yml": IntakeFormat(".yml", "code_asset", "YAML config"),
    ".toml": IntakeFormat(".toml", "code_asset", "TOML config"),
    ".rs": IntakeFormat(".rs", "code_asset", "Rust code"),
    ".cpp": IntakeFormat(".cpp", "code_asset", "C++ code"),
    ".h": IntakeFormat(".h", "code_asset", "C/C++ header"),
    ".hpp": IntakeFormat(".hpp", "code_asset", "C++ header"),
}

ACCEPTED_FORMATS: Dict[str, IntakeFormat] = {
    **AUDIO_FORMATS,
    **MIDI_FORMATS,
    **VIDEO_FORMATS,
    **IMAGE_FORMATS,
    **SESSION_FORMATS,
    **CAPTION_TRANSCRIPT_FORMATS,
    **CODE_FORMATS,
}

_KIND_DIRS: Mapping[str, str] = {
    "audio_asset": "audio",
    "midi_asset": "midi",
    "video_asset": "video",
    "image_asset": "images",
    "recording_bundle": "bundles",
    "edit_list": "edit_lists",
    "timeline_metadata": "metadata",
    "caption_track": "captions",
    "transcript": "transcripts",
    "code_asset": "code",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_upload_name(filename: str) -> str:
    base = Path(filename or "upload").name.strip().replace("\\", "_").replace("/", "_")
    base = _SAFE_NAME_RE.sub("_", base).strip(" ._")
    return base or "upload"


def classify_filename(filename: str) -> Optional[IntakeFormat]:
    name = sanitize_upload_name(filename)
    lower = name.lower()
    for ext in sorted(ACCEPTED_FORMATS.keys(), key=len, reverse=True):
        if lower.endswith(ext):
            return ACCEPTED_FORMATS[ext]
    return None


def accepted_formats_manifest() -> Dict[str, Any]:
    by_kind: Dict[str, list[Dict[str, str]]] = {}
    for ext, fmt in sorted(ACCEPTED_FORMATS.items()):
        by_kind.setdefault(fmt.kind, []).append(
            {"extension": ext, "label": fmt.label, "notes": fmt.notes}
        )
    return {
        "status": "ok",
        "accepted_extensions": sorted(ACCEPTED_FORMATS.keys()),
        "by_kind": by_kind,
    }


def destination_for_upload(base_dir: Path, filename: str, fmt: IntakeFormat) -> Path:
    safe_name = sanitize_upload_name(filename)
    kind_dir = _KIND_DIRS.get(fmt.kind, "unknown")
    target_dir = base_dir / "media_intake" / kind_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(safe_name).stem or "upload"
    suffix = Path(safe_name).suffix or fmt.extension
    unique = f"{stem}_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix.lower()}"
    return target_dir / unique


async def save_upload_file(upload: Any, destination: Path, *, chunk_size: int = 1024 * 1024) -> int:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)
    return size


__all__ = [
    "ACCEPTED_FORMATS",
    "AUDIO_FORMATS",
    "MIDI_FORMATS",
    "VIDEO_FORMATS",
    "IMAGE_FORMATS",
    "IntakeFormat",
    "accepted_formats_manifest",
    "classify_filename",
    "destination_for_upload",
    "sanitize_upload_name",
    "save_upload_file",
]
