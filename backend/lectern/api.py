"""HTTP API for the web app."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import builder, db, srs
from .ai import AIError, Tutor, material_text
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


# ---------- optional password ----------
# Set LECTERN_PASSWORD when the app is reachable from the internet; otherwise anyone who
# finds it can spend your DeepSeek credit.
PASSWORD = os.environ.get("LECTERN_PASSWORD", "")
COOKIE = "lectern_auth"


def _token() -> str:
    return hmac.new(PASSWORD.encode(), b"lectern", hashlib.sha256).hexdigest()


@app.middleware("http")
async def require_password(request: Request, call_next):
    path = request.url.path
    if PASSWORD and path.startswith("/api/") and path not in ("/api/login", "/api/session"):
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), _token()):
            return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return await call_next(request)


class LoginIn(BaseModel):
    password: str


@app.get("/api/session")
def session(request: Request):
    ok = not PASSWORD or hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())
    return {"signed_in": ok, "password_required": bool(PASSWORD)}


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    if not PASSWORD or not hmac.compare_digest(body.password, PASSWORD):
        raise HTTPException(401, "Wrong password.")
    response.set_cookie(COOKIE, _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90,
                        secure=os.environ.get("LECTERN_SECURE_COOKIE", "1") == "1")
    return {"ok": True}


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
        # Files uploaded since the course was built aren't in it yet.
        s["stale"] = bool(topics) and conn.execute(
            "SELECT COUNT(*) FROM documents WHERE subject_id=? AND in_course=0", (subject_id,)
        ).fetchone()[0] > 0
        s["failed_topics"] = sum(1 for t in topics if t["status"] == "failed")
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
            got = extract(name, data)
        except UnsupportedFile as e:
            errors.append(str(e))
            continue
        except Exception:
            errors.append(f"{name}: couldn't read this file. Is it damaged or password-protected?")
            continue
        chunks = got.chunks
        warning = ""
        if got.image_pages:
            n = len(got.image_pages)
            warning = f"{n} page{'s are' if n != 1 else ' is'} mostly images. The AI will read {'them' if n != 1 else 'it'} when you build."
        elif not chunks:
            warning = "No text found in this file."
        with db.tx() as conn:
            doc_id = conn.execute(
                "INSERT INTO documents (subject_id, filename, kind, units, chars, warning, image_pages) "
                "VALUES (?,?,?,?,?,?,?)",
                (subject_id, name, kind, len(chunks), sum(len(c.text) for c in chunks), warning,
                 json.dumps(got.image_pages)),
            ).lastrowid
            conn.executemany(
                "INSERT INTO chunks (document_id, subject_id, idx, label, text) VALUES (?,?,?,?,?)",
                [(doc_id, subject_id, c.page, c.label, c.text) for c in chunks],
            )
            if got.image_pages:
                # Kept so the AI can look at the image pages during the build.
                db.UPLOADS.mkdir(parents=True, exist_ok=True)
                (db.UPLOADS / f"{doc_id}.pdf").write_bytes(data)
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
    (db.UPLOADS / f"{document_id}.pdf").unlink(missing_ok=True)


class BuildIn(BaseModel):
    fresh: bool = False  # True: replan from scratch and reset progress


@app.post("/api/subjects/{subject_id}/build", status_code=202)
def build(subject_id: int, body: BuildIn | None = None):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        readable = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE subject_id=? AND (units > 0 OR image_pages != '[]')", (subject_id,)
        ).fetchone()[0]
        if not readable:
            raise HTTPException(422, "Upload some slides or a textbook with readable content first.")
    if not builder.start(subject_id, tutor(), fresh=bool(body and body.fresh)):
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


def _solution(q: dict) -> dict:
    return {
        "answer_index": q["answer_index"],
        "model_answer": q["model_answer"],
        "explanation": q["explanation"],
    }


def _mark(q: dict, answer: str) -> dict:
    if q["kind"] == "mcq":
        try:
            picked = int(answer)
        except ValueError:
            if not answer.strip():
                return {"score": 0.0, "feedback": "No answer given."}
            raise HTTPException(422, "Answer a multiple-choice question with the option's index.")
        if picked == q["answer_index"]:
            return {"score": 1.0, "feedback": "Correct."}
        return {"score": 0.0, "feedback": f"Not quite. The answer is: {q['options'][q['answer_index']]}"}
    if not answer.strip():
        return {"score": 0.0, "feedback": "No answer given."}
    try:
        return tutor().mark(q, answer)
    except AIError as e:
        raise HTTPException(503, str(e))


@app.post("/api/questions/{question_id}/answer")
def answer_question(question_id: int, body: AnswerIn):
    with db.tx() as conn:
        q = _get(conn, "SELECT * FROM questions WHERE id=?", question_id)
    m = _mark(q, body.answer)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO attempts (question_id, topic_id, score, answer, feedback) VALUES (?,?,?,?,?)",
            (question_id, q["topic_id"], m["score"], body.answer, m["feedback"]),
        )
    return {**m, **_solution(q)}


# ---------- study everything that's due ----------

@app.get("/api/review")
def review_all():
    """Due cards from every subject, most overdue first, then a few new cards from each."""
    cols = "c.id, c.front, c.back, c.source, c.reps, c.due_at, c.topic_id, t.title topic, s.name subject, s.color"
    join = "FROM cards c JOIN topics t ON t.id=c.topic_id JOIN subjects s ON s.id=c.subject_id"
    with db.tx() as conn:
        due = db.rows(conn.execute(
            f"SELECT {cols} {join} WHERE c.due_at IS NOT NULL AND c.due_at <= ? ORDER BY c.due_at",
            (srs.iso(srs.now()),),
        ))
        new = []
        for (sid,) in conn.execute("SELECT id FROM subjects ORDER BY id"):
            new += db.rows(conn.execute(
                f"SELECT {cols} {join} WHERE c.subject_id=? AND c.due_at IS NULL AND t.lesson_done=1 "
                "ORDER BY t.position, c.id LIMIT ?",
                (sid, NEW_CARDS_PER_SESSION // 3 or 1),
            ))
    return {"cards": due + new, "due": len(due), "new": len(new)}


# ---------- tutor chat ----------

CHAT_HISTORY = 40  # messages of the thread sent back to the AI


def _thread(conn, subject_id: int, topic_id: int | None) -> list[dict]:
    return db.rows(conn.execute(
        "SELECT id, role, content, created_at FROM chat_messages WHERE subject_id=? AND topic_id IS ? ORDER BY id",
        (subject_id, topic_id),
    ))


@app.get("/api/subjects/{subject_id}/chat")
def get_chat(subject_id: int, topic_id: int | None = None):
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        return {"messages": _thread(conn, subject_id, topic_id)}


@app.delete("/api/subjects/{subject_id}/chat", status_code=204)
def clear_chat(subject_id: int, topic_id: int | None = None):
    with db.tx() as conn:
        conn.execute("DELETE FROM chat_messages WHERE subject_id=? AND topic_id IS ?", (subject_id, topic_id))


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    topic_id: int | None = None


@app.post("/api/subjects/{subject_id}/chat")
def chat(subject_id: int, body: ChatIn):
    """Stream the tutor's reply as newline-delimited JSON: {"text": …} pieces, then {"done": true}."""
    with db.tx() as conn:
        subject = _get(conn, "SELECT * FROM subjects WHERE id=?", subject_id)
        topic = None
        if body.topic_id is not None:
            topic = _get(conn, "SELECT * FROM topics WHERE id=? AND subject_id=?", body.topic_id, subject_id)
        chunks = db.rows(conn.execute(
            "SELECT id, label, text FROM chunks WHERE subject_id=? ORDER BY document_id, idx", (subject_id,)
        ))
        history = _thread(conn, subject_id, body.topic_id)[-CHAT_HISTORY:]
        # The thread must open with the student; drop a leading reply left by trimming.
        while history and history[0]["role"] != "user":
            history.pop(0)
    if not chunks:
        raise HTTPException(422, "Upload some material first.")
    material = material_text(chunks)

    def stream():
        reply = []
        try:
            for piece in tutor().chat(subject["name"], material, topic, history, body.message):
                reply.append(piece)
                yield json.dumps({"text": piece}) + "\n"
        except AIError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception:
            logging.exception("chat failed")
            yield json.dumps({"error": "The tutor hit a problem. Try again."}) + "\n"
            return
        with db.tx() as conn:
            conn.executemany(
                "INSERT INTO chat_messages (subject_id, topic_id, role, content) VALUES (?,?,?,?)",
                [(subject_id, body.topic_id, "user", body.message),
                 (subject_id, body.topic_id, "assistant", "".join(reply))],
            )
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------- mock exams ----------

