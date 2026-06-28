#!/usr/bin/env python3
"""
Shared DB helpers for personal sessions.db and per-project mental-model.db.
Uses stdlib sqlite3 (FTS5 built into macOS SQLite) + JSON blob embeddings.

Personal DB:  ~/.claude/sessions.db
  - sessions      — metadata + JSON embedding
  - sessions_fts  — FTS5 virtual table for keyword search

Project DB:   <project-root>/.claude/mental-model.db
  - mental_model      — metadata + JSON embedding
  - mental_model_fts  — FTS5 virtual table
"""
import json
import math
import sqlite3
from pathlib import Path

PERSONAL_DB = Path.home() / ".claude" / "sessions.db"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_personal(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            file_name   TEXT NOT NULL UNIQUE,
            date        TEXT NOT NULL,
            title       TEXT,
            embedding   TEXT,
            indexed_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
            session_id,
            file_name,
            date,
            title,
            content,
            content='',
            contentless_delete=1
        );
    """)
    conn.commit()


def _init_project(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mental_model (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            file_name   TEXT NOT NULL,
            date        TEXT NOT NULL,
            title       TEXT,
            summary     TEXT,
            embedding   TEXT,
            indexed_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS mental_model_fts USING fts5(
            session_id,
            file_name,
            date,
            title,
            content,
            content='',
            contentless_delete=1
        );
    """)
    conn.commit()


def personal_db() -> sqlite3.Connection:
    PERSONAL_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(str(PERSONAL_DB))
    _init_personal(conn)
    return conn


def project_db(project_root: Path) -> sqlite3.Connection:
    db_path = project_root / ".claude" / "mental-model.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(str(db_path))
    _init_project(conn)
    return conn


def vec_to_json(embedding: list) -> str:
    return json.dumps(embedding)


def cosine_distance(a: list, b_json: str) -> float:
    """Cosine distance in [0, 2]. 0 = identical."""
    b = json.loads(b_json)
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 2.0
    return 1.0 - (dot / (mag_a * mag_b))
