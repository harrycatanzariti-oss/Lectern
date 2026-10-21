"""SQLite storage. One file, one connection per request/thread."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("LECTERN_DATA", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = Path(os.environ.get("LECTERN_DB", DATA_DIR / "lectern.db"))
UPLOADS = DATA_DIR / "uploads"

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#3b6cf6',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    build_status TEXT NOT NULL DEFAULT 'empty',   -- empty | ready_to_build | building | built | failed
    build_message TEXT NOT NULL DEFAULT '',
    build_progress REAL NOT NULL DEFAULT 0,
    built_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,              -- slides | textbook | notes | outline (the official syllabus)
    units INTEGER NOT NULL DEFAULT 0, -- pages or slides with text
    chars INTEGER NOT NULL DEFAULT 0,
    warning TEXT NOT NULL DEFAULT '',
    image_pages TEXT NOT NULL DEFAULT '[]', -- pages with too little text; the AI reads them at build
    in_course INTEGER NOT NULL DEFAULT 0,    -- set once a build has used this document
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT '',            -- the syllabus unit/module this topic belongs to
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    lesson_md TEXT NOT NULL DEFAULT '',
    key_points TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed | missing (on the syllabus, no material yet)
    lesson_done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_at TEXT                       -- NULL = never studied (new)
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,               -- mcq | short
    prompt TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    answer_index INTEGER,
    model_answer TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    score REAL NOT NULL,              -- 0..1
    answer TEXT NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,  -- NULL = the subject-wide chat
    role TEXT NOT NULL,               -- user | assistant
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- The syllabus: what the student has to know, organised by the course's learning
-- outcomes and how it's assessed. Rebuilt by the AI; confidence is the student's own.
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    weight REAL,                      -- percent of the final mark, if known
    format TEXT NOT NULL DEFAULT '',  -- e.g. "2-hour closed-book exam"
    criteria TEXT NOT NULL DEFAULT '' -- what markers look for
);
CREATE TABLE IF NOT EXISTS syllabus_sections (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT ''  -- the learning outcome this header stands for
);
CREATE TABLE IF NOT EXISTS syllabus_items (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES syllabus_sections(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',     -- what exactly to know, and to what depth
    marking TEXT NOT NULL DEFAULT '',    -- how it's marked / what earns the marks
    importance TEXT NOT NULL DEFAULT 'medium',  -- high | medium | low, by marks at stake
    assessed_in TEXT NOT NULL DEFAULT '[]',     -- assessment names
    topic_ids TEXT NOT NULL DEFAULT '[]',       -- course topics that teach it
    confidence INTEGER NOT NULL DEFAULT 0       -- the student's own: 0 unrated, 1 not yet, 2 getting there, 3 confident
);
CREATE INDEX IF NOT EXISTS syllabus_items_subject ON syllabus_items(subject_id, section_id, position);
CREATE INDEX IF NOT EXISTS chat_thread ON chat_messages(subject_id, topic_id, id);
CREATE INDEX IF NOT EXISTS chunks_subject ON chunks(subject_id, document_id, idx);
CREATE INDEX IF NOT EXISTS cards_due ON cards(subject_id, due_at);
CREATE INDEX IF NOT EXISTS attempts_topic ON attempts(topic_id);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS leaves an existing
# table alone, so databases made before a column existed get it added here.
ADDED_COLUMNS = [
    ("documents", "image_pages", "TEXT NOT NULL DEFAULT '[]'"),
    ("documents", "in_course", "INTEGER NOT NULL DEFAULT 1"),  # existing files were already built in
    ("topics", "unit", "TEXT NOT NULL DEFAULT ''"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init() -> None:
    with tx() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        # A build can't survive a restart; don't leave subjects stuck on "building".
        conn.execute(
            "UPDATE subjects SET build_status='failed', build_message='Interrupted by a restart. Build again.' "
            "WHERE build_status='building'"
        )


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for key in ("key_points", "sources", "options", "image_pages", "assessed_in", "topic_ids"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]