@app.get("/api/subjects/{subject_id}/exam")
def exam(subject_id: int, n: int = 10, topics: str = ""):
    """A mixed exam across the chosen topics (default: all), questions spread evenly over them."""
    n = max(1, min(n, 40))
    chosen = [int(t) for t in topics.split(",") if t.strip().isdigit()]
    with db.tx() as conn:
        _get(conn, "SELECT id FROM subjects WHERE id=?", subject_id)
        where, args = "q.subject_id=? AND t.status='ready'", [subject_id]
        if chosen:
            where += f" AND q.topic_id IN ({','.join('?' * len(chosen))})"
            args += chosen
        qs = db.rows(conn.execute(
            f"""SELECT q.*, t.title topic, t.position,
                   (SELECT COUNT(*) FROM attempts a WHERE a.question_id=q.id) tries
                FROM questions q JOIN topics t ON t.id=q.topic_id WHERE {where}
                ORDER BY random()""",
            args,
        ))
    # Round-robin across topics, least-practised questions first, so the exam covers the course.
    by_topic: dict[int, list[dict]] = {}
    for q in sorted(qs, key=lambda q: q["tries"]):
        by_topic.setdefault(q["topic_id"], []).append(q)
    picked: list[dict] = []
    while len(picked) < n and any(by_topic.values()):
        for bucket in by_topic.values():
            if bucket and len(picked) < n:
                picked.append(bucket.pop(0))
    picked.sort(key=lambda q: (q["position"], q["kind"] != "mcq"))
    return {"questions": [_public_question(q) for q in picked]}


