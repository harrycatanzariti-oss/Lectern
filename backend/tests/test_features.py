import json

from lectern import api, builder, db

from .test_api import build, make_subject, upload
from .test_extract import RULE, make_pdf


def topics(client, sid):
    return client.get(f"/api/subjects/{sid}").json()["topics"]


def test_image_pages_are_read_by_claude(client):
    sid = make_subject(client)
    r = client.post(f"/api/subjects/{sid}/documents",
                    files=[("files", ("scan.pdf", make_pdf(RULE, ""), "application/pdf"))])
    doc = r.json()["documents"][0]
    assert doc["image_pages"] == [2] and "The AI will read it" in doc["warning"]
    assert (db.UPLOADS / f"{doc['id']}.pdf").exists()

    build(client, sid)
    with db.tx() as conn:
        labels = [r[0] for r in conn.execute("SELECT label FROM chunks WHERE subject_id=? ORDER BY idx", (sid,))]
        d = db.row(conn.execute("SELECT * FROM documents WHERE id=?", (doc["id"],)).fetchone())
    assert labels == ["scan.pdf, p.1", "scan.pdf, p.2"]
    assert d["image_pages"] == [] and d["units"] == 2 and d["warning"] == ""

    client.delete(f"/api/documents/{doc['id']}")
    assert not (db.UPLOADS / f"{doc['id']}.pdf").exists()


def test_image_only_pdf_can_be_built(client, monkeypatch):
    started = []
    monkeypatch.setattr(builder, "start", lambda sid, tutor, fresh: started.append(sid) or True)
    sid = make_subject(client)
    client.post(f"/api/subjects/{sid}/documents", files=[("files", ("scan.pdf", make_pdf(""), "application/pdf"))])
    assert client.post(f"/api/subjects/{sid}/build").status_code == 202 and started == [sid]


