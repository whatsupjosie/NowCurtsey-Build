"""Local document and message storage for the PubCast typewriter workspace."""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from .persistence import read_json, write_json


SYSTEM_FOLDERS = [
    {"folder_id": "drafts", "name": "Drafts", "kind": "document", "system": True},
    {"folder_id": "scripts", "name": "Scripts", "kind": "document", "system": True},
    {"folder_id": "notes", "name": "Notes", "kind": "document", "system": True},
    {"folder_id": "inbox", "name": "Inbox", "kind": "message", "system": True},
    {"folder_id": "sent", "name": "Sent", "kind": "message", "system": True},
]


def _now() -> float:
    return time.time()


def _doc_id() -> str:
    return f"doc_{uuid.uuid4().hex[:10]}"


def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:10]}"


def _state_path(data_dir: Path, user_id: str) -> Path:
    return Path(data_dir) / "documents" / f"{user_id}.json"


def _seed_state(user_id: str) -> Dict[str, Any]:
    ts = _now()
    welcome_doc = {
        "doc_id": _doc_id(),
        "title": "Welcome to PubCast",
        "folder_id": "notes",
        "doc_type": "creative",
        "content": (
            "Welcome to your dressing room workspace.\n\n"
            "Use Creative Writing for notes and freeform ideas.\n"
            "Use Script Writing for screenplay-style drafting.\n"
            "Use Email / Messages for production communication."
        ),
        "created_at": ts,
        "updated_at": ts,
        "metadata": {"seed": True},
    }
    script_doc = {
        "doc_id": _doc_id(),
        "title": "Cold Open",
        "folder_id": "scripts",
        "doc_type": "script",
        "content": (
            "INT. PUBCAST STUDIO - NIGHT\n\n"
            "The lights rise on a velvet set.\n\n"
            "HOST\n"
            "Welcome back to the show."
        ),
        "created_at": ts,
        "updated_at": ts,
        "metadata": {"seed": True},
    }
    inbox_message = {
        "message_id": _msg_id(),
        "folder_id": "inbox",
        "subject": "Call Time Confirmed",
        "body": (
            "You are booked for rehearsal in Studio A.\n"
            "Check the green room board for the latest call sheet."
        ),
        "sender": "Production Office",
        "recipients": [user_id],
        "created_at": ts,
        "read": False,
        "transport": "local",
    }
    return {
        "version": 1,
        "folders": deepcopy(SYSTEM_FOLDERS),
        "documents": [welcome_doc, script_doc],
        "messages": [inbox_message],
        "provider": {
            "mode": "local",
            "configured": False,
            "status": "placeholder",
            "note": "Local store active. External providers can be added later.",
        },
    }


def load_state(data_dir: Path, user_id: str) -> Dict[str, Any]:
    path = _state_path(data_dir, user_id)
    if not path.exists():
        state = _seed_state(user_id)
        write_json(path, state)
        return state

    state = read_json(path)
    if not state:
        state = _seed_state(user_id)
        write_json(path, state)
        return state

    changed = False
    state.setdefault("version", 1)
    state.setdefault("folders", deepcopy(SYSTEM_FOLDERS))
    state.setdefault("documents", [])
    state.setdefault("messages", [])
    state.setdefault(
        "provider",
        {
            "mode": "local",
            "configured": False,
            "status": "placeholder",
            "note": "Local store active. External providers can be added later.",
        },
    )

    existing_ids = {folder["folder_id"] for folder in state["folders"]}
    for folder in SYSTEM_FOLDERS:
        if folder["folder_id"] not in existing_ids:
            state["folders"].append(deepcopy(folder))
            changed = True

    if changed:
        write_json(path, state)
    return state