class ExamAnswer(BaseModel):
    question_id: int
    answer: str = Field(max_length=8000)


class ExamIn(BaseModel):
    answers: list[ExamAnswer] = Field(max_length=40)


@app.post("/api/subjects/{subject_id}/exam")
def submit_exam(subject_id: int, body: ExamIn):
    """Mark every answer (short answers in parallel), record them, and break the score down by topic."""
    with db.tx() as conn:
        questions = {}
        for a in body.answers:
            q = _get(conn, "SELECT q.*, t.title topic FROM questions q JOIN topics t ON t.id=q.topic_id "
                           "WHERE q.id=? AND q.subject_id=?", a.question_id, subject_id)
            questions[a.question_id] = q

    def mark(a: ExamAnswer) -> dict:
        try:
            return _mark(questions[a.question_id], a.answer)
        except HTTPException as e:
            return {"score": 0.0, "feedback": f"Couldn't be marked: {e.detail}", "unmarked": True}

    with ThreadPoolExecutor(4) as pool:
        marks = list(pool.map(mark, body.answers))

    results, topics = [], {}
    with db.tx() as conn:
        for a, m in zip(body.answers, marks):
            q = questions[a.question_id]
            if not m.get("unmarked"):
                conn.execute(
                    "INSERT INTO attempts (question_id, topic_id, score, answer, feedback) VALUES (?,?,?,?,?)",
                    (q["id"], q["topic_id"], m["score"], a.answer, m["feedback"]),
                )
            results.append({**_public_question(q), "answer": a.answer, **m, **_solution(q)})
            t = topics.setdefault(q["topic_id"], {"topic_id": q["topic_id"], "topic": q["topic"], "score": 0.0, "n": 0})
            t["score"] += m["score"]
            t["n"] += 1
    total = sum(m["score"] for m in marks)
    return {
        "score": round(total / len(marks), 3) if marks else 0.0,
        "results": results,
        "topics": sorted(topics.values(), key=lambda t: t["score"] / t["n"]),
    }


# ---------- export for a Claude Project ----------

def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "subject"


