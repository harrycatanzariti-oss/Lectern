"""Build a subject's course from its uploads: plan topics, then write each one.

Two modes. A fresh build plans the whole course from scratch and resets progress. An
update keeps every existing topic (and the student's progress on it), fits newly added
files in as new topics or extra sections, and retries topics that failed last time.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import db
from .ai import MAX_MATERIAL_CHARS, AIError, Tutor, material_text
from .extract import pdf_label, render_pages

log = logging.getLogger(__name__)
PARALLEL_TOPICS = 4
# Page images per transcription request: enough to be efficient, few enough to keep
# each request well under DeepSeek's size limit and its answer under the output limit.
TRANSCRIBE_BATCH = 8

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


def start(subject_id: int, tutor: Tutor, fresh: bool, syllabus_only: bool = False) -> bool:
    """Run the build in the background. False if one is already running."""
    with _lock:
        if subject_id in _running:
            return False
        _running.add(subject_id)
    _status(subject_id, "building", "Reading your material", 0.01)
    threading.Thread(target=_run, args=(subject_id, tutor, fresh, syllabus_only), daemon=True).start()
    return True


def _run(subject_id: int, tutor: Tutor, fresh: bool, syllabus_only: bool = False) -> None:
    try:
        if syllabus_only:
            rebuild_syllabus(subject_id, tutor)
        else:
            build(subject_id, tutor, fresh)
    except AIError as e:
        _status(subject_id, "failed", str(e))
    except Exception:
        log.exception("build of subject %s failed", subject_id)
        _status(subject_id, "failed", "Something went wrong building this subject. Try again.")
    finally:
        with _lock:
            _running.discard(subject_id)


def read_image_pages(subject_id: int, tutor: Tutor) -> None:
    """Have the AI read PDF pages that came without a usable text layer.

    A batch the AI can't read is skipped with a note on the file rather than failing
    the build: the rest of the course is still worth having."""
    with db.tx() as conn:
        docs = db.rows(conn.execute(
            "SELECT id, filename, image_pages FROM documents WHERE subject_id=? AND image_pages != '[]'",
            (subject_id,),
        ))
    total = sum(len(d["image_pages"]) for d in docs)
    done = 0
    for d in docs:
        path = db.UPLOADS / f"{d['id']}.pdf"
        if not path.exists():
            continue
        data = path.read_bytes()
        pages = d["image_pages"]
        failed_note = ""
        for start in range(0, len(pages), TRANSCRIBE_BATCH):
            batch = pages[start:start + TRANSCRIBE_BATCH]
            _status(subject_id, "building", f"Reading image pages ({done} of {total})", 0.01 + 0.02 * done / total)
            try:
                texts = tutor.transcribe(d["filename"], render_pages(data, batch), batch)
                note = ""
            except AIError as e:
                log.warning("couldn't read pages %s of %s: %s", batch, d["filename"], e)
                texts = {}
                note = f"Couldn't read some image pages ({e}). Upload a text version to include them."
            with db.tx() as conn:
                conn.executemany(
                    "INSERT INTO chunks (document_id, subject_id, idx, label, text) VALUES (?,?,?,?,?)",
                    [(d["id"], subject_id, p, pdf_label(d["filename"], p), t) for p, t in texts.items()],
                )
                left = [p for p in d["image_pages"] if p not in batch]
                # The upload's "the AI will read these" note is done with; a failure note stays.
                warning = note or failed_note
                failed_note = warning
                conn.execute(
                    "UPDATE documents SET image_pages=?, units=units+?, chars=chars+?, warning=? WHERE id=?",
                    (json.dumps(left), len(texts), sum(map(len, texts.values())), warning, d["id"]),
                )
                d["image_pages"] = left
            done += len(batch)


def _load_material(subject_id: int) -> tuple[dict, str, dict[int, str]]:
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
            f"This subject has about {len(material) // 4000}k tokens of text, more than the AI can read "
            "at once. Split it into two subjects (e.g. by semester or textbook part)."
        )
    return subject, material, {c["id"]: c["label"] for c in chunks}


def build(subject_id: int, tutor: Tutor, fresh: bool = True) -> None:
    read_image_pages(subject_id, tutor)
    subject, material, labels = _load_material(subject_id)
    with db.tx() as conn:
        has_course = conn.execute("SELECT COUNT(*) FROM topics WHERE subject_id=?", (subject_id,)).fetchone()[0]
        # Official course outlines: the syllabus every topic is measured against.
        outline_files = [r[0] for r in conn.execute(
            "SELECT filename FROM documents WHERE subject_id=? AND kind='outline' ORDER BY id", (subject_id,)
        )]
    if fresh or not has_course:
        _fresh(subject, material, labels, tutor, outline_files)
    else:
        _update(subject, material, labels, tutor, outline_files)


def _covered(t: dict) -> bool:
    """A syllabus item counts as covered only if the material is actually cited for it."""
    return bool(t["covered"] and t["sources"])


def _summary(written: int, added: int = 0, extended: int = 0, gaps: int = 0) -> str | None:
    parts = []
    if added:
        parts.append(f"{added} new topic{'s' * (added != 1)}")
    if extended:
        parts.append(f"{extended} topic{'s' * (extended != 1)} extended")
    if not parts and written:
        parts.append(f"{written} topic{'s' * (written != 1)} written")
    if gaps:
        parts.append(f"{gaps} syllabus item{'s' * (gaps != 1)} not in your material yet")
    return ", ".join(parts) or None


def _fresh(subject: dict, material: str, labels: dict[int, str], tutor: Tutor, outline_files: list[str]) -> None:
    subject_id = subject["id"]
    _status(subject_id, "building", "Planning the course", 0.03)
    outline = tutor.outline(subject["name"], material, outline_files)["topics"]
    if not outline:
        raise AIError("The AI couldn't find any topics in this material.")
    for t in outline:
        t["sources"] = [s for s in t["sources"] if s in labels]

    with db.tx() as conn:
        # A fresh build starts the course over: old topics take their cards and attempts with them.
        conn.execute("DELETE FROM topics WHERE subject_id=?", (subject_id,))
        topic_ids = [
            conn.execute(
                "INSERT INTO topics (subject_id, position, unit, title, summary, sources, status) VALUES (?,?,?,?,?,?,?)",
                (subject_id, i, t["unit"].strip(), t["title"], t["summary"],
                 json.dumps([labels[s] for s in t["sources"]]), "pending" if _covered(t) else "missing"),
            ).lastrowid
            for i, t in enumerate(outline)
        ]

    note = _syllabus_step(subject, material, tutor, outline_files)

    # Syllabus items with no material are listed, not written: there's nothing to teach from.
    jobs = [
        (topic_ids[i], lambda i=i: tutor.topic(subject["name"], material, outline, i))
        for i, t in enumerate(outline) if _covered(t)
    ]
    gaps = len(outline) - len(jobs)
    _write_all(subject_id, jobs, labels, total=len(jobs), done_message=_join(_summary(len(jobs), gaps=gaps), note))


def _update(subject: dict, material: str, labels: dict[int, str], tutor: Tutor, outline_files: list[str]) -> None:
    subject_id = subject["id"]
    with db.tx() as conn:
        existing = db.rows(conn.execute(
            "SELECT id, unit, title, summary, status, sources FROM topics WHERE subject_id=? ORDER BY position",
            (subject_id,),
        ))
        new_files = [r[0] for r in conn.execute(
            "SELECT filename FROM documents WHERE subject_id=? AND in_course=0 ORDER BY id", (subject_id,)
        )]
    by_id = {t["id"]: t for t in existing}

    def as_planned(t: dict) -> dict:
        return {"existing_id": t["id"], "unit": t["unit"], "title": t["title"], "summary": t["summary"],
                "sources": [], "covered": t["status"] != "missing", "extend": False}

    if new_files:
        _status(subject_id, "building", "Fitting your new files into the course", 0.03)
        planned = tutor.update_outline(subject["name"], material, existing, new_files, outline_files)["topics"]
    else:
        planned = [as_planned(t) for t in existing]

    # The AI must keep every existing topic; put back any it dropped, after its old neighbour.
    seen: set[int] = set()
    course: list[dict] = []
    for t in planned:
        t["sources"] = [s for s in t["sources"] if s in labels]
        eid = t["existing_id"]
        if eid in by_id and eid not in seen:
            seen.add(eid)
            old = by_id[eid]
            course.append({**t, "id": eid, "title": old["title"], "summary": old["summary"],
                           "unit": old["unit"] or t["unit"].strip()})  # a topic keeps its unit once it has one
        elif eid not in by_id:
            course.append({**t, "id": None, "unit": t["unit"].strip(), "extend": False})
    for i, t in enumerate(existing):
        if t["id"] not in seen:
            after = next((j for j, c in enumerate(course) if i and c["id"] == existing[i - 1]["id"]), -1)
            course.insert(after + 1, {**as_planned(t), "id": t["id"], "covered": False})

    with db.tx() as conn:
        for pos, t in enumerate(course):
            if t["id"] is None:
                t["id"] = conn.execute(
                    "INSERT INTO topics (subject_id, position, unit, title, summary, sources, status) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (subject_id, pos, t["unit"], t["title"], t["summary"],
                     json.dumps([labels[s] for s in t["sources"]]), "pending" if _covered(t) else "missing"),
                ).lastrowid
                t["new"] = True
            else:
                conn.execute("UPDATE topics SET position=?, unit=? WHERE id=?", (pos, t["unit"], t["id"]))
                if by_id[t["id"]]["status"] == "missing" and _covered(t):
                    conn.execute("UPDATE topics SET sources=? WHERE id=?",
                                 (json.dumps([labels[s] for s in t["sources"]]), t["id"]))

    note = _syllabus_step(subject, material, tutor, outline_files) if new_files else None

    outline = [{"title": t["title"], "summary": t["summary"], "sources": t["sources"]} for t in course]
    jobs: list[tuple[int, Callable[[], dict]]] = []
    added = extended = filled = 0
    for i, t in enumerate(course):
        status = "new" if t.get("new") else by_id[t["id"]]["status"]
        write = lambda i=i: tutor.topic(subject["name"], material, outline, i)  # noqa: E731
        if status == "new" and _covered(t):
            jobs.append((t["id"], write))
            added += 1
        elif status == "failed":
            jobs.append((t["id"], write))
        elif status == "missing" and _covered(t):
            jobs.append((t["id"], write))  # a syllabus gap the new material now fills
            filled += 1
        elif status == "ready" and t["extend"] and t["sources"]:
            jobs.append((t["id"], lambda t=t: tutor.extend_topic(
                subject["name"], material, t, t["sources"], _have(t["id"])
            )))
            extended += 1
    with db.tx() as conn:
        gaps = conn.execute("SELECT COUNT(*) FROM topics WHERE subject_id=? AND status='missing'",
                            (subject_id,)).fetchone()[0] - filled
    _write_all(subject_id, jobs, labels, total=len(jobs),
               done_message=_join(_summary(len(jobs), added + filled, extended, gaps) or "Course is up to date", note))


def _join(message: str | None, note: str | None) -> str | None:
    return ". ".join(m for m in (message, note) if m) or None


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _syllabus_step(subject: dict, material: str, tutor: Tutor, outline_files: list[str]) -> str | None:
    """Draft the syllabus. Returns a note for the status line if it couldn't be done;
    the course is still worth building without it."""
    _status(subject["id"], "building", "Mapping the syllabus", 0.04)
    try:
        write_syllabus(subject, material, tutor, outline_files)
        return None
    except Exception as e:
        log.warning("syllabus for subject %s failed: %s", subject["id"], e)
        return "The syllabus couldn't be drafted; try Rebuild syllabus"


def write_syllabus(subject: dict, material: str, tutor: Tutor, outline_files: list[str]) -> None:
    """Replace the subject's syllabus with a fresh draft, keeping the student's confidence
    ratings on items that survive (matched by title)."""
    subject_id = subject["id"]
    with db.tx() as conn:
        topics = db.rows(conn.execute(
            "SELECT id, title, summary FROM topics WHERE subject_id=? ORDER BY position", (subject_id,)
        ))
        old = db.rows(conn.execute(
            "SELECT s.title section, i.title item, i.confidence FROM syllabus_items i "
            "JOIN syllabus_sections s ON s.id=i.section_id WHERE i.subject_id=? ORDER BY s.position, i.position",
            (subject_id,),
        ))
    result = tutor.syllabus(subject["name"], material, outline_files, topics, old)
    if not result["sections"]:
        raise AIError("The AI returned an empty syllabus.")

    topic_ids = {t["id"] for t in topics}
    by_both = {(_norm(o["section"]), _norm(o["item"])): o["confidence"] for o in old}
    by_item = {_norm(o["item"]): o["confidence"] for o in old}
    names = [a["name"].strip() for a in result["assessments"]]
    with db.tx() as conn:
        conn.execute("DELETE FROM assessments WHERE subject_id=?", (subject_id,))
        conn.execute("DELETE FROM syllabus_sections WHERE subject_id=?", (subject_id,))
        for i, a in enumerate(result["assessments"]):
            weight = a["weight"] if 0 <= a["weight"] <= 100 else None
            conn.execute(
                "INSERT INTO assessments (subject_id, position, name, weight, format, criteria) VALUES (?,?,?,?,?,?)",
                (subject_id, i, names[i], weight, a["format"], a["criteria"]),
            )
        for i, sec in enumerate(result["sections"]):
            sid = conn.execute(
                "INSERT INTO syllabus_sections (subject_id, position, title, outcome) VALUES (?,?,?,?)",
                (subject_id, i, sec["title"].strip(), sec["outcome"].strip()),
            ).lastrowid
            for j, it in enumerate(sec["items"]):
                confidence = by_both.get((_norm(sec["title"]), _norm(it["title"])), by_item.get(_norm(it["title"]), 0))
                conn.execute(
                    "INSERT INTO syllabus_items (section_id, subject_id, position, title, detail, marking, importance, "
                    "assessed_in, topic_ids, confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, subject_id, j, it["title"].strip(), it["detail"], it["marking"], it["importance"],
                     json.dumps([n for n in (x.strip() for x in it["assessed_in"]) if n in names]),
                     json.dumps([t for t in dict.fromkeys(it["topic_ids"]) if t in topic_ids]), confidence),
                )


def rebuild_syllabus(subject_id: int, tutor: Tutor) -> None:
    """Redraft just the syllabus, e.g. after adding a course outline or for a course built
    before syllabuses existed."""
    subject, material, _labels = _load_material(subject_id)
    with db.tx() as conn:
        outline_files = [r[0] for r in conn.execute(
            "SELECT filename FROM documents WHERE subject_id=? AND kind='outline' ORDER BY id", (subject_id,)
        )]
    _status(subject_id, "building", "Mapping the syllabus", 0.3)
    write_syllabus(subject, material, tutor, outline_files)
    _status(subject_id, "built", "Syllabus updated", 1)


def _have(topic_id: int) -> dict[str, list[str]]:
    """What a topic already teaches, so an extension doesn't repeat it."""
    with db.tx() as conn:
        t = db.row(conn.execute("SELECT key_points FROM topics WHERE id=?", (topic_id,)).fetchone())
        return {
            "key_points": t["key_points"],
            "cards": [r[0] for r in conn.execute("SELECT front FROM cards WHERE topic_id=?", (topic_id,))],
            "questions": [r[0] for r in conn.execute("SELECT prompt FROM questions WHERE topic_id=?", (topic_id,))],
        }


