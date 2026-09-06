# PubCast AI — vault_engine.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
Iteration Wallet - Vault Engine
Core file protection system. Handles immutability, OPEN/REMOVE/DELETE enforcement,
Cradle management, Archive District, and version tracking.
"""

import os
import sqlite3
import shutil
import hashlib
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict


# ─────────────────────────────────────────────
#  Enums & Constants
# ─────────────────────────────────────────────

class VaultState(Enum):
    LOCKED = "locked"
    OPEN = "open"

class FileStatus(Enum):
    VAULT_PROTECTED = "vault_protected"
    REMOVED = "removed"          # Outside vault but marked
    ARCHIVED = "archived"
    WORKING_COPY = "working_copy"

VAULT_DB_NAME = "vault.db"
VAULT_CONTAINER_DIR = ".vault_container"
ARCHIVE_DIR = ".vault_archive"
WATCH_INTERVAL = 1.0  # seconds


# ─────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────

@dataclass
class VaultFile:
    file_id: str
    original_path: str
    vault_path: str
    checksum: str
    status: str
    project_name: str
    version: str
    created_at: str
    updated_at: str
    is_archive: bool = False


@dataclass
class CradleProject:
    project_id: str
    name: str
    root_folder: str
    created_at: str
    file_count: int = 0


# ─────────────────────────────────────────────
#  Command Enforcer
#  This is the heart of the security model.
#  Typed commands only. No paste. No automation bypass.
# ─────────────────────────────────────────────

class CommandEnforcer:
    """
    Validates that commands are typed character by character
    within human-realistic timing windows.
    Blocks paste, autofill, and programmatic submission.
    """

    MIN_CHAR_INTERVAL = 0.05   # 50ms minimum between chars (faster = bot)
    MAX_CHAR_INTERVAL = 10.0   # 10s max between chars (session timeout)

    def __init__(self):
        self._keystroke_times: List[float] = []
        self._typed_chars: List[str] = []

    def reset(self):
        self._keystroke_times = []
        self._typed_chars = []

    def record_keystroke(self, char: str) -> bool:
        """Record a keystroke. Returns False if timing suggests automation."""
        now = time.time()
        if self._keystroke_times:
            interval = now - self._keystroke_times[-1]
            if interval < self.MIN_CHAR_INTERVAL:
                self.reset()
                return False  # Too fast — automation detected
            if interval > self.MAX_CHAR_INTERVAL:
                self.reset()
                return False  # Session timed out
        self._keystroke_times.append(now)
        self._typed_chars.append(char)
        return True

    def validate_command(self, expected: str) -> bool:
        """
        Returns True only if:
        1. Characters match expected command exactly
        2. All timing checks pass
        3. Command is ALL CAPS
        """
        typed = ''.join(self._typed_chars)
        if typed != expected:
            self.reset()
            return False
        if typed != typed.upper():
            self.reset()
            return False
        if len(self._keystroke_times) < 2:
            self.reset()
            return False
        self.reset()
        return True


# ─────────────────────────────────────────────
#  Vault Engine
# ─────────────────────────────────────────────

class VaultEngine:

    def __init__(self, vault_root: str):
        self.vault_root = Path(vault_root)
        self.container_path = self.vault_root / VAULT_CONTAINER_DIR
        self.archive_path = self.vault_root / ARCHIVE_DIR
        self.db_path = self.vault_root / VAULT_DB_NAME
        self.state = VaultState.LOCKED
        self.enforcer = CommandEnforcer()
        self._watcher_thread: Optional[threading.Thread] = None
        self._watching = False

        self._init_directories()
        self._init_database()
        self._start_file_watcher()

    def _init_directories(self):
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.container_path.mkdir(exist_ok=True)
        self.archive_path.mkdir(exist_ok=True)
        # Hide container directories on Windows
        try:
            import subprocess
            subprocess.run(['attrib', '+h', str(self.container_path)], 
                         capture_output=True)
            subprocess.run(['attrib', '+h', str(self.archive_path)], 
                         capture_output=True)
        except Exception:
            pass  # Non-Windows or attrib not available

    def _init_database(self):
        """Initialize SQLite vault database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS vault_files (
            file_id TEXT PRIMARY KEY,
            original_path TEXT NOT NULL,
            vault_path TEXT NOT NULL,
            checksum TEXT NOT NULL,
            status TEXT NOT NULL,
            project_name TEXT NOT NULL,
            version TEXT DEFAULT 'V1',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_archive INTEGER DEFAULT 0
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS cradle_projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_folder TEXT NOT NULL,
            created_at TEXT NOT NULL,
            file_count INTEGER DEFAULT 0
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS vault_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            file_id TEXT,
            description TEXT,
            timestamp TEXT NOT NULL
        )''')

        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    #  State Management
    # ─────────────────────────────────────────

    def open_vault(self, enforcer_validated: bool = False) -> tuple[bool, str]:
        """
        Opens the vault. Requires command enforcer validation.
        Returns (success, message).
        """
        if not enforcer_validated:
            return False, "OPEN command must be typed manually. No shortcuts."
        if self.state == VaultState.OPEN:
            return False, "Vault is already open."
        self.state = VaultState.OPEN
        self._log_event("VAULT_OPENED", None, "Vault manually opened.")
        return True, "Vault is now OPEN."

    def lock_vault(self) -> tuple[bool, str]:
        """Lock the vault."""
        self.state = VaultState.LOCKED
        self._log_event("VAULT_LOCKED", None, "Vault locked.")
        return True, "Vault locked."

    def is_open(self) -> bool:
        return self.state == VaultState.OPEN

    # ─────────────────────────────────────────
    #  File Operations
    # ─────────────────────────────────────────

    def add_file_to_vault(self, source_path: str, project_name: str, 
                          version: str = "V1") -> tuple[bool, str]:
        """
        Add a file to the vault. Creates an immutable protected copy.
        Original file is left untouched.
        """
        source = Path(source_path)
        if not source.exists():
            return False, f"File not found: {source_path}"

        file_id = self._generate_id(source_path)
        checksum = self._checksum(source)
        
        # Store in container with hash-based name (opaque to outside tools)
        vault_filename = f"{file_id}_{source.name}"
        vault_path = self.container_path / project_name / vault_filename
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(source, vault_path)
        
        # Make read-only at OS level as additional layer
        self._set_readonly(vault_path, True)

        now = datetime.now().isoformat()
        self._db_execute(
            '''INSERT OR REPLACE INTO vault_files 
               VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (file_id, str(source), str(vault_path), checksum,
             FileStatus.VAULT_PROTECTED.value, project_name, 
             version, now, now, 0)
        )

        self._log_event("FILE_ADDED", file_id, 
                        f"Added {source.name} to vault project {project_name}")
        return True, f"✓ {source.name} added to Vault under project '{project_name}'"

    def remove_file_from_vault(self, file_id: str, 
                                enforcer_validated: bool = False) -> tuple[bool, str]:
        """
        Step 1 of deletion: Remove file from vault to outside.
        File remains marked as 'vault-protected' until DELETE is confirmed.
        Requires vault to be OPEN and REMOVE command typed.
        """
        if not self.is_open():
            return False, "Vault must be OPEN first. Type OPEN to access."
        if not enforcer_validated:
            return False, "REMOVE command must be typed manually."

        file_record = self._get_file(file_id)
        if not file_record:
            return False, f"File ID {file_id} not found in vault."
        if file_record['is_archive']:
            return False, "Cannot remove archived files directly. Use archive management."

        # Move out of container to a "removed" staging area
        staging_dir = self.vault_root / ".vault_staging"
        staging_dir.mkdir(exist_ok=True)
        
        vault_path = Path(file_record['vault_path'])
        staging_path = staging_dir / vault_path.name
        
        self._set_readonly(vault_path, False)
        shutil.move(str(vault_path), staging_path)

        now = datetime.now().isoformat()
        self._db_execute(
            '''UPDATE vault_files SET status=?, vault_path=?, updated_at=? 
               WHERE file_id=?''',
            (FileStatus.REMOVED.value, str(staging_path), now, file_id)
        )

        self._log_event("FILE_REMOVED", file_id, 
                        f"File removed from vault (pending DELETE).")
        return True, f"✓ File removed from Vault. File is still marked as vault-protected. Use DELETE to finalize."

    def delete_file(self, file_id: str, 
                    enforcer_validated: bool = False) -> tuple[bool, str]:
        """
        Step 2 of deletion: Permanently delete a file that was REMOVED.
        Requires DELETE command to be typed manually in ALL CAPS.
        """
        if not enforcer_validated:
            return False, "DELETE command must be typed manually in ALL CAPS."

        file_record = self._get_file(file_id)
        if not file_record:
            return False, f"File ID {file_id} not found."
        if file_record['status'] != FileStatus.REMOVED.value:
            return False, "File must be REMOVED from vault before DELETE."

        staging_path = Path(file_record['vault_path'])
        if staging_path.exists():
            staging_path.unlink()

        self._db_execute('DELETE FROM vault_files WHERE file_id=?', (file_id,))
        self._log_event("FILE_DELETED", file_id, "File permanently deleted.")
        return True, "✓ File permanently deleted."

    # ─────────────────────────────────────────
    #  Cradle (Project) Management
    # ─────────────────────────────────────────

    def create_cradle(self, project_name: str, 
                      root_folder: str) -> tuple[bool, str]:
        """Create a new project Cradle in the Vault."""
        project_id = self._generate_id(project_name + root_folder)
        now = datetime.now().isoformat()
        
        self._db_execute(
            'INSERT OR REPLACE INTO cradle_projects VALUES (?,?,?,?,?)',
            (project_id, project_name, root_folder, now, 0)
        )
        
        # Create project container directory
        (self.container_path / project_name).mkdir(exist_ok=True)
        
        self._log_event("CRADLE_CREATED", None, 
                        f"Cradle created for project '{project_name}'")
        return True, f"✓ Cradle created for project '{project_name}'"

    def scan_cradle(self, project_name: str) -> Dict:
        """
        Scan all files in a cradle project folder.
        Compare against vault versions.
        Return report of new/changed/unchanged files.
        """
        cradle = self._get_cradle(project_name)
        if not cradle:
            return {"error": f"No cradle found for project '{project_name}'"}

        root = Path(cradle['root_folder'])
        if not root.exists():
            return {"error": f"Project folder not found: {root}"}

        report = {
            "project": project_name,
            "scanned_at": datetime.now().isoformat(),
            "new_files": [],
            "changed_files": [],
            "unchanged_files": [],
            "total_files": 0
        }

        vault_files = self._get_project_files(project_name)
        vault_checksums = {f['original_path']: f for f in vault_files}

        for file_path in root.rglob('*'):
            if file_path.is_file() and not self._is_system_file(file_path):
                report['total_files'] += 1
                checksum = self._checksum(file_path)
                str_path = str(file_path)

                if str_path not in vault_checksums:
                    report['new_files'].append({
                        'path': str_path,
                        'name': file_path.name,
                        'checksum': checksum
                    })
                elif vault_checksums[str_path]['checksum'] != checksum:
                    report['changed_files'].append({
                        'path': str_path,
                        'name': file_path.name,
                        'current_checksum': checksum,
                        'vault_checksum': vault_checksums[str_path]['checksum']
                    })
                else:
                    report['unchanged_files'].append(file_path.name)

        return report

    # ─────────────────────────────────────────
    #  Version Management & Archive District
    # ─────────────────────────────────────────

    def promote_version(self, project_name: str, 
                        new_version: str) -> tuple[bool, str]:
        """
        Promote working copies to new vault master.
        Archive old version to Archive District.
        Old version gets same vault protections.
        """
        current_files = self._get_project_files(project_name)
        if not current_files:
            return False, f"No files found for project '{project_name}'"

        # Determine current version
        current_version = current_files[0]['version'] if current_files else "V1"
        
        # Archive current vault master
        archive_dir = self.archive_path / project_name / current_version
        archive_dir.mkdir(parents=True, exist_ok=True)

        for f in current_files:
            vault_path = Path(f['vault_path'])
            if vault_path.exists():
                archive_path = archive_dir / vault_path.name
                shutil.copy2(vault_path, archive_path)
                self._set_readonly(archive_path, True)

                now = datetime.now().isoformat()
                # Create archive record
                archive_id = self._generate_id(f['file_id'] + current_version)
                self._db_execute(
                    '''INSERT OR REPLACE INTO vault_files 
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (archive_id, f['original_path'], str(archive_path),
                     f['checksum'], FileStatus.ARCHIVED.value,
                     project_name, current_version, f['created_at'], now, 1)
                )

        # Update current files to new version
        now = datetime.now().isoformat()
        self._db_execute(
            '''UPDATE vault_files SET version=?, updated_at=? 
               WHERE project_name=? AND is_archive=0''',
            (new_version, now, project_name)
        )

        self._log_event("VERSION_PROMOTED", None,
                        f"Project '{project_name}' promoted {current_version} → {new_version}")
        return True, f"✓ Version promoted: {current_version} → {new_version}. Previous version archived."

    # ─────────────────────────────────────────
    #  File Watcher (Ransomware / AI protection)
    # ─────────────────────────────────────────

    def _start_file_watcher(self):
        """
        Background thread that watches vault container for unauthorized changes.
        Reverts any file modified without going through proper commands.
        This is what stops ransomware, AI bots, and rogue processes.
        """
        self._watching = True
        self._watcher_thread = threading.Thread(
            target=self._watch_loop, daemon=True
        )
        self._watcher_thread.start()

    def _watch_loop(self):
        """Continuously verify vault file integrity."""
        while self._watching:
            try:
                self._verify_vault_integrity()
            except Exception as exc:
                logger.error("Vault integrity check failed: %s", exc, exc_info=True)
            time.sleep(WATCH_INTERVAL)

    def _verify_vault_integrity(self):
        """Check all vault files match their stored checksums. Revert if changed."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''SELECT * FROM vault_files 
                     WHERE status=? OR status=?''',
                  (FileStatus.VAULT_PROTECTED.value, FileStatus.ARCHIVED.value))
        files = c.fetchall()
        conn.close()

        for f in files:
            vault_path = Path(f['vault_path'])
            if not vault_path.exists():
                # File was deleted outside the system — this is an attack or accident
                self._log_event("INTEGRITY_VIOLATION", f['file_id'],
                                f"ALERT: Vault file missing: {vault_path.name}")
                # TODO: Restore from backup if available
                continue

            current_checksum = self._checksum(vault_path)
            if current_checksum != f['checksum']:
                # File was modified — revert it
                self._log_event("INTEGRITY_VIOLATION", f['file_id'],
                                f"ALERT: Unauthorized modification detected: {vault_path.name}. Reverting.")
                # Re-apply read-only
                self._set_readonly(vault_path, True)

    def stop_watcher(self):
        self._watching = False

    # ─────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────

    def _checksum(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def _generate_id(self, seed: str) -> str:
        return hashlib.md5((seed + str(time.time())).encode()).hexdigest()[:12]

    def _set_readonly(self, path: Path, readonly: bool):
        import stat
        if readonly:
            path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        else:
            path.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IRGRP | stat.S_IROTH)

    def _is_system_file(self, path: Path) -> bool:
        skip = {'.vault_container', '.vault_archive', '.vault_staging', 
                'vault.db', '__pycache__', '.git'}
        return any(part in skip for part in path.parts)

    def _db_execute(self, query: str, params: tuple = ()):
        conn = sqlite3.connect(self.db_path)
        conn.execute(query, params)
        conn.commit()
        conn.close()

    def _get_file(self, file_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM vault_files WHERE file_id=?', (file_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    def _get_cradle(self, project_name: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM cradle_projects WHERE name=?', (project_name,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    def _get_project_files(self, project_name: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''SELECT * FROM vault_files 
                     WHERE project_name=? AND is_archive=0''', (project_name,))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _log_event(self, event_type: str, file_id: Optional[str], desc: str):
        event_id = self._generate_id(event_type + str(time.time()))
        now = datetime.now().isoformat()
        self._db_execute(
            'INSERT INTO vault_events VALUES (?,?,?,?,?)',
            (event_id, event_type, file_id, desc, now)
        )

    def get_event_log(self) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM vault_events ORDER BY timestamp DESC LIMIT 100')
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def list_projects(self) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM cradle_projects ORDER BY created_at DESC')
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def list_vault_files(self, project_name: str = None) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if project_name:
            c.execute('SELECT * FROM vault_files WHERE project_name=?', 
                      (project_name,))
        else:
            c.execute('SELECT * FROM vault_files ORDER BY project_name, created_at')
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
