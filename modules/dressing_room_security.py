from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .persistence import append_jsonl, read_json, write_json

CODE_HASH_ITERATIONS = 120_000
STATUS_UNLOCKED = 'unlocked'
STATUS_CODE_REQUIRED = 'code_required'
STATUS_LOCKED_OUT = 'locked_out'


def _safe(value: str) -> str:
    cleaned = ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(value or 'anon'))
    return cleaned[:80] or 'anon'


def _utc_ts() -> float:
    return time.time()


def _security_root(data_dir: Path) -> Path:
    p = Path(data_dir) / 'dressing_room_security'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _black_box_path(data_dir: Path) -> Path:
    p = Path(data_dir) / 'black_box'
    p.mkdir(parents=True, exist_ok=True)
    return p / 'dressing_room_access.jsonl'


def _manifest_root(data_dir: Path) -> Path:
    p = Path(data_dir) / 'dressing_room_forensics'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _project_overlay_path(data_dir: Path, user_id: str, project_id: str) -> Path:
    p = Path(data_dir) / 'projects' / _safe(project_id) / 'dressing_overlays'
    p.mkdir(parents=True, exist_ok=True)
    return p / f'{_safe(user_id)}.json'


def _portable_profile_path(data_dir: Path, user_id: str) -> Path:
    p = Path(data_dir) / 'pub_profiles'
    p.mkdir(parents=True, exist_ok=True)
    return p / f'{_safe(user_id)}.json'


@dataclass
class SecurityState:
    user_id: str
    lock_enabled: bool = False
    code_salt: str = ''
    code_hash: str = ''
    failed_attempts: int = 0
    first_failure_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    flagged: bool = False
    threat_level: str = 'normal'
    locked_until: Optional[float] = None
    black_box_incident_id: Optional[str] = None
    owner_review_required: bool = False
    host_intervention_required: bool = False
    unlocked_session_ids: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'user_id': self.user_id,
            'lock_enabled': self.lock_enabled,
            'code_salt': self.code_salt,
            'code_hash': self.code_hash,
            'failed_attempts': self.failed_attempts,
            'first_failure_at': self.first_failure_at,
            'last_failure_at': self.last_failure_at,
            'flagged': self.flagged,
            'threat_level': self.threat_level,
            'locked_until': self.locked_until,
            'black_box_incident_id': self.black_box_incident_id,
            'owner_review_required': self.owner_review_required,
            'host_intervention_required': self.host_intervention_required,
            'unlocked_session_ids': list(self.unlocked_session_ids or []),
        }


def _state_path(data_dir: Path, user_id: str) -> Path:
    return _security_root(data_dir) / f'{_safe(user_id)}.json'


def load_state(data_dir: Path, user_id: str) -> SecurityState:
    path = _state_path(data_dir, user_id)
    if path.exists():
        try:
            data = read_json(path)
            return SecurityState(
                user_id=user_id,
                lock_enabled=bool(data.get('lock_enabled', False)),
                code_salt=str(data.get('code_salt', '')),
                code_hash=str(data.get('code_hash', '')),
                failed_attempts=int(data.get('failed_attempts', 0)),
                first_failure_at=data.get('first_failure_at'),
                last_failure_at=data.get('last_failure_at'),
                flagged=bool(data.get('flagged', False)),
                threat_level=str(data.get('threat_level', 'normal')),
                locked_until=data.get('locked_until'),
                black_box_incident_id=data.get('black_box_incident_id'),
                owner_review_required=bool(data.get('owner_review_required', False)),
                host_intervention_required=bool(data.get('host_intervention_required', False)),
                unlocked_session_ids=list(data.get('unlocked_session_ids', [])),
            )
        except Exception:
            pass
    return SecurityState(user_id=user_id, unlocked_session_ids=[])


def save_state(data_dir: Path, state: SecurityState) -> SecurityState:
    write_json(_state_path(data_dir, state.user_id), state.to_dict())
    return state


def _validate_code(code: str) -> bool:
    if not isinstance(code, str):
        return False
    if len(code) != 4:
        return False
    if code[0] in '#*' and code[1:].isdigit():
        return True
    if code[-1] in '#*' and code[:-1].isdigit():
        return True
    return False