def _write_all(
    subject_id: int,
    jobs: list[tuple[int, Callable[[], dict]]],
    labels: dict[int, str],
    total: int,
    done_message: str | None = None,
) -> None:
    done = 0
    failed = 0
    done_lock = threading.Lock()

    def write(job: tuple[int, Callable[[], dict]]) -> None:
        nonlocal done, failed
        topic_id, make = job
        try:
            _save_topic(subject_id, topic_id, make(), labels)
        except Exception as e:
            log.warning("topic %s of subject %s failed: %s", topic_id, subject_id, e)
            with db.tx() as conn:
                # A failed extension leaves the topic as it was; a failed new topic is marked.
                conn.execute("UPDATE topics SET status='failed' WHERE id=? AND status!='ready'", (topic_id,))
            with done_lock:
                failed += 1
        with done_lock:
            done += 1
            _status(subject_id, "building", f"Wrote {done} of {total} topics", 0.05 + 0.95 * done / total)

    if not jobs:
        _finish(subject_id, done_message or "Course is up to date")
        return
    # The first call puts the material in DeepSeek's prefix cache; the rest read from it.
    write(jobs[0])
    with ThreadPoolExecutor(PARALLEL_TOPICS) as pool:
        list(pool.map(write, jobs[1:]))

    if failed == total:
        _status(subject_id, "failed", "The AI couldn't write any topics. Try building again.", 1)
    elif failed:
        _finish(subject_id, f"{failed} of {total} topics failed to write. Update the course to retry them.")
    else:
        _finish(subject_id, done_message or f"{total} topic{'s' if total != 1 else ''} written")


