"""HTTP API for the web app."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import builder, db, srs
from .ai import AIError, Tutor
from .extract import SUPPORTED, UnsupportedFile, extract

logging.basicConfig(level=logging.INFO)

MASTERED = 0.8
NEW_CARDS_PER_SESSION = 15
MAX_UPLOAD_BYTES = 200 * 1024 * 1024



@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="Lectern", lifespan=lifespan)
_tutor: Tutor | None = None


def tutor() -> Tutor:
    global _tutor
    if _tutor is None:
        _tutor = Tutor()
    return _tutor


def set_tutor(t: Tutor) -> None:
    """Tests swap in a fake tutor."""
    global _tutor
    _tutor = t


def _get(conn, sql: str, *args) -> dict:
    r = db.row(conn.execute(sql, args).fetchone())
    if r is None:
        raise HTTPException(404, "Not found")
    return r


# ---------- mastery ----------

def topic_mastery(conn, topic_ids: list[int]) -> dict[int, dict]:
    """Per topic: how well the cards are known and how well practice questions go, 0..1."""
    out = {t: {"cards": 0, "cards_known": 0.0, "questions": 0, "practice": 0.0, "attempted": 0} for t in topic_ids}
    if not topic_ids:
        return out
    marks = ",".join("?" * len(topic_ids))
    for r in conn.execute(
        f"SELECT topic_id, COUNT(*) n, SUM(MIN(interval_days / {srs.MATURE_DAYS}.0, 1.0)) known "
        f"FROM cards WHERE topic_id IN ({marks}) GROUP BY topic_id", topic_ids,
    ):
        out[r["topic_id"]].update(cards=r["n"], cards_known=r["known"] or 0.0)
    for r in conn.execute(
        f"SELECT topic_id, COUNT(*) n FROM questions WHERE topic_id IN ({marks}) GROUP BY topic_id", topic_ids,
    ):
        out[r["topic_id"]]["questions"] = r["n"]
    # Latest attempt per question counts, so re-trying a question you got wrong fixes your score.
    for r in conn.execute(
        f"""SELECT a.topic_id, COUNT(*) n, SUM(a.score) total FROM attempts a
            JOIN (SELECT question_id, MAX(id) id FROM attempts GROUP BY question_id) latest ON latest.id = a.id
            WHERE a.topic_id IN ({marks}) GROUP BY a.topic_id""", topic_ids,
    ):
        out[r["topic_id"]].update(attempted=r["n"], practice=r["total"] or 0.0)

    result = {}
    for t, m in out.items():
        cards = m["cards_known"] / m["cards"] if m["cards"] else None
        practice = m["practice"] / m["questions"] if m["questions"] else None
        parts = [p for p in (cards, practice) if p is not None]
        result[t] = {
            "mastery": round(sum(parts) / len(parts), 3) if parts else 0.0,
            "cards": round(cards or 0.0, 3),
            "practice": round(practice or 0.0, 3),
            "attempted": m["attempted"],
            "questions": m["questions"],
        }
    return result


def _due_counts(conn, subject_id: int | None = None) -> dict[int, dict]:
    sql = (
        "SELECT subject_id, SUM(due_at IS NOT NULL AND due_at <= ?) due, SUM(due_at IS NULL) new "
        "FROM cards {} GROUP BY subject_id"
    )
    args: list = [srs.iso(srs.now())]
    if subject_id is not None:
        sql = sql.format("WHERE subject_id=?")
        args.append(subject_id)
    else:
        sql = sql.format("")
    return {r["subject_id"]: {"due": r["due"] or 0, "new": r["new"] or 0} for r in conn.execute(sql, args)}


# ---------- subjects ----------

class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="#3b6cf6", pattern=r"^#[0-9a-fA-F]{6}$")


class SubjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


@app.get("/api/subjects")
def list_subjects():
    with db.tx() as conn:
        subjects = db.rows(conn.execute("SELECT * FROM subjects ORDER BY created_at DESC, id DESC"))
        due = _due_counts(conn)
        for s in subjects:
            topics = [r["id"] for r in conn.execute(
                "SELECT id FROM topics WHERE subject_id=? AND status='ready'", (s["id"],)
            )]
            m = topic_mastery(conn, topics)
            s["topics"] = len(topics)
            s["mastered"] = sum(1 for v in m.values() if v["mastery"] >= MASTERED)
            s["mastery"] = round(sum(v["mastery"] for v in m.values()) / len(m), 3) if m else 0.0
            s["documents"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE subject_id=?", (s["id"],)
            ).fetchone()[0]
            s.update(due.get(s["id"], {"due": 0, "new": 0}))
    return subjects


@app.post("/api/subjects", status_code=201)
def create_subject(body: SubjectIn):
    with db.tx() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, color) VALUES (?, ?)", (body.name.strip(), body.color)
        ).lastrowid
        return _get(conn, "SELECT * FROM subjects WHERE id=?", sid)


@app.patch("/api/subjects/{subject_id}")
def update_subject(subject_id: int, body: SubjectPatch):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        if body.name is not None:
            conn.execute("UPDATE subjects SET name=? WHERE id=?", (body.name.strip(), subject_id))
        if body.color is not None:
            conn.execute("UPDATE subjects SET color=? WHERE id=?", (body.color, subject_id))
        return _get(conn, "SELECT * FROM subjects WHERE id=?", subject_id)


@app.delete("/api/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: int):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        if conn.execute("SELECT build_status FROM subjects WHERE id=?", (subject_id,)).fetchone()[0] == "building":
            raise HTTPException(409, "Wait for the build to finish before deleting this subject.")
        conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))


@app.get("/api/subjects/{subject_id}")
def get_subject(subject_id: int):
    with db.tx() as conn:
        s = _get(conn, "SELECT * FROM subjects WHERE id=?", subject_id)
        s["documents"] = db.rows(conn.execute(
            "SELECT * FROM documents WHERE subject_id=? ORDER BY id", (subject_id,)
        ))
        topics = db.rows(conn.execute(
            "SELECT id, position, title, summary, sources, status, lesson_done FROM topics "
            "WHERE subject_id=? ORDER BY position", (subject_id,)
        ))
        m = topic_mastery(conn, [t["id"] for t in topics])
        for t in topics:
            t.update(m[t["id"]])
            t["lesson_done"] = bool(t["lesson_done"])
        s["topics"] = topics
        s.update(_due_counts(conn, subject_id).get(subject_id, {"due": 0, "new": 0}))
        s["next"] = _next_step(topics, s["due"])
        # Uploads newer than the last build aren't in the course yet.
        s["stale"] = bool(s["built_at"]) and conn.execute(
            "SELECT COUNT(*) FROM documents WHERE subject_id=? AND created_at > ?", (subject_id, s["built_at"])
        ).fetchone()[0] > 0
    return s


def _next_step(topics: list[dict], due: int) -> dict | None:
    """What the student should do now: clear due reviews, else learn or practise the next topic."""
    if due:
        return {"action": "review", "label": f"Review {due} due card{'s' if due != 1 else ''}"}
    for t in topics:
        if t["status"] != "ready" or t["mastery"] >= MASTERED:
            continue
        if not t["lesson_done"]:
            return {"action": "learn", "topic_id": t["id"], "label": f"Learn: {t['title']}"}
        return {"action": "practice", "topic_id": t["id"], "label": f"Practise: {t['title']}"}
    return None


# ---------- documents ----------

@app.post("/api/subjects/{subject_id}/documents", status_code=201)
async def upload(subject_id: int, files: list[UploadFile] = File(...), kind: str = Form("slides")):
    if kind not in ("slides", "textbook", "notes"):
        raise HTTPException(422, "kind must be slides, textbook or notes")
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
    added, errors = [], []
    for f in files:
        data = await f.read()
        name = Path(f.filename or "upload").name
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append(f"{name}: larger than 200 MB")
            continue
        try:
            chunks = extract(name, data)
        except UnsupportedFile as e:
            errors.append(str(e))
            continue
        except Exception:
            errors.append(f"{name}: couldn't read this file. Is it damaged or password-protected?")
            continue
        warning = "" if chunks else "No text found. If this is a scanned PDF, run it through OCR first."
        with db.tx() as conn:
            doc_id = conn.execute(
                "INSERT INTO documents (subject_id, filename, kind, units, chars, warning) VALUES (?,?,?,?,?,?)",
                (subject_id, name, kind, len(chunks), sum(len(c.text) for c in chunks), warning),
            ).lastrowid
            conn.executemany(
                "INSERT INTO chunks (document_id, subject_id, idx, label, text) VALUES (?,?,?,?,?)",
                [(doc_id, subject_id, i, c.label, c.text) for i, c in enumerate(chunks)],
            )
            conn.execute(
                "UPDATE subjects SET build_status='ready_to_build' WHERE id=? AND build_status IN ('empty')",
                (subject_id,),
            )
            added.append(_get(conn, "SELECT * FROM documents WHERE id=?", doc_id))
    if not added and errors:
        raise HTTPException(422, " ".join(errors))
    return {"documents": added, "errors": errors, "supported": SUPPORTED}


@app.delete("/api/documents/{document_id}", status_code=204)
def delete_document(document_id: int):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM documents WHERE id=?", document_id)
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))


@app.post("/api/subjects/{subject_id}/build", status_code=202)
def build(subject_id: int):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        if not conn.execute("SELECT COUNT(*) FROM chunks WHERE subject_id=?", (subject_id,)).fetchone()[0]:
            raise HTTPException(422, "Upload some slides or a textbook with readable text first.")
    if not builder.start(subject_id, tutor()):
        raise HTTPException(409, "This subject is already being built.")
    return {"ok": True}


# ---------- lessons ----------

@app.get("/api/topics/{topic_id}")
def get_topic(topic_id: int):
    with db.tx() as conn:
        t = _get(conn, "SELECT * FROM topics WHERE id=?", topic_id)
        t.update(topic_mastery(conn, [topic_id])[topic_id])
        t["lesson_done"] = bool(t["lesson_done"])
        neighbours = db.rows(conn.execute(
            "SELECT id, position, title FROM topics WHERE subject_id=? AND position IN (?, ?) ORDER BY position",
            (t["subject_id"], t["position"] - 1, t["position"] + 1),
        ))
        t["prev"] = next((n for n in neighbours if n["position"] < t["position"]), None)
        t["next"] = next((n for n in neighbours if n["position"] > t["position"]), None)
    return t


@app.post("/api/topics/{topic_id}/complete")
def complete_topic(topic_id: int):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM topics WHERE id=?", topic_id)
        conn.execute("UPDATE topics SET lesson_done=1 WHERE id=?", (topic_id,))
    return {"ok": True}


# ---------- flashcards ----------

@app.get("/api/subjects/{subject_id}/review")
def review_queue(subject_id: int, topic_id: int | None = None):
    """Due cards first (most overdue first), then new cards in course order."""
    where, args = "c.subject_id=?", [subject_id]
    if topic_id is not None:
        where += " AND c.topic_id=?"
        args.append(topic_id)
    cols = "c.id, c.front, c.back, c.source, c.reps, c.due_at, c.topic_id, t.title topic"
    with db.tx() as conn:
        due = db.rows(conn.execute(
            f"SELECT {cols} FROM cards c JOIN topics t ON t.id=c.topic_id "
            f"WHERE {where} AND c.due_at IS NOT NULL AND c.due_at <= ? ORDER BY c.due_at",
            [*args, srs.iso(srs.now())],
        ))
        # New cards only from topics whose lesson you've read, unless you picked the topic.
        lesson = "" if topic_id is not None else " AND t.lesson_done=1"
        new = db.rows(conn.execute(
            f"SELECT {cols} FROM cards c JOIN topics t ON t.id=c.topic_id "
            f"WHERE {where} AND c.due_at IS NULL{lesson} ORDER BY t.position, c.id LIMIT ?",
            [*args, NEW_CARDS_PER_SESSION],
        ))
    return {"cards": due + new, "due": len(due), "new": len(new)}


class GradeIn(BaseModel):
    grade: str


@app.post("/api/cards/{card_id}/grade")
def grade_card(card_id: int, body: GradeIn):
    if body.grade not in srs.GRADES:
        raise HTTPException(422, f"grade must be one of {', '.join(srs.GRADES)}")
    with db.tx() as conn:
        card = _get(conn, "SELECT * FROM cards WHERE id=?", card_id)
        new = srs.schedule(card, body.grade)
        conn.execute(
            "UPDATE cards SET ease=:ease, interval_days=:interval_days, reps=:reps, lapses=:lapses, "
            "due_at=:due_at WHERE id=:id",
            {**new, "id": card_id},
        )
    return new


# ---------- practice ----------

def _public_question(q: dict) -> dict:
    return {k: q[k] for k in ("id", "topic_id", "kind", "prompt", "options", "source", "topic")}


@app.get("/api/subjects/{subject_id}/practice")
def practice_set(subject_id: int, topic_id: int | None = None, n: int = 8):
    """Questions you haven't answered yet, then ones you got wrong, weakest topics first."""
    n = max(1, min(n, 30))
    where, args = "q.subject_id=?", [subject_id]
    if topic_id is not None:
        where += " AND q.topic_id=?"
        args.append(topic_id)
    else:
        where += " AND t.lesson_done=1"
    with db.tx() as conn:
        qs = db.rows(conn.execute(
            f"""SELECT q.*, t.title topic, t.position,
                   (SELECT score FROM attempts a WHERE a.question_id=q.id ORDER BY a.id DESC LIMIT 1) last
                FROM questions q JOIN topics t ON t.id=q.topic_id WHERE {where}""",
            args,
        ))
        mastery = topic_mastery(conn, list({q["topic_id"] for q in qs}))
    qs = [q for q in qs if q["last"] is None or q["last"] < 1]
    qs.sort(key=lambda q: (q["last"] is not None, mastery[q["topic_id"]]["mastery"], q["position"], q["id"]))
    return {"questions": [_public_question(q) for q in qs[:n]]}


