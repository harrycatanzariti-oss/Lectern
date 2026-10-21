import sqlite3

from lectern import db

OLD_SCHEMA = """
CREATE TABLE subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '#3b6cf6',
    created_at TEXT NOT NULL DEFAULT (datetime('now')), build_status TEXT NOT NULL DEFAULT 'empty',
    build_message TEXT NOT NULL DEFAULT '', build_progress REAL NOT NULL DEFAULT 0, built_at TEXT);
CREATE TABLE documents (id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, filename TEXT NOT NULL,
    kind TEXT NOT NULL, units INTEGER NOT NULL DEFAULT 0, chars INTEGER NOT NULL DEFAULT 0,
    warning TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE topics (id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, position INTEGER NOT NULL,
    title TEXT NOT NULL, summary TEXT NOT NULL, lesson_md TEXT NOT NULL DEFAULT '',
    key_points TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending', lesson_done INTEGER NOT NULL DEFAULT 0);
INSERT INTO subjects (id, name) VALUES (1, 'Calc');
INSERT INTO documents (subject_id, filename, kind) VALUES (1, 'w1.pdf', 'slides');
INSERT INTO topics (subject_id, position, title, summary, status, lesson_done) VALUES (1, 0, 'Limits', 's', 'ready', 1);
"""


def test_old_database_is_upgraded_in_place(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    sqlite3.connect(path).executescript(OLD_SCHEMA)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    db.init()  # running again is harmless
    with db.tx() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents").fetchone())
        topic = db.row(conn.execute("SELECT * FROM topics").fetchone())
    assert doc["image_pages"] == [] and doc["in_course"] == 1  # old uploads count as built in
    assert topic["unit"] == "" and topic["lesson_done"] == 1 and topic["title"] == "Limits"  # data kept