def _hash_code(code: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', code.encode('utf-8'), bytes.fromhex(salt_hex), CODE_HASH_ITERATIONS).hex()


def set_code(data_dir: Path, user_id: str, code: str) -> Dict[str, Any]:
    if not _validate_code(code):
        raise ValueError('Code must be exactly 4 characters: 3 digits and one # or * at the beginning or end.')
    state = load_state(data_dir, user_id)
    salt_hex = secrets.token_hex(16)
    state.code_salt = salt_hex
    state.code_hash = _hash_code(code, salt_hex)
    state.lock_enabled = True
    state.failed_attempts = 0
    state.first_failure_at = None
    state.last_failure_at = None
    state.flagged = False
    state.threat_level = 'normal'
    state.locked_until = None
    state.owner_review_required = False
    state.host_intervention_required = False
    state.unlocked_session_ids = []
    save_state(data_dir, state)
    return {'ok': True, 'lock_enabled': True}


def disable_code(data_dir: Path, user_id: str, code: str) -> Dict[str, Any]:
    state = load_state(data_dir, user_id)
    if not state.lock_enabled:
        return {'ok': True, 'lock_enabled': False}
    if not verify_code_value(state, code):
        raise PermissionError('Current code required to disable dressing room lock.')
    state.lock_enabled = False
    state.code_hash = ''
    state.code_salt = ''
    state.failed_attempts = 0
    state.first_failure_at = None
    state.last_failure_at = None
    state.flagged = False
    state.threat_level = 'normal'
    state.locked_until = None
    state.owner_review_required = False
    state.host_intervention_required = False
    state.unlocked_session_ids = []
    save_state(data_dir, state)
    return {'ok': True, 'lock_enabled': False}


def verify_code_value(state: SecurityState, code: str) -> bool:
    if not state.lock_enabled:
        return True
    if not _validate_code(code):
        return False
    expected = _hash_code(code, state.code_salt)
    return hmac.compare_digest(expected, state.code_hash)


def _iter_dressing_room_files(data_dir: Path, room_owner_id: str, project_id: str) -> List[Path]:
    candidates = [
        _portable_profile_path(data_dir, room_owner_id),
        Path(data_dir) / 'avatars' / f'{_safe(room_owner_id)}.json',
        _project_overlay_path(data_dir, room_owner_id, project_id),
        _state_path(data_dir, room_owner_id),
    ]
    return [p for p in candidates if p.exists() and p.is_file()]


def build_forensic_manifest(data_dir: Path, room_owner_id: str, project_id: str, *, access_log: Optional[List[str]] = None) -> Dict[str, Any]:
    files = []
    total_size = 0
    for path in _iter_dressing_room_files(data_dir, room_owner_id, project_id):
        raw = path.read_bytes()
        size = len(raw)
        total_size += size
        files.append({
            'path': str(path),
            'size_bytes': size,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'modified_at': path.stat().st_mtime,
        })
    return {
        'room_owner_id': room_owner_id,
        'project_id': project_id,
        'captured_at': _utc_ts(),
        'file_count': len(files),
        'total_size_bytes': total_size,
        'files': files,
        'accessed_files': list(access_log or []),
    }


def _write_manifest(data_dir: Path, incident_id: str, manifest: Dict[str, Any]) -> Path:
    path = _manifest_root(data_dir) / f'{incident_id}.json'
    write_json(path, manifest)
    return path


def _read_manifest(data_dir: Path, incident_id: str) -> Optional[Dict[str, Any]]:
    path = _manifest_root(data_dir) / f'{incident_id}.json'
    if not path.exists():
        return None
    return read_json(path)


def log_black_box_event(data_dir: Path, event: Dict[str, Any]) -> None:
    append_jsonl(_black_box_path(data_dir), event)


def _event_base(*, room_owner_id: str, acting_identity: str, project_id: str, session_id: str, credential_type: str, event_type: str, status: str) -> Dict[str, Any]:
    return {
        'ts': _utc_ts(),
        'event_type': event_type,
        'status': status,
        'room_owner_id': room_owner_id,
        'acting_identity': acting_identity,
        'project_id': project_id,
        'session_id': session_id,
        'credential_type': credential_type,
    }


def attempt_entry(
    data_dir: Path,
    *,
    room_owner_id: str,
    acting_identity: str,
    project_id: str,
    session_id: str,
    credential_type: str,
    code: Optional[str],
    valid_routing: bool,
    access_log: Optional[List[str]] = None,
) -> Dict[str, Any]:
    state = load_state(data_dir, room_owner_id)
    now = _utc_ts()
    if not valid_routing:
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='room_route_denied', status='denied')
        event['reason'] = 'invalid_routing'
        log_black_box_event(data_dir, event)
        return {'ok': False, 'status': 'denied', 'reason': 'invalid_routing'}

    if state.locked_until and now < state.locked_until:
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='lockout_active', status='denied')
        event['locked_until'] = state.locked_until
        log_black_box_event(data_dir, event)
        return {'ok': False, 'status': STATUS_LOCKED_OUT, 'locked_until': state.locked_until, 'owner_review_required': state.owner_review_required, 'host_intervention_required': state.host_intervention_required}

    if not state.lock_enabled:
        if session_id not in state.unlocked_session_ids:
            state.unlocked_session_ids.append(session_id)
            save_state(data_dir, state)
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='room_route_success', status='ok')
        event['lock_enabled'] = False
        log_black_box_event(data_dir, event)
        return {'ok': True, 'status': STATUS_UNLOCKED, 'lock_enabled': False}

    if session_id in (state.unlocked_session_ids or []):
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='room_route_success', status='ok')
        event['lock_enabled'] = True
        event['unlock_cached'] = True
        log_black_box_event(data_dir, event)
        return {'ok': True, 'status': STATUS_UNLOCKED, 'lock_enabled': True, 'unlock_cached': True}

    if code is None:
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='lock_prompt_presented', status='challenge')
        log_black_box_event(data_dir, event)
        return {'ok': False, 'status': STATUS_CODE_REQUIRED, 'lock_enabled': True, 'flagged': state.flagged, 'threat_level': state.threat_level}

    if verify_code_value(state, code):
        state.failed_attempts = 0
        state.first_failure_at = None
        state.last_failure_at = None
        state.flagged = False if state.threat_level == 'normal' else state.flagged
        if session_id not in state.unlocked_session_ids:
            state.unlocked_session_ids.append(session_id)
        save_state(data_dir, state)
        event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='lock_code_success', status='ok')
        log_black_box_event(data_dir, event)
        return {'ok': True, 'status': STATUS_UNLOCKED, 'lock_enabled': True}

    state.failed_attempts += 1
    state.last_failure_at = now
    state.first_failure_at = state.first_failure_at or now
    if state.failed_attempts >= 1:
        state.flagged = True
    if state.failed_attempts >= 3:
        state.threat_level = 'elevated'
        state.owner_review_required = True
        state.host_intervention_required = True
        state.locked_until = now + 300
        if not state.black_box_incident_id:
            state.black_box_incident_id = secrets.token_hex(10)
        manifest = build_forensic_manifest(data_dir, room_owner_id, project_id, access_log=access_log)
        manifest['incident_id'] = state.black_box_incident_id
        manifest['private_to_owner'] = True
        manifest['sealed'] = True
        _write_manifest(data_dir, state.black_box_incident_id, manifest)
    save_state(data_dir, state)

    event = _event_base(room_owner_id=room_owner_id, acting_identity=acting_identity, project_id=project_id, session_id=session_id, credential_type=credential_type, event_type='lock_code_failure', status='denied')
    event.update({
        'failed_attempts': state.failed_attempts,
        'flagged': state.flagged,
        'threat_level': state.threat_level,
        'owner_review_required': state.owner_review_required,
        'host_intervention_required': state.host_intervention_required,
        'incident_id': state.black_box_incident_id,
    })
    log_black_box_event(data_dir, event)
    return {
        'ok': False,
        'status': 'incorrect_code',
        'failed_attempts': state.failed_attempts,
        'flagged': state.flagged,
        'threat_level': state.threat_level,
        'owner_review_required': state.owner_review_required,
        'host_intervention_required': state.host_intervention_required,
        'incident_id': state.black_box_incident_id,
        'locked_until': state.locked_until,
    }


