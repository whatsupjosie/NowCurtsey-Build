"""
Immutable, content-addressed vault store with structural lock enforcement.

Design goal: an AI (or any caller) can always READ a vault entry, and can
always PROPOSE a new version, but can never overwrite or delete an entry
once it is locked. The guarantee is enforced twice, independently:

  1. Application layer  - VaultStore exposes no update-in-place method at
     all for existing rows. The only way to "change" a locked entry is to
     insert a new child row that points back to it as its parent.
  2. Database layer      - a SQLite trigger refuses any UPDATE or DELETE
     against a row whose status is 'locked', regardless of what code path
     tries to issue it. This means even a bug, a bypassed API, or a raw
     SQL statement run by a compromised or malicious process cannot
     mutate a locked entry - the database itself says no.

Every entry is hash-chained to its parent (SHA-256 over content + parent
hash + author + timestamp), so tampering that somehow got past both
layers is still mathematically detectable by re-walking the chain.
"""

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_entries (
    id           TEXT PRIMARY KEY,
    parent_id    TEXT,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    author_type  TEXT NOT NULL CHECK (author_type IN ('human', 'ai')),
    author_id    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'locked')),
    created_at   REAL NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES vault_entries(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id   TEXT,
    action     TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id   TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    detail     TEXT,
    at         REAL NOT NULL
);

-- Layer 2 enforcement: the database itself refuses to touch a locked row,
-- independent of whatever the Python layer above it does or doesn't check.
CREATE TRIGGER IF NOT EXISTS block_locked_update
BEFORE UPDATE ON vault_entries
FOR EACH ROW WHEN OLD.status = 'locked'
BEGIN
    SELECT RAISE(ABORT, 'locked vault entry is immutable: propose a new version instead');
END;

CREATE TRIGGER IF NOT EXISTS block_locked_delete
BEFORE DELETE ON vault_entries
FOR EACH ROW WHEN OLD.status = 'locked'
BEGIN
    SELECT RAISE(ABORT, 'locked vault entry cannot be deleted');
END;
"""


class LockedEntryError(Exception):
    """Raised when any caller — human or AI — tries to mutate a locked entry."""


@dataclass
class VaultEntry:
    id: str
    parent_id: Optional[str]
    content: str
    content_hash: str
    author_type: str
    author_id: str
    status: str
    created_at: float


def _hash(content: str, parent_hash: str, author_id: str, created_at: float) -> str:
    payload = f"{parent_hash}|{author_id}|{created_at}|{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class VaultStore:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- reads: always allowed, for anyone ----

    def read(self, entry_id: str) -> VaultEntry:
        row = self.conn.execute(
            "SELECT * FROM vault_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no vault entry {entry_id}")
        return VaultEntry(**dict(row))

    # ---- the ONLY write path: insert a new version ----
    # There is deliberately no update() or edit() method. Changing a
    # locked entry's content is structurally impossible through this
    # class because no method exists to do it — you can only create a
    # new child entry that references it.

    def propose_version(
        self,
        content: str,
        author_type: str,
        author_id: str,
        parent_id: Optional[str] = None,
    ) -> VaultEntry:
        if author_type not in ("human", "ai"):
            raise ValueError("author_type must be 'human' or 'ai'")

        parent_hash = ""
        if parent_id is not None:
            parent = self.read(parent_id)  # reads always work, locked or not
            parent_hash = parent.content_hash

        entry_id = str(uuid.uuid4())
        created_at = time.time()
        content_hash = _hash(content, parent_hash, author_id, created_at)

        self.conn.execute(
            "INSERT INTO vault_entries "
            "(id, parent_id, content, content_hash, author_type, author_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
            (entry_id, parent_id, content, content_hash, author_type, author_id, created_at),
        )
        self._log(entry_id, "propose_version", author_type, author_id, "ok")
        self.conn.commit()
        return self.read(entry_id)

    # ---- locking: human-only, one-way ----

    def lock(self, entry_id: str, actor_type: str, actor_id: str) -> None:
        if actor_type != "human":
            self._log(entry_id, "lock", actor_type, actor_id, "rejected: ai cannot lock")
            self.conn.commit()
            raise PermissionError("only a human actor may lock a vault entry")
        self.conn.execute(
            "UPDATE vault_entries SET status = 'locked' WHERE id = ? AND status = 'draft'",
            (entry_id,),
        )
        self._log(entry_id, "lock", actor_type, actor_id, "ok")
        self.conn.commit()

    # ---- for demonstration only: bypasses the application layer entirely,
    # to prove the DATABASE trigger (not just the Python API) is what
    # actually stops mutation of a locked entry ----

    def _dangerous_raw_overwrite(self, entry_id: str, new_content: str) -> None:
        try:
            self.conn.execute(
                "UPDATE vault_entries SET content = ? WHERE id = ?",
                (new_content, entry_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            self._log(entry_id, "raw_overwrite_attempt", "unknown", "unknown", f"blocked: {e}")
            self.conn.commit()
            raise LockedEntryError(str(e)) from e

    # ---- tamper detection: recompute the chain independently ----

    def verify_chain(self, entry_id: str) -> bool:
        entry = self.read(entry_id)
        parent_hash = ""
        if entry.parent_id is not None:
            parent = self.read(entry.parent_id)
            parent_hash = parent.content_hash
            if not self.verify_chain(entry.parent_id):
                return False
        expected = _hash(entry.content, parent_hash, entry.author_id, entry.created_at)
        return expected == entry.content_hash

    def _log(self, entry_id, action, actor_type, actor_id, outcome, detail=""):
        self.conn.execute(
            "INSERT INTO audit_log (entry_id, action, actor_type, actor_id, outcome, detail, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, action, actor_type, actor_id, outcome, detail, time.time()),
        )


if __name__ == "__main__":
    vault = VaultStore()

    genesis = vault.propose_version(
        content="Draft 1: the opening scene as originally written.",
        author_type="human",
        author_id="curtsey",
    )
    print("genesis:", genesis.id[:8], "status:", genesis.status)

    read_back = vault.read(genesis.id)
    assert read_back.content == genesis.content
    print("AI read genesis content OK")

    vault.lock(genesis.id, actor_type="human", actor_id="curtsey")
    print("genesis locked:", vault.read(genesis.id).status)

    ai_child = vault.propose_version(
        content="Draft 1, AI-suggested rewrite of the opening scene.",
        author_type="ai",
        author_id="pubpartner-writer",
        parent_id=genesis.id,
    )
    print("AI child entry:", ai_child.id[:8], "parent:", ai_child.parent_id[:8])
    print("original genesis untouched:", vault.read(genesis.id).content)

    try:
        vault._dangerous_raw_overwrite(genesis.id, "SILENTLY REPLACED CONTENT")
        print("!! THIS SHOULD NEVER PRINT — locked row was overwritten !!")
    except LockedEntryError as e:
        print("raw overwrite correctly blocked by DB trigger:", e)

    print("chain valid:", vault.verify_chain(ai_child.id))

    try:
        vault.lock(ai_child.id, actor_type="ai", actor_id="pubpartner-writer")
    except PermissionError as e:
        print("AI lock attempt correctly rejected:", e)
