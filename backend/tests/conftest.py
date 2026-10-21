import os
import tempfile

import pytest

os.environ["LECTERN_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from lectern import api, db  # noqa: E402


class FakeTutor:
    """Stands in for Claude: a fixed two-topic course, and marks answers by keyword."""

    def __init__(self):
        self.topic_calls = []

    def outline(self, subject, material):
        ids = [int(part.split("]")[0]) for part in material.split("[S")[1:]]
        return {"subject_summary": subject, "topics": [
            {"title": "Limits", "summary": "What a limit is", "sources": ids[:1] + [99999]},
            {"title": "Derivatives", "summary": "Rates of change", "sources": ids[1:2]},
        ]}

    def topic(self, subject, material, outline, index):
        self.topic_calls.append(index)
        title = outline[index]["title"]
        src = outline[index]["sources"][0] if outline[index]["sources"] else 0
        return {
            "lesson_md": f"# {title}\nLesson text.",
            "key_points": [f"{title} point"],
            "flashcards": [
                {"front": f"{title} Q{i}?", "back": f"A{i}", "source": src} for i in range(3)
            ],
            "questions": [
                {"kind": "mcq", "prompt": f"{title} mcq", "options": ["a", "b", "c", "d"], "answer_index": 2,
                 "model_answer": "c", "explanation": "because", "source": src},
                {"kind": "short", "prompt": f"{title} short", "options": [], "answer_index": -1,
                 "model_answer": "slope", "explanation": "method", "source": src},
                # Malformed mcq should be stored as a short-answer question.
                {"kind": "mcq", "prompt": f"{title} broken", "options": ["x"], "answer_index": 5,
                 "model_answer": "x", "explanation": "", "source": src},
            ],
        }

    def update_outline(self, subject, material, existing, new_files):
        self.update_calls = getattr(self, "update_calls", 0) + 1
        ids = [int(part.split("]")[0]) for part in material.split("[S")[1:]]
        kept = [{"existing_id": t["id"], "title": "renamed?", "summary": "", "sources": ids[-1:], "extend": i == 0}
                for i, t in enumerate(existing) if t["id"] not in self.drop]
        return {"topics": kept + [
            {"existing_id": -1, "title": "Integrals", "summary": "Areas", "sources": ids[-1:], "extend": False},
        ]}

    drop: set = set()

    def extend_topic(self, subject, material, topic, sources, have):
        self.extended = (topic["title"], have)
        return {
            "lesson_md": "## More\nExtra section.",
            "key_points": ["extra point"],
            "flashcards": [{"front": "Extra Q?", "back": "Extra A", "source": sources[0]}],
            "questions": [],
        }

    def transcribe(self, filename, images, pages):
        assert len(images) == len(pages)
        return {p: f"Diagram on page {p} of {filename}" for p in pages}

    def chat(self, subject, material, topic, history, message):
        self.chat_args = (topic["title"] if topic else None, [m["content"] for m in history], message)
        yield "You asked: "
        yield message

    def mark(self, question, answer):
        ok = question["model_answer"].lower() in answer.lower()
        return {"score": 1.0 if ok else 0.25, "feedback": "Good." if ok else "Mention the slope."}


@pytest.fixture
def client():
    db.DB_PATH.unlink(missing_ok=True)
    fake = FakeTutor()
    api.set_tutor(fake)
    with TestClient(api.app) as c:
        c.fake = fake
        yield c
