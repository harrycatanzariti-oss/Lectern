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
    assert "| 1 | Unit 1: Calculus | Limits (weak) | " in md
    assert "| 2 | Unit 1: Calculus | Derivatives | 0% | no | 0/3 |" in md
    assert "Recent wrong or partly-right answers" in md
    assert "### 1. Limits" in md and "- Q: Limits Q0?\n  A: A0" in md
    assert "*Answer:* C. c" in md
    assert "## Source material" not in md
    assert "## Syllabus: what they need to know" in md and "- Final exam (60%): 3-hour exam." in md
    assert "**The chain rule** (medium importance; their confidence: unrated; assessed in Final exam)" in md

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


def outline_upload(client, sid, text="Unit 1: limits, derivatives. Unit 2: Taylor series."):
    return client.post(f"/api/subjects/{sid}/documents", data={"kind": "outline"},
                       files=[("files", ("syllabus.md", text.encode(), "text/markdown"))])


def test_dashboard_groups_topics_into_units(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    s = client.get(f"/api/subjects/{sid}").json()
    assert [u["title"] for u in s["units"]] == ["Unit 1: Calculus"]
    assert s["units"][0]["topic_ids"] == [t["id"] for t in s["topics"]]
    assert s["progress"] == {"mastery": 0.0, "topics": 2, "mastered": 0, "covered": 2, "missing": 0,
                             "lessons_read": 0}


def test_course_outline_shows_gaps_then_fills_them(client):
    sid = make_subject(client)
    upload(client, sid)
    assert outline_upload(client, sid).status_code == 201
    build(client, sid)
    assert client.fake.outline_files == ["syllabus.md"]

    s = client.get(f"/api/subjects/{sid}").json()
    gap = s["topics"][2]
    assert (gap["title"], gap["status"], gap["unit"]) == ("Taylor series", "missing", "Unit 2: Series")
    assert [u["title"] for u in s["units"]] == ["Unit 1: Calculus", "Unit 2: Series"]
    assert s["units"][1]["missing"] == 1 and s["progress"]["covered"] == 2 and s["progress"]["missing"] == 1
    assert "1 syllabus item not in your material yet" in s["build_message"]
    with db.tx() as conn:  # nothing was written for the gap
        assert conn.execute("SELECT COUNT(*) FROM cards WHERE topic_id=?", (gap["id"],)).fetchone()[0] == 0
    assert gap["id"] not in [q["topic_id"] for q in client.get(f"/api/subjects/{sid}/exam?n=40").json()["questions"]]
    assert client.get("/api/subjects").json()[0]["missing"] == 1

    # New material arrives that covers the gap.
    client.fake.fill_gaps = True
    upload(client, sid, "Taylor series approximate functions with polynomials.")
    builder.build(sid, client.fake, fresh=False)
    assert [t["status"] for t in client.fake.update_existing] == ["ready", "ready", "missing"]
    s = client.get(f"/api/subjects/{sid}").json()
    filled = next(t for t in s["topics"] if t["id"] == gap["id"])
    assert filled["status"] == "ready" and filled["unit"] == "Unit 2: Series"  # unit kept
    assert s["progress"]["missing"] == 0
    with db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards WHERE topic_id=?", (gap["id"],)).fetchone()[0] == 3


def test_old_topics_without_units_get_one_on_update(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    with db.tx() as conn:
        conn.execute("UPDATE topics SET unit='' WHERE subject_id=?", (sid,))
    assert [u["title"] for u in client.get(f"/api/subjects/{sid}").json()["units"]] == ["Course"]
    upload(client, sid, "More.")
    builder.build(sid, client.fake, fresh=False)
    units = [u["title"] for u in client.get(f"/api/subjects/{sid}").json()["units"]]
    assert units == ["renamed unit?", "Unit 3: Integration"]


def test_syllabus_is_built_with_the_course(client):
    sid = make_subject(client)
    upload(client, sid)
    outline_upload(client, sid)
    build(client, sid)
    assert client.fake.syllabus_args["outline_files"] == ["syllabus.md"]
    ids = [t["id"] for t in topics(client, sid)]

    syl = client.get(f"/api/subjects/{sid}/syllabus").json()
    assert syl["has_outline"] is True
    assert [(a["name"], a["weight"]) for a in syl["assessments"]] == [("Final exam", 60), ("Quizzes", None)]
    assert [s["title"] for s in syl["sections"]] == ["Limits and continuity", "Differentiation"]
    first = syl["sections"][0]["items"][0]
    assert first["title"] == "The epsilon-delta definition of a limit"
    assert first["assessed_in"] == ["Final exam"]  # unknown assessment names dropped
    assert [t["id"] for t in first["topics"]] == [ids[0]]  # unknown topic ids dropped
    assert first["mastery"] == 0.0 and first["confidence"] == 0
    assert syl["sections"][0]["items"][1]["mastery"] is None  # no linked topic
    assert syl["progress"] == {"items": 3, "mastery": 0.0, "confident": 0, "rated": 0, "high": 1}


def test_confidence_is_kept_when_the_syllabus_is_redrafted(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    item = client.get(f"/api/subjects/{sid}/syllabus").json()["sections"][1]["items"][0]
    assert client.patch(f"/api/syllabus/items/{item['id']}", json={"confidence": 3}).status_code == 200
    assert client.patch(f"/api/syllabus/items/{item['id']}", json={"confidence": 7}).status_code == 422

    upload(client, sid, "More.")
    builder.build(sid, client.fake, fresh=False)  # an update redrafts the syllabus
    assert client.fake.syllabus_args["existing"][2] == {"section": "Differentiation", "item": "The chain rule",
                                                       "confidence": 3}
    syl = client.get(f"/api/subjects/{sid}/syllabus").json()
    assert syl["sections"][1]["items"][0]["confidence"] == 3
    assert syl["progress"]["confident"] == 1 and syl["progress"]["rated"] == 1


def test_rebuild_syllabus_on_its_own(client, monkeypatch):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    started = []
    monkeypatch.setattr(builder, "start", lambda s, t, fresh, syllabus_only=False: started.append(syllabus_only) or True)
    assert client.post(f"/api/subjects/{sid}/syllabus").status_code == 202 and started == [True]

    builder.rebuild_syllabus(sid, client.fake)
    s = client.get(f"/api/subjects/{sid}").json()
    assert (s["build_status"], s["build_message"]) == ("built", "Syllabus updated")
    assert len(topics(client, sid)) == 2  # the course itself is untouched


def test_failed_syllabus_doesnt_fail_the_build(client):
    from lectern.ai import AIError

    def broken(*a, **k):
        raise AIError("nope")
    client.fake.syllabus = broken
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    s = client.get(f"/api/subjects/{sid}").json()
    assert s["build_status"] == "built" and "Rebuild syllabus" in s["build_message"]
    assert client.get(f"/api/subjects/{sid}/syllabus").json()["sections"] == []
