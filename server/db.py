"""SQLite persistence for API keys, admins, requests, and uploaded voices."""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
DB_PATH = DATA_DIR / "studio.db"
VOICES_UPLOAD_DIR = DATA_DIR / "voices"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
  id            TEXT PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
  id           TEXT PRIMARY KEY,
  prefix       TEXT NOT NULL,
  key_hash     TEXT NOT NULL UNIQUE,
  raw_key      TEXT,
  name         TEXT,
  owner_email  TEXT,
  active       INTEGER NOT NULL DEFAULT 1,
  scopes       TEXT NOT NULL DEFAULT '["speech"]',
  bootstrap    INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS requests (
  id               TEXT PRIMARY KEY,
  api_key_id       TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
  model            TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending',
  latency_ms       INTEGER,
  prompt_preview   TEXT,
  prompt_full      TEXT,
  error            TEXT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS uploaded_voices (
  id          TEXT PRIMARY KEY,
  api_key_id  TEXT REFERENCES api_keys(id) ON DELETE CASCADE,
  name        TEXT,
  file_path   TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VOICES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def new_id() -> str:
    return uuid.uuid4().hex


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )
        conn.commit()


# ── Admins ────────────────────────────────────────────────────────────────────

def get_admin_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(conn.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone())


def get_admin_by_id(admin_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(conn.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone())


def create_admin(username: str, password_hash: str) -> dict[str, Any]:
    admin_id = new_id()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO admins (id, username, password_hash) VALUES (?, ?, ?)",
            (admin_id, username, password_hash),
        )
        conn.commit()
    return {"id": admin_id, "username": username}


def update_admin_password(admin_id: str, password_hash: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (password_hash, admin_id))
        conn.commit()


def admin_count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM admins").fetchone()
        return int(row["n"])


# ── API Keys ──────────────────────────────────────────────────────────────────

def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone())


def get_api_key_by_id(key_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone())


def list_api_keys() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def create_api_key(
    *,
    prefix: str,
    key_hash: str,
    raw_key: str,
    name: str | None = None,
    owner_email: str | None = None,
    scopes: str = '["speech"]',
    bootstrap: bool = False,
) -> dict[str, Any]:
    key_id = new_id()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (id, prefix, key_hash, raw_key, name, owner_email, scopes, bootstrap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key_id, prefix, key_hash, raw_key, name, owner_email, scopes, 1 if bootstrap else 0),
        )
        conn.commit()
    return {"id": key_id, "prefix": prefix, "raw_key": raw_key}


def update_api_key(key_id: str, **fields: Any) -> None:
    allowed = {"active", "name", "scopes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    if "active" in updates:
        updates["active"] = 1 if updates["active"] else 0
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [key_id]
    with _connect() as conn:
        conn.execute(f"UPDATE api_keys SET {set_clause} WHERE id = ?", values)
        conn.commit()


def delete_api_key(key_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.commit()


def touch_api_key(key_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", (key_id,))
        conn.commit()


def get_bootstrap_key() -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute("SELECT * FROM api_keys WHERE bootstrap = 1 AND active = 1 LIMIT 1").fetchone()
        )


# ── Requests ──────────────────────────────────────────────────────────────────

def create_request(*, api_key_id: str | None, model: str, prompt_full: str) -> str:
    req_id = new_id()
    preview = prompt_full[:200]
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO requests (id, api_key_id, model, status, prompt_preview, prompt_full)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (req_id, api_key_id, model, preview, prompt_full),
        )
        conn.commit()
    return req_id


def finish_request(
    req_id: str,
    *,
    status: str,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE requests SET status = ?, latency_ms = ?, error = ?
            WHERE id = ?
            """,
            (status, latency_ms, error, req_id),
        )
        conn.commit()


def list_requests(limit: int = 100) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*, k.prefix AS key_prefix, k.name AS key_name
            FROM requests r
            LEFT JOIN api_keys k ON k.id = r.api_key_id
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_request(req_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute(
                """
                SELECT r.*, k.prefix AS key_prefix, k.name AS key_name, k.owner_email AS key_email
                FROM requests r
                LEFT JOIN api_keys k ON k.id = r.api_key_id
                WHERE r.id = ?
                """,
                (req_id,),
            ).fetchone()
        )


# ── Uploaded voices ───────────────────────────────────────────────────────────

def create_uploaded_voice(*, voice_id: str, api_key_id: str | None, name: str | None, file_path: str) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO uploaded_voices (id, api_key_id, name, file_path) VALUES (?, ?, ?, ?)",
            (voice_id, api_key_id, name, file_path),
        )
        conn.commit()
    return {"id": voice_id, "name": name, "file_path": file_path}


def get_uploaded_voice(voice_id: str, api_key_id: str | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        if api_key_id is None:
            return _row_to_dict(
                conn.execute("SELECT * FROM uploaded_voices WHERE id = ?", (voice_id,)).fetchone()
            )
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM uploaded_voices WHERE id = ? AND (api_key_id = ? OR api_key_id IS NULL)",
                (voice_id, api_key_id),
            ).fetchone()
        )


def list_uploaded_voices(api_key_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if api_key_id is None:
            rows = conn.execute("SELECT * FROM uploaded_voices ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM uploaded_voices WHERE api_key_id = ? OR api_key_id IS NULL ORDER BY created_at DESC",
                (api_key_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_owned_voice(voice_id: str, api_key_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM uploaded_voices WHERE id = ? AND api_key_id = ?",
                (voice_id, api_key_id),
            ).fetchone()
        )


def delete_uploaded_voice(voice_id: str, api_key_id: str) -> dict[str, Any] | None:
    row = get_owned_voice(voice_id, api_key_id)
    if not row:
        return None
    with _connect() as conn:
        conn.execute("DELETE FROM uploaded_voices WHERE id = ? AND api_key_id = ?", (voice_id, api_key_id))
        conn.commit()
    return row


def delete_uploaded_voice_by_id(voice_id: str) -> dict[str, Any] | None:
    row = get_uploaded_voice(voice_id)
    if not row:
        return None
    with _connect() as conn:
        conn.execute("DELETE FROM uploaded_voices WHERE id = ?", (voice_id,))
        conn.commit()
    return row
