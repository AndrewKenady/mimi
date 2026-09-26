"""SQLite persistence: one local database file, WAL mode, versioned migrations.

A single connection guarded by a re-entrant lock keeps things simple and safe
for a single-device app (FastAPI handlers, worker threads and background tasks
all share it). Queries are short; heavy work happens outside the lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # --- v1: initial schema ------------------------------------------------
    """
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);

    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL,              -- owner | user | guest
        color TEXT,
        pin_hash TEXT,
        password_hash TEXT,
        created_at REAL NOT NULL,
        last_seen REAL
    );
    CREATE UNIQUE INDEX users_name ON users(name COLLATE NOCASE);

    CREATE TABLE sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at REAL NOT NULL,
        last_seen REAL,
        client TEXT,
        ip TEXT
    );

    CREATE TABLE settings (scope TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL);

    CREATE TABLE chats (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT,
        project TEXT,
        mode TEXT,
        head_id TEXT,
        pinned INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0,
        temporary INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX chats_user ON chats(user_id, archived, updated_at);

    CREATE TABLE messages (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        parent_id TEXT,
        role TEXT NOT NULL,               -- user | assistant
        content TEXT NOT NULL DEFAULT '',
        meta TEXT,                        -- JSON: sources, tools, memories, attachments, timings, model
        created_at REAL NOT NULL
    );
    CREATE INDEX messages_chat ON messages(chat_id, created_at);
    CREATE INDEX messages_parent ON messages(parent_id);
    CREATE VIRTUAL TABLE messages_fts USING fts5(content, chat_id UNINDEXED, message_id UNINDEXED);

    CREATE TABLE memories (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        category TEXT,
        status TEXT NOT NULL,             -- active | suggested
        pinned INTEGER NOT NULL DEFAULT 0,
        source_chat_id TEXT,
        source_message_id TEXT,
        embedding BLOB,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_used_at REAL,
        use_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX memories_user ON memories(user_id, status);

    CREATE TABLE docs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        kind TEXT,                        -- pdf | docx | text | note
        source TEXT,                      -- upload | scribe
        title TEXT,
        path TEXT,
        size INTEGER,
        status TEXT,                      -- queued | indexing | ready | error
        error TEXT,
        chunks INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    );
    CREATE TABLE doc_chunks (
        id INTEGER PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        text TEXT NOT NULL,
        embedding BLOB
    );
    CREATE INDEX doc_chunks_doc ON doc_chunks(doc_id);
    CREATE VIRTUAL TABLE doc_chunks_fts USING fts5(text, content='doc_chunks', content_rowid='id');
    CREATE TRIGGER doc_chunks_ai AFTER INSERT ON doc_chunks BEGIN
        INSERT INTO doc_chunks_fts(rowid, text) VALUES (new.id, new.text);
    END;
    CREATE TRIGGER doc_chunks_ad AFTER DELETE ON doc_chunks BEGIN
        INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    END;

    CREATE TABLE notes (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL,             -- queued | transcribing | summarizing | ready | error
        progress REAL NOT NULL DEFAULT 0,
        duration REAL,
        audio_path TEXT,
        transcript TEXT,                  -- JSON list of segments
        summary TEXT,                     -- JSON: summary, key_points, action_items
        meta TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE locations (ts REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, source TEXT, accuracy REAL);
    """,
]


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._migrate()

    # --- migrations -------------------------------------------------------
    def _migrate(self) -> None:
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
                try:
                    self.conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version={i};\nCOMMIT;")
                except Exception:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise

    # --- helpers ----------------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, seq)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # key/value store for small bits of device state
    def kv_get(self, key: str, default: Any = None) -> Any:
        v = self.scalar("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(v) if v is not None else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return default