def save_state(data_dir: Path, user_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    path = _state_path(data_dir, user_id)
    write_json(path, state)
    return state


def create_folder(data_dir: Path, user_id: str, name: str, kind: str = "document") -> Dict[str, Any]:
    state = load_state(data_dir, user_id)
    folder = {
        "folder_id": f"fld_{uuid.uuid4().hex[:10]}",
        "name": name.strip() or "Untitled Folder",
        "kind": kind if kind in {"document", "message"} else "document",
        "system": False,
    }
    state["folders"].append(folder)
    save_state(data_dir, user_id, state)
    return folder


def list_documents(data_dir: Path, user_id: str) -> List[Dict[str, Any]]:
    state = load_state(data_dir, user_id)
    docs = state.get("documents", [])
    return sorted(docs, key=lambda item: item.get("updated_at", 0), reverse=True)


def get_document(data_dir: Path, user_id: str, doc_id: str) -> Dict[str, Any]:
    state = load_state(data_dir, user_id)
    for doc in state.get("documents", []):
        if doc.get("doc_id") == doc_id:
            return doc
    raise KeyError(doc_id)


def upsert_document(data_dir: Path, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    state = load_state(data_dir, user_id)
    docs = state["documents"]
    now = _now()
    doc_id = str(payload.get("doc_id") or _doc_id())

    for doc in docs:
        if doc.get("doc_id") == doc_id:
            doc.update(
                {
                    "title": str(payload.get("title") or doc.get("title") or "Untitled"),
                    "folder_id": str(payload.get("folder_id") or doc.get("folder_id") or "drafts"),
                    "doc_type": str(payload.get("doc_type") or doc.get("doc_type") or "creative"),
                    "content": str(payload.get("content") or ""),
                    "updated_at": now,
                    "metadata": {**doc.get("metadata", {}), **dict(payload.get("metadata") or {})},
                }
            )
            save_state(data_dir, user_id, state)
            return doc

    doc = {
        "doc_id": doc_id,
        "title": str(payload.get("title") or "Untitled"),
        "folder_id": str(payload.get("folder_id") or "drafts"),
        "doc_type": str(payload.get("doc_type") or "creative"),
        "content": str(payload.get("content") or ""),
        "created_at": now,
        "updated_at": now,
        "metadata": dict(payload.get("metadata") or {}),
    }
    docs.append(doc)
    save_state(data_dir, user_id, state)
    return doc


def import_document(data_dir: Path, user_id: str, filename: str, content: str) -> Dict[str, Any]:
    title = Path(filename).stem or "Imported Document"
    return upsert_document(
        data_dir,
        user_id,
        {
            "title": title,
            "folder_id": "drafts",
            "doc_type": "creative",
            "content": content,
            "metadata": {"imported_from": filename},
        },
    )


def export_document(data_dir: Path, user_id: str, doc_id: str) -> Dict[str, Any]:
    doc = get_document(data_dir, user_id, doc_id)
    safe_title = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in doc["title"]).strip("_") or "document"
    return {
        "filename": f"{safe_title}.txt",
        "content": doc.get("content", ""),
        "title": doc.get("title", "Untitled"),
    }


def list_messages(data_dir: Path, user_id: str) -> List[Dict[str, Any]]:
    state = load_state(data_dir, user_id)
    msgs = state.get("messages", [])
    return sorted(msgs, key=lambda item: item.get("created_at", 0), reverse=True)


def send_message(data_dir: Path, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    state = load_state(data_dir, user_id)
    now = _now()
    outgoing = {
        "message_id": _msg_id(),
        "folder_id": "sent",
        "subject": str(payload.get("subject") or "(No Subject)"),
        "body": str(payload.get("body") or ""),
        "sender": str(payload.get("sender") or "You"),
        "recipients": list(payload.get("recipients") or ["Production Office"]),
        "created_at": now,
        "read": True,
        "transport": "local",
    }
    ack = {
        "message_id": _msg_id(),
        "folder_id": "inbox",
        "subject": f"Re: {outgoing['subject']}",
        "body": "Message queued in local transport. External delivery provider not configured yet.",
        "sender": "PubCast Mailroom",
        "recipients": [user_id],
        "created_at": now + 0.001,
        "read": False,
        "transport": "local",
    }
    state["messages"].extend([outgoing, ack])
    save_state(data_dir, user_id, state)
    return outgoing

