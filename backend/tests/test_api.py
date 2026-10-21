import time

from lectern import builder, db


def make_subject(client, name="Calculus"):
    return client.post("/api/subjects", json={"name": name}).json()["id"]


def upload(client, sid, text="Limits describe approach.\n\nDerivatives are slopes."):
    files = [("files", ("notes.txt", text.encode(), "text/plain")),
             ("files", ("more.txt", b"The derivative is the slope of the tangent.", "text/plain"))]
    return client.post(f"/api/subjects/{sid}/documents", files=files, data={"kind": "notes"})


def build(client, sid):
    builder.build(sid, client.fake)  # run inline rather than on a thread


def test_subjects_are_separate(client):
    a, b = make_subject(client, "Calculus"), make_subject(client, "Biology")
    upload(client, a)
    build(client, a)
    subjects = {s["name"]: s for s in client.get("/api/subjects").json()}
    assert subjects["Calculus"]["topics"] == 2 and subjects["Calculus"]["new"] == 6
    assert subjects["Biology"]["topics"] == 0 and subjects["Biology"]["documents"] == 0
    assert client.get(f"/api/subjects/{b}/review").json()["cards"] == []


def test_upload_rejects_unsupported(client):
    sid = make_subject(client)
    r = client.post(f"/api/subjects/{sid}/documents",
                    files=[("files", ("x.key", b"..", "application/octet-stream"))])
    assert r.status_code == 422 and "supported" in r.json()["detail"]


def test_build_needs_material(client):
    sid = make_subject(client)
    assert client.post(f"/api/subjects/{sid}/build").status_code == 422


def test_build_endpoint_runs_in_background(client):
    sid = make_subject(client)
    upload(client, sid)
    assert client.post(f"/api/subjects/{sid}/build").status_code == 202
    for _ in range(100):
        if client.get(f"/api/subjects/{sid}").json()["build_status"] == "built":
            break
        time.sleep(0.02)
    s = client.get(f"/api/subjects/{sid}").json()
    assert s["build_status"] == "built" and s["build_progress"] == 1
    assert client.fake.topic_calls[0] == 0  # first topic primes the cache before the rest


def test_build_course(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    s = client.get(f"/api/subjects/{sid}").json()
    assert [t["title"] for t in s["topics"]] == ["Limits", "Derivatives"]
    assert s["topics"][0]["sources"] == ["notes.txt"]  # bogus source id dropped
    assert s["next"] == {"action": "learn", "topic_id": s["topics"][0]["id"], "label": "Learn: Limits"}

    topic = client.get(f"/api/topics/{s['topics'][0]['id']}").json()
    assert topic["lesson_md"].startswith("# Limits") and topic["next"]["title"] == "Derivatives"
    with db.tx() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM questions WHERE topic_id=?", (topic["id"],))]
    assert kinds == ["mcq", "short", "short"]


def test_learning_loop(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    tid = client.get(f"/api/subjects/{sid}").json()["topics"][0]["id"]

    # New cards wait until the lesson has been read.
    assert client.get(f"/api/subjects/{sid}/review").json()["cards"] == []
    client.post(f"/api/topics/{tid}/complete")
    cards = client.get(f"/api/subjects/{sid}/review").json()["cards"]
    assert len(cards) == 3
    for c in cards:
        assert client.post(f"/api/cards/{c['id']}/grade", json={"grade": "good"}).status_code == 200
    assert client.get(f"/api/subjects/{sid}/review").json()["cards"] == []
    assert client.post(f"/api/cards/{cards[0]['id']}/grade", json={"grade": "meh"}).status_code == 422

    qs = client.get(f"/api/subjects/{sid}/practice").json()["questions"]
    assert len(qs) == 3 and "answer_index" not in qs[0] and "model_answer" not in qs[0]
    mcq = next(q for q in qs if q["kind"] == "mcq")
    assert client.post(f"/api/questions/{mcq['id']}/answer", json={"answer": "1"}).json()["score"] == 0
    assert client.post(f"/api/questions/{mcq['id']}/answer", json={"answer": "2"}).json()["score"] == 1
    short = next(q for q in qs if q["prompt"].endswith("short"))
    r = client.post(f"/api/questions/{short['id']}/answer", json={"answer": "it's the slope"}).json()
    assert r["score"] == 1 and r["model_answer"] == "slope"

    # Answered-correctly questions drop out of practice; the wrong-kind one remains.
    remaining = client.get(f"/api/subjects/{sid}/practice").json()["questions"]
    assert [q["prompt"] for q in remaining] == ["Limits broken"]

    t = client.get(f"/api/subjects/{sid}").json()["topics"][0]
    assert t["attempted"] == 2 and t["practice"] == round(2 / 3, 3)
    assert 0 < t["mastery"] < 0.8


def test_rebuild_after_new_upload_is_flagged(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    with db.tx() as conn:
        conn.execute("UPDATE documents SET created_at=datetime('now','-2 hours') WHERE subject_id=?", (sid,))
        conn.execute("UPDATE subjects SET built_at=datetime('now','-1 hour') WHERE id=?", (sid,))
    assert client.get(f"/api/subjects/{sid}").json()["stale"] is False
    upload(client, sid, "Integrals are areas.")
    assert client.get(f"/api/subjects/{sid}").json()["stale"] is True
    build(client, sid)
    with db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM topics WHERE subject_id=?", (sid,)).fetchone()[0] == 2


def test_delete_subject_cascades(client):
    sid = make_subject(client)
    upload(client, sid)
    build(client, sid)
    assert client.delete(f"/api/subjects/{sid}").status_code == 204
    with db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
