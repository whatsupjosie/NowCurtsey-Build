# PubCast AI — userdb.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/userdb.py — Async SQLite-backed user database.

Exports:
    init_db()
    get_user(username: str) -> dict | None
    create_user(username: str, password: str, role: str) -> bool
    create_owner_if_not_exists()
    record_mod_action(room: str, operator: str, action: str, detail: str)
    get_mod_actions(room: str, limit: int) -> list[dict]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .auth import get_password_hash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB location — resolved once at import time, overridable via env
# ---------------------------------------------------------------------------
_DB_PATH: Path = Path(os.environ.get("PUBCAST_DATA_DIR", "data")) / "users.db"

# SQLite is synchronous; we run it in a thread executor to avoid blocking
# the asyncio event loop.
_executor: Optional[asyncio.AbstractEventLoop] = None


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _sync_init_db() -> None:
    """Create tables if they don't exist. Runs synchronously."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_connection()
    try:
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username        TEXT PRIMARY KEY,
                hashed_password TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'guest',
                created_at      REAL NOT NULL DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS mod_actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                room        TEXT NOT NULL,
                operator    TEXT NOT NULL,
                action      TEXT NOT NULL,
                detail      TEXT NOT NULL DEFAULT '',
                ts          REAL NOT NULL DEFAULT (strftime('%s','now'))
            );

            CREATE INDEX IF NOT EXISTS idx_mod_actions_room ON mod_actions(room, ts DESC);
        """)
        conn.commit()
        logger.info("userdb: tables ready at %s", _DB_PATH)
    finally:
        conn.close()


def _sync_get_user(username: str) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT username, hashed_password, role, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _sync_create_user(username: str, password: str, role: str) -> bool:
    """Insert user. Returns False if username already exists."""
    hashed = get_password_hash(password)
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
            (username, hashed, role),
        )
        conn.commit()
        logger.info("userdb: created user '%s' with role '%s'", username, role)
        return True
    except sqlite3.IntegrityError:
        logger.debug("userdb: user '%s' already exists", username)
        return False
    finally:
        conn.close()


def _sync_create_owner_if_not_exists() -> None:
    """
    Create the default owner account if no users exist yet.
    Credentials are pulled from environment variables so they are never
    hard-coded.  Falls back to insecure defaults with a loud warning.
    """
    owner_name = os.environ.get("PUBCAST_OWNER_USERNAME", "owner")
    owner_pass = os.environ.get("PUBCAST_OWNER_PASSWORD", "")

    if not owner_pass:
        logger.warning(
            "PUBCAST_OWNER_PASSWORD is not set. "
            "The owner account will NOT be auto-created. "
            "Set PUBCAST_OWNER_PASSWORD before first run."
        )
        return

    conn = _get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            hashed = get_password_hash(owner_pass)
            conn.execute(
                "INSERT OR IGNORE INTO users (username, hashed_password, role) VALUES (?, ?, 'owner')",
                (owner_name, hashed),
            )
            conn.commit()
            logger.info("userdb: owner account '%s' created", owner_name)
        else:
            logger.debug("userdb: users already exist, skipping owner seed")
    finally:
        conn.close()


def _sync_record_mod_action(room: str, operator: str, action: str, detail: str) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO mod_actions (room, operator, action, detail) VALUES (?, ?, ?, ?)",
            (room, operator, action, detail),
        )
        conn.commit()
    finally:
        conn.close()


def _sync_get_mod_actions(room: str, limit: int) -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT room, operator, action, detail, ts FROM mod_actions "
            "WHERE room = ? ORDER BY ts DESC LIMIT ?",
            (room, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------

async def _in_thread(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


async def init_db() -> None:
    await _in_thread(_sync_init_db)


async def get_user(username: str) -> Optional[Dict[str, Any]]:
    return await _in_thread(_sync_get_user, username)


async def create_user(username: str, password: str, role: str = "guest") -> bool:
    return await _in_thread(_sync_create_user, username, password, role)


async def create_owner_if_not_exists() -> None:
    await _in_thread(_sync_create_owner_if_not_exists)


async def record_mod_action(room: str, operator: str, action: str, detail: str = "") -> None:
    await _in_thread(_sync_record_mod_action, room, operator, action, detail)


async def get_mod_actions(room: str, limit: int = 100) -> List[Dict[str, Any]]:
    return await _in_thread(_sync_get_mod_actions, room, limit)


# ---------------------------------------------------------------------------
# v6 additions — user management (WIRING_COMPLETE)
# ---------------------------------------------------------------------------

def _sync_get_all_users() -> List[Dict[str, Any]]:
    """Return all users sorted by created_at. Owner only."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT username, role, created_at FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _sync_update_user_role(username: str, new_role: str) -> Optional[str]:
    """
    Update a user's role. Returns the previous role, or None if user not found.
    Raises ValueError if the role is not a known role.
    """
    valid_roles = {"guest", "friend", "crew", "security", "mod", "owner"}
    if new_role not in valid_roles:
        raise ValueError(f"Invalid role '{new_role}'. Must be one of: {valid_roles}")
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return None
        old_role = row["role"]
        conn.execute(
            "UPDATE users SET role = ? WHERE username = ?",
            (new_role, username),
        )
        conn.commit()
        logger.info("userdb: role change for '%s': %s → %s", username, old_role, new_role)
        return old_role
    finally:
        conn.close()


def record_mod_action_sync(room: str, operator: str, action: str, detail: str = "") -> None:
    """Synchronous wrapper for record_mod_action — usable outside async context."""
    _sync_record_mod_action(room, operator, action, detail)


# Async wrappers for the new sync functions

async def get_all_users() -> List[Dict[str, Any]]:
    """Return all users. Caller should enforce owner-only access."""
    return await _in_thread(_sync_get_all_users)


async def update_user_role(username: str, new_role: str) -> Optional[str]:
    """
    Update user role. Returns the old role string, or None if user not found.
    Raises ValueError on invalid role.
    """
    return await _in_thread(_sync_update_user_role, username, new_role)