def _finish(subject_id: int, message: str) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE subjects SET built_at=datetime('now') WHERE id=?", (subject_id,))
        conn.execute("UPDATE documents SET in_course=1 WHERE subject_id=?", (subject_id,))
    _status(subject_id, "built", message, 1)


def _save_topic(subject_id: int, topic_id: int, content: dict, labels: dict[int, str]) -> None:
    """Store a written topic. On a topic that's already ready, append instead (an extension)."""
    def source(s: int) -> str:
        return labels.get(s, "")

    with db.tx() as conn:
        t = db.row(conn.execute("SELECT status, lesson_md, key_points FROM topics WHERE id=?", (topic_id,)).fetchone())
        if t["status"] == "ready":
            lesson = f"{t['lesson_md'].rstrip()}\n\n{content['lesson_md'].strip()}"
            points = t["key_points"] + content["key_points"]
        else:
            lesson, points = content["lesson_md"], content["key_points"]
            # Rewriting a failed topic: clear anything half-saved.
            conn.execute("DELETE FROM cards WHERE topic_id=?", (topic_id,))
            conn.execute("DELETE FROM questions WHERE topic_id=?", (topic_id,))
        conn.execute(
            "UPDATE topics SET lesson_md=?, key_points=?, status='ready' WHERE id=?",
            (lesson, json.dumps(points), topic_id),
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