@app.get("/api/subjects/{subject_id}/export")
def export(subject_id: int, material: bool = False):
    """One Markdown file with the course, your progress, and optionally the source text,
    to upload to a Claude Project's knowledge."""
    with db.tx() as conn:
        subject = _get(conn, "SELECT * FROM subjects WHERE id=?", subject_id)
        topics = db.rows(conn.execute(
            "SELECT * FROM topics WHERE subject_id=? AND status='ready' ORDER BY position", (subject_id,)
        ))
        mastery = topic_mastery(conn, [t["id"] for t in topics])
        cards = db.rows(conn.execute(
            "SELECT topic_id, front, back, reps, lapses, due_at FROM cards WHERE subject_id=? ORDER BY id", (subject_id,)
        ))
        questions = db.rows(conn.execute("SELECT * FROM questions WHERE subject_id=? ORDER BY id", (subject_id,)))
        misses = db.rows(conn.execute(
            """SELECT q.prompt, a.answer, a.score, a.feedback, t.title topic FROM attempts a
               JOIN questions q ON q.id=a.question_id JOIN topics t ON t.id=a.topic_id
               WHERE t.subject_id=? AND a.score < 1 AND a.id IN (SELECT MAX(id) FROM attempts GROUP BY question_id)
               ORDER BY a.id DESC LIMIT 25""",
            (subject_id,),
        ))
        chunks = db.rows(conn.execute(
            "SELECT label, text FROM chunks WHERE subject_id=? ORDER BY document_id, idx", (subject_id,)
        )) if material else []
        files = [r[0] for r in conn.execute("SELECT filename FROM documents WHERE subject_id=? ORDER BY id", (subject_id,))]

    out = [
        f"# {subject['name']}: study pack",
        "",
        f"Exported from Lectern on {srs.now():%d %B %Y}. Built from: {', '.join(files) or 'no files'}.",
        "",
        "> **For Claude:** this file is a student's course for this subject, their progress, and "
        "the mistakes they've made recently. Act as their tutor. Teach in the course's order, "
        "focus on topics marked weak, and when quizzing them, use the flashcards and practice "
        "questions here as a guide. "
        + ("The source material is at the end; cite its labels (e.g. \"Week 3.pdf, p.12\") when you use it."
           if material else "Their original slides and textbook may also be in this project; cite them by file and page."),
        "",
        "## Progress",
        "",
        "| # | Topic | Mastery | Lesson read | Practice answered |",
        "|---|---|---|---|---|",
    ]
    for t in topics:
        m = mastery[t["id"]]
        flag = " (weak)" if (t["lesson_done"] or m["attempted"]) and m["mastery"] < 0.5 else ""
        out.append(
            f"| {t['position'] + 1} | {t['title']}{flag} | {round(m['mastery'] * 100)}% | "
            f"{'yes' if t['lesson_done'] else 'no'} | {m['attempted']}/{m['questions']} |"
        )
    hard = [c for c in cards if c["lapses"] >= 2]
    if hard:
        out += ["", "**Flashcards they keep forgetting:**", ""]
        out += [f"- {c['front']} → {c['back']}" for c in hard[:20]]
    if misses:
        out += ["", "**Recent wrong or partly-right answers:**", ""]
        for m in misses:
            out.append(f"- [{m['topic']}] {m['prompt']}\n  - Their answer: {m['answer'] or '(blank)'} "
                       f"({round(m['score'] * 100)}%). {m['feedback']}")

    out += ["", "## Course", ""]
    for t in topics:
        out += [f"### {t['position'] + 1}. {t['title']}", "", f"*{t['summary']}*", ""]
        if t["sources"]:
            out += [f"Sources: {'; '.join(t['sources'])}", ""]
        out += [t["lesson_md"].strip(), ""]
        if t["key_points"]:
            out += ["**Key points**", ""] + [f"- {p}" for p in t["key_points"]] + [""]
        tc = [c for c in cards if c["topic_id"] == t["id"]]
        if tc:
            out += ["**Flashcards**", ""] + [f"- Q: {c['front']}\n  A: {c['back']}" for c in tc] + [""]
        tq = [q for q in questions if q["topic_id"] == t["id"]]
        if tq:
            out += ["**Practice questions**", ""]
            for i, q in enumerate(tq, 1):
                out.append(f"{i}. {q['prompt']}")
                for j, o in enumerate(q["options"]):
                    out.append(f"   - {chr(65 + j)}. {o}")
                answer = (f"{chr(65 + q['answer_index'])}. {q['options'][q['answer_index']]}"
                          if q["kind"] == "mcq" else q["model_answer"])
                out.append(f"   - *Answer:* {answer}")
                if q["explanation"]:
                    out.append(f"   - *Why:* {q['explanation']}")
            out.append("")

    if material:
        out += ["## Source material", ""]
        for c in chunks:
            out += [f"### {c['label']}", "", c["text"], ""]

    name = f"{_slug(subject['name'])}{'-with-material' if material else ''}.md"
    return Response(
        "\n".join(out),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


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