def test_update_keeps_progress_and_adds_topics(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    before = topics(client, sid)
    limits = before[0]["id"]
    client.post(f"/api/topics/{limits}/complete")
    card = client.get(f"/api/subjects/{sid}/review").json()["cards"][0]
    client.post(f"/api/cards/{card['id']}/grade", json={"grade": "easy"})
    assert client.get(f"/api/subjects/{sid}").json()["stale"] is False

    upload(client, sid, "Integrals are areas under curves.")
    assert client.get(f"/api/subjects/{sid}").json()["stale"] is True
    assert client.post(f"/api/subjects/{sid}/build", json={"fresh": False}).status_code == 202
    for _ in range(200):
        if client.get(f"/api/subjects/{sid}").json()["build_status"] != "building":
            break
        import time; time.sleep(0.01)

    s = client.get(f"/api/subjects/{sid}").json()
    assert s["build_status"] == "built" and s["stale"] is False
    assert s["build_message"] == "1 new topic, 1 topic extended"
    assert [t["title"] for t in s["topics"]] == ["Limits", "Derivatives", "Integrals"]  # titles kept
    assert [t["id"] for t in s["topics"][:2]] == [t["id"] for t in before]
    assert s["topics"][0]["lesson_done"] and s["topics"][0]["cards"] > 0  # progress survived

    lesson = client.get(f"/api/topics/{limits}").json()
    assert lesson["lesson_md"].endswith("## More\nExtra section.")
    assert lesson["key_points"] == ["Limits point", "extra point"]
    assert "Limits Q0?" in client.fake.extended[1]["cards"]
    with db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards WHERE topic_id=?", (limits,)).fetchone()[0] == 4


def test_update_restores_topics_claude_dropped(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    first, second = [t["id"] for t in topics(client, sid)]
    client.fake.drop = {second}
    upload(client, sid, "More.")
    builder.build(sid, client.fake, fresh=False)
    assert [t["title"] for t in topics(client, sid)] == ["Limits", "Derivatives", "Integrals"]


def test_update_retries_failed_topics(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    tid = topics(client, sid)[1]["id"]
    with db.tx() as conn:
        conn.execute("UPDATE topics SET status='failed' WHERE id=?", (tid,))
        conn.execute("DELETE FROM cards WHERE topic_id=?", (tid,))
    assert client.get(f"/api/subjects/{sid}").json()["failed_topics"] == 1
    builder.build(sid, client.fake, fresh=False)  # no new files: just the retry
    t = topics(client, sid)[1]
    assert t["status"] == "ready" and t["id"] == tid
    assert not getattr(client.fake, "update_calls", 0)
    with db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards WHERE topic_id=?", (tid,)).fetchone()[0] == 3


def test_fresh_build_resets(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    client.post(f"/api/topics/{topics(client, sid)[0]['id']}/complete")
    builder.build(sid, client.fake, fresh=True)
    assert not any(t["lesson_done"] for t in topics(client, sid))


def chat(client, sid, message, topic_id=None):
    r = client.post(f"/api/subjects/{sid}/chat", json={"message": message, "topic_id": topic_id})
    return [json.loads(line) for line in r.text.splitlines()]


def test_chat_threads(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    tid = topics(client, sid)[0]["id"]

    events = chat(client, sid, "What is a limit?", tid)
    assert "".join(e.get("text", "") for e in events) == "You asked: What is a limit?"
    assert events[-1] == {"done": True}
    chat(client, sid, "And again?", tid)
    assert client.fake.chat_args == ("Limits", ["What is a limit?", "You asked: What is a limit?"], "And again?")

    # The subject-wide thread is separate from the topic's.
    chat(client, sid, "Overview?")
    assert client.fake.chat_args == (None, [], "Overview?")
    assert len(client.get(f"/api/subjects/{sid}/chat?topic_id={tid}").json()["messages"]) == 4
    assert len(client.get(f"/api/subjects/{sid}/chat").json()["messages"]) == 2
    client.delete(f"/api/subjects/{sid}/chat?topic_id={tid}")
    assert client.get(f"/api/subjects/{sid}/chat?topic_id={tid}").json()["messages"] == []


def test_chat_reports_errors(client):
    from lectern.ai import AIError

    sid = make_subject(client)
    upload(client, sid)

    def broken(*a):
        raise AIError("Claude is rate-limiting us.")
        yield
    client.fake.chat = broken
    assert chat(client, sid, "hi") == [{"error": "Claude is rate-limiting us."}]
    assert client.get(f"/api/subjects/{sid}/chat").json()["messages"] == []


def test_exam(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    qs = client.get(f"/api/subjects/{sid}/exam?n=4").json()["questions"]
    assert len(qs) == 4 and {q["topic"] for q in qs} == {"Limits", "Derivatives"}  # spread over topics
    assert "answer_index" not in qs[0]

    answers = []
    for q in qs:
        if q["kind"] == "mcq":
            answers.append({"question_id": q["id"], "answer": "2"})
        else:
            answers.append({"question_id": q["id"], "answer": ""})
    r = client.post(f"/api/subjects/{sid}/exam", json={"answers": answers}).json()
    mcqs = sum(q["kind"] == "mcq" for q in qs)
    assert r["score"] == round(mcqs / 4, 3)
    assert {t["topic"] for t in r["topics"]} == {"Limits", "Derivatives"}
    assert all("model_answer" in x for x in r["results"])

    one = client.get(f"/api/subjects/{sid}/exam?n=40&topics={qs[0]['topic_id']}").json()["questions"]
    assert {q["topic_id"] for q in one} == {qs[0]["topic_id"]} and len(one) == 3


def test_review_all_subjects(client):
    a, b = make_subject(client, "Calculus"), make_subject(client, "Physics")
    for sid in (a, b):
        upload(client, sid)
        build(client, sid)
        client.post(f"/api/topics/{topics(client, sid)[0]['id']}/complete")
    cards = client.get("/api/review").json()["cards"]
    assert {c["subject"] for c in cards} == {"Calculus", "Physics"}


def test_password(client, monkeypatch):
    monkeypatch.setattr(api, "PASSWORD", "hunter2")
    monkeypatch.setenv("LECTERN_SECURE_COOKIE", "0")
    assert client.get("/api/subjects").status_code == 401
    assert client.get("/api/session").json() == {"signed_in": False, "password_required": True}
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    assert client.get("/api/subjects").status_code == 200


def test_export_for_claude_project(client):
    sid = make_subject(client, "MATH1131 Calculus")
    upload(client, sid)
    build(client, sid)
    tid = topics(client, sid)[0]["id"]
    client.post(f"/api/topics/{tid}/complete")
    q = client.get(f"/api/subjects/{sid}/practice").json()["questions"][0]
    client.post(f"/api/questions/{q['id']}/answer", json={"answer": "0" if q["kind"] == "mcq" else "no idea"})

    r = client.get(f"/api/subjects/{sid}/export")
    assert r.headers["content-disposition"] == 'attachment; filename="math1131-calculus.md"'
    md = r.text
    assert md.startswith("# MATH1131 Calculus: study pack")
    assert "| 1 | Limits (weak) | " in md and "| 2 | Derivatives | 0% | no | 0/3 |" in md
    assert "Recent wrong or partly-right answers" in md
    assert "### 1. Limits" in md and "- Q: Limits Q0?\n  A: A0" in md
    assert "*Answer:* C. c" in md
    assert "## Source material" not in md

    full = client.get(f"/api/subjects/{sid}/export?material=true")
    assert "with-material" in full.headers["content-disposition"]
    assert "### notes.txt" in full.text and "Derivatives are slopes." in full.text


def test_unreadable_image_pages_dont_fail_the_build(client):
    from lectern.ai import AIError

    def refuse(*a):
        raise AIError("DeepSeek rejected the request (400): images not supported")
    client.fake.transcribe = refuse
    sid = make_subject(client)
    r = client.post(f"/api/subjects/{sid}/documents",
                    files=[("files", ("scan.pdf", make_pdf(RULE, ""), "application/pdf"))])
    doc = r.json()["documents"][0]
    build(client, sid)
    s = client.get(f"/api/subjects/{sid}").json()
    assert s["build_status"] == "built"
    d = s["documents"][0]
    assert d["image_pages"] == [] and "images not supported" in d["warning"] and d["id"] == doc["id"]
