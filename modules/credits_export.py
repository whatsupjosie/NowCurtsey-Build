from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


ROLE_ORDER = [
    'creator', 'writer_of_record', 'director', 'producer', 'original_host',
    'cast', 'actor', 'performer', 'technical_director', 'builder', 'crew', 'observer'
]


def _autosave_dir(data_dir: Path, slug: str) -> Path:
    return Path(data_dir) / 'projects' / slug / 'autosaves'


def _iter_save_docs(data_dir: Path, slug: str):
    path = _autosave_dir(data_dir, slug)
    if not path.exists():
        return
    for file in sorted(path.glob('*.json')):
        try:
            yield json.loads(file.read_text(encoding='utf-8'))
        except Exception:
            continue


def _add_line(target: Dict[str, set], role: str, name: str):
    if role and name:
        target[role].add(name)


def generate_credits(data_dir: Path, slug: str, *, mode: str = 'industry_standard') -> Dict[str, Any]:
    lines: Dict[str, set] = defaultdict(set)
    apparent: Dict[str, set] = defaultdict(set)
    project_identity: Dict[str, Any] = {}
    sessions: List[Dict[str, Any]] = []

    for doc in _iter_save_docs(data_dir, slug) or []:
        project_identity = doc.get('project_identity') or project_identity
        project_credits = doc.get('project_credits') or {}
        session_credits = doc.get('session_credits') or {}
        sessions.append({
            'session_id': session_credits.get('session_id'),
            'participant_count': len(session_credits.get('participants', [])),
        })

        for role, people in project_credits.items():
            if isinstance(people, list):
                for p in people:
                    if isinstance(p, dict):
                        _add_line(lines, role, p.get('credit_name') or p.get('display_name') or p.get('user_id'))
                    elif isinstance(p, str):
                        _add_line(lines, role, p)

        for p in session_credits.get('participants', []):
            if not p.get('creditable', True):
                continue
            display = p.get('credit_name') or p.get('display_name') or p.get('user_id')
            for role in p.get('project_role', []) or []:
                _add_line(lines, role, display)
                apparent[display].add(role)
            for role in p.get('session_role', []) or []:
                _add_line(lines, role, display)
                apparent[display].add(role)

    ordered_roles = [r for r in ROLE_ORDER if r in lines] + [r for r in sorted(lines) if r not in ROLE_ORDER]
    credits = [{'role': role, 'names': sorted(lines[role])} for role in ordered_roles]

    public_hash = [
        {'name': name, 'roles': sorted(roles)}
        for name, roles in sorted(apparent.items(), key=lambda x: x[0].lower())
    ]

    return {
        'mode': mode,
        'project_identity': project_identity,
        'credits': credits,
        'public_hash': public_hash,
        'session_count': len(sessions),
        'sessions': sessions,
    }



def render_credit_crawl(data: Dict[str, Any]) -> str:
    title = (data.get('project_identity') or {}).get('canonical_title') or 'Untitled Project'
    lines = [title, '', 'CREDITS', '']
    for block in data.get('credits', []):
        lines.append(block.get('role', '').replace('_', ' ').title())
        for name in block.get('names', []):
            lines.append(name)
        lines.append('')
    return "\n".join(lines).strip() + "\n"
