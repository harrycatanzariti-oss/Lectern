"""Build a subject's course from its uploads: plan topics, then write each one."""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from . import db
from .ai import MAX_MATERIAL_CHARS, AIError, Tutor, material_text

log = logging.getLogger(__name__)
PARALLEL_TOPICS = 4

_running: set[int] = set()
_lock = threading.Lock()


def _status(subject_id: int, status: str, message: str, progress: float | None = None) -> None:
    with db.tx() as conn:
        if progress is None:
            conn.execute(
                "UPDATE subjects SET build_status=?, build_message=? WHERE id=?",
                (status, message, subject_id),
            )
        else:
            conn.execute(
                "UPDATE subjects SET build_status=?, build_message=?, build_progress=? WHERE id=?",
                (status, message, progress, subject_id),
            )


def start(subject_id: int, tutor: Tutor) -> bool:
    """Run the build in the background. False if one is already running."""
    with _lock:
        if subject_id in _running:
            return False
        _running.add(subject_id)
    _status(subject_id, "building", "Reading your material", 0.01)
    threading.Thread(target=_run, args=(subject_id, tutor), daemon=True).start()
    return True


def _run(subject_id: int, tutor: Tutor) -> None:
    try:
        build(subject_id, tutor)
    except AIError as e:
        _status(subject_id, "failed", str(e))
    except Exception:
        log.exception("build of subject %s failed", subject_id)
        _status(subject_id, "failed", "Something went wrong building this subject. Try again.")
    finally:
        with _lock:
            _running.discard(subject_id)


def build(subject_id: int, tutor: Tutor) -> None:
    with db.tx() as conn:
        subject = db.row(conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone())
        chunks = db.rows(conn.execute(
            "SELECT id, label, text FROM chunks WHERE subject_id=? ORDER BY document_id, idx", (subject_id,)
        ))
    if not chunks:
        raise AIError("Upload some slides or a textbook first.")
    material = material_text(chunks)
    if len(material) > MAX_MATERIAL_CHARS:
        raise AIError(
            f"This subject has about {len(material) // 4000}k tokens of text, more than Claude can read "
            "at once. Split it into two subjects (e.g. by semester or textbook part)."
        )
    labels = {c["id"]: c["label"] for c in chunks}

    _status(subject_id, "building", "Planning the course", 0.03)
    outline = tutor.outline(subject["name"], material)["topics"]
    if not outline:
        raise AIError("Claude couldn't find any topics in this material.")
    for t in outline:
        t["sources"] = [s for s in t["sources"] if s in labels]

    with db.tx() as conn:
        # A rebuild starts the course over: old topics take their cards and attempts with them.
        conn.execute("DELETE FROM topics WHERE subject_id=?", (subject_id,))
        topic_ids = [
            conn.execute(
                "INSERT INTO topics (subject_id, position, title, summary, sources) VALUES (?,?,?,?,?)",
                (subject_id, i, t["title"], t["summary"], json.dumps([labels[s] for s in t["sources"]])),
            ).lastrowid
            for i, t in enumerate(outline)
        ]

    done = 0
    failed = 0
    done_lock = threading.Lock()

    def write(i: int) -> None:
        nonlocal done, failed
        try:
            content = tutor.topic(subject["name"], material, outline, i)
            _save_topic(subject_id, topic_ids[i], content, labels)
        except Exception as e:
            log.warning("topic %s of subject %s failed: %s", i, subject_id, e)
            with db.tx() as conn:
                conn.execute("UPDATE topics SET status='failed' WHERE id=?", (topic_ids[i],))
            with done_lock:
                failed += 1
        with done_lock:
            done += 1
            _status(
                subject_id, "building", f"Wrote {done} of {len(outline)} topics",
                0.05 + 0.95 * done / len(outline),
            )

    # The first topic writes the material into Claude's cache; the rest read from it.
    write(0)
    with ThreadPoolExecutor(PARALLEL_TOPICS) as pool:
        list(pool.map(write, range(1, len(outline))))

    with db.tx() as conn:
        conn.execute("UPDATE subjects SET built_at=datetime('now') WHERE id=?", (subject_id,))
    if failed == len(outline):
        _status(subject_id, "failed", "Claude couldn't write any topics. Try building again.", 1)
    elif failed:
        _status(subject_id, "built", f"{failed} of {len(outline)} topics failed to write. Build again to retry.", 1)
    else:
        _status(subject_id, "built", f"{len(outline)} topics ready", 1)


def _save_topic(subject_id: int, topic_id: int, content: dict, labels: dict[int, str]) -> None:
    def source(s: int) -> str:
        return labels.get(s, "")

    with db.tx() as conn:
        conn.execute(
            "UPDATE topics SET lesson_md=?, key_points=?, status='ready' WHERE id=?",
            (content["lesson_md"], json.dumps(content["key_points"]), topic_id),
        )
        conn.executemany(
            "INSERT INTO cards (topic_id, subject_id, front, back, source) VALUES (?,?,?,?,?)",
            [(topic_id, subject_id, c["front"], c["back"], source(c["source"])) for c in content["flashcards"]],
        )
        for q in content["questions"]:
            mcq = q["kind"] == "mcq" and len(q["options"]) >= 2 and 0 <= q["answer_index"] < len(q["options"])
            conn.execute(
                "INSERT INTO questions (topic_id, subject_id, kind, prompt, options, answer_index, model_answer, "
                "explanation, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    topic_id, subject_id, "mcq" if mcq else "short", q["prompt"],
                    json.dumps(q["options"] if mcq else []), q["answer_index"] if mcq else None,
                    q["model_answer"], q["explanation"], source(q["source"]),
                ),
            )