class AnswerIn(BaseModel):
    answer: str = Field(max_length=8000)


@app.post("/api/questions/{question_id}/answer")
def answer_question(question_id: int, body: AnswerIn):
    with db.tx() as conn:
        q = _get(conn, "SELECT * FROM questions WHERE id=?", question_id)
    if q["kind"] == "mcq":
        try:
            picked = int(body.answer)
        except ValueError:
            raise HTTPException(422, "Answer a multiple-choice question with the option's index.")
        score = 1.0 if picked == q["answer_index"] else 0.0
        feedback = "Correct." if score else f"Not quite. The answer is: {q['options'][q['answer_index']]}"
    else:
        if not body.answer.strip():
            score, feedback = 0.0, "No answer given."
        else:
            try:
                marked = tutor().mark(q, body.answer)
            except AIError as e:
                raise HTTPException(503, str(e))
            score, feedback = marked["score"], marked["feedback"]
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO attempts (question_id, topic_id, score, answer, feedback) VALUES (?,?,?,?,?)",
            (question_id, q["topic_id"], score, body.answer, feedback),
        )
    return {
        "score": score,
        "feedback": feedback,
        "answer_index": q["answer_index"],
        "model_answer": q["model_answer"],
        "explanation": q["explanation"],
    }


# ---------- frontend ----------

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = DIST / path
        if path and file.is_file() and DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(DIST / "index.html")