def get_status(data_dir: Path, room_owner_id: str, session_id: str) -> Dict[str, Any]:
    state = load_state(data_dir, room_owner_id)
    locked = bool(state.lock_enabled and session_id not in (state.unlocked_session_ids or []))
    return {
        'lock_enabled': state.lock_enabled,
        'code_required': locked,
        'flagged': state.flagged,
        'threat_level': state.threat_level,
        'owner_review_required': state.owner_review_required,
        'host_intervention_required': state.host_intervention_required,
        'locked_until': state.locked_until,
        'incident_id': state.black_box_incident_id,
    }


def compare_manifest_to_current(data_dir: Path, room_owner_id: str, project_id: str, incident_id: str) -> Dict[str, Any]:
    baseline = _read_manifest(data_dir, incident_id)
    if not baseline:
        raise FileNotFoundError('No forensic baseline found for this incident.')
    current = build_forensic_manifest(data_dir, room_owner_id, project_id)
    before = {item['path']: item for item in baseline.get('files', [])}
    after = {item['path']: item for item in current.get('files', [])}
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = []
    accessed = []
    for path in sorted(set(before) & set(after)):
        if before[path]['sha256'] != after[path]['sha256']:
            modified.append(path)
        if before[path].get('modified_at') != after[path].get('modified_at'):
            accessed.append(path)
    return {
        'incident_id': incident_id,
        'room_owner_id': room_owner_id,
        'project_id': project_id,
        'baseline': {
            'file_count': baseline.get('file_count', 0),
            'total_size_bytes': baseline.get('total_size_bytes', 0),
            'captured_at': baseline.get('captured_at'),
            'accessed_files': baseline.get('accessed_files', []),
        },
        'current': {
            'file_count': current.get('file_count', 0),
            'total_size_bytes': current.get('total_size_bytes', 0),
            'captured_at': current.get('captured_at'),
        },
        'tamper_suspected': bool(added or deleted or modified),
        'added_files': added,
        'deleted_files': deleted,
        'modified_files': modified,
        'accessed_files': sorted(set(accessed) | set(baseline.get('accessed_files', []))),
    }
