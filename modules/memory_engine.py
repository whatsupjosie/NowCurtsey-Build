from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _db_path(data_dir: Path) -> Path:
    p = Path(data_dir) / 'memory'
    p.mkdir(parents=True, exist_ok=True)
    return p / 'pubcast_memory.db'


def _conn(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(data_dir)), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: Path) -> None:
    conn = _conn(data_dir)
    try:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS memory_events (
            event_id TEXT PRIMARY KEY,
            ts REAL NOT NULL,
            session_id TEXT,
            project_id TEXT,
            user_id TEXT,
            room_id TEXT,
            feature_id TEXT,
            event_type TEXT,
            speaking_style TEXT,
            mood_trace TEXT,
            summary TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_room ON memory_events(project_id, room_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_events(user_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_events(session_id, ts DESC);
        ''')
        conn.commit()
    finally:
        conn.close()


def record_event(
    data_dir: Path,
    *,
    session_id: str,
    project_id: str,
    user_id: str,
    room_id: str,
    feature_id: str = '',
    event_type: str,
    summary: str,
    speaking_style: str = '',
    mood_trace: str = '',
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    init_db(data_dir)
    event = {
        'event_id': uuid.uuid4().hex[:16],
        'ts': time.time(),
        'session_id': session_id,
        'project_id': project_id,
        'user_id': user_id,
        'room_id': room_id,
        'feature_id': feature_id,
        'event_type': event_type,
        'speaking_style': speaking_style,
        'mood_trace': mood_trace,
        'summary': summary,
        'payload': payload or {},
    }
    conn = _conn(data_dir)
    try:
        conn.execute(
            'INSERT INTO memory_events (event_id, ts, session_id, project_id, user_id, room_id, feature_id, event_type, speaking_style, mood_trace, summary, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                event['event_id'], event['ts'], event['session_id'], event['project_id'], event['user_id'], event['room_id'], event['feature_id'],
                event['event_type'], event['speaking_style'], event['mood_trace'], event['summary'], json.dumps(event['payload'], ensure_ascii=False),
            )
        )
        conn.commit()
    finally:
        conn.close()
    return event


def recent_for_room(data_dir: Path, *, project_id: str, room_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    init_db(data_dir)
    conn = _conn(data_dir)
    try:
        rows = conn.execute(
            'SELECT * FROM memory_events WHERE project_id=? AND room_id=? ORDER BY ts DESC LIMIT ?',
            (project_id, room_id, limit),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def recent_for_user(data_dir: Path, *, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    init_db(data_dir)
    conn = _conn(data_dir)
    try:
        rows = conn.execute('SELECT * FROM memory_events WHERE user_id=? ORDER BY ts DESC LIMIT ?', (user_id, limit)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def context_summary(data_dir: Path, *, session_id: str, project_id: str, user_id: str, room_id: str) -> Dict[str, Any]:
    room_events = recent_for_room(data_dir, project_id=project_id, room_id=room_id, limit=8)
    user_events = recent_for_user(data_dir, user_id=user_id, limit=8)
    motifs = []
    seen = set()
    for ev in room_events + user_events:
        for key in (ev.get('mood_trace'), ev.get('speaking_style'), ev.get('event_type')):
            if key and key not in seen:
                motifs.append(key)
                seen.add(key)
    return {
        'session_id': session_id,
        'project_id': project_id,
        'user_id': user_id,
        'room_id': room_id,
        'recent_room_events': room_events,
        'recent_user_events': user_events,
        'motifs': motifs[:12],
    }


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d['payload'] = json.loads(d.pop('payload_json') or '{}')
    return d
