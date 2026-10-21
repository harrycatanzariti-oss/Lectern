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

    def outline(self, subject, material, outline_files=()):
        ids = [int(part.split("]")[0]) for part in material.split("[S")[1:]]
        self.outline_files = list(outline_files)
        topics = [
            {"unit": "Unit 1: Calculus", "title": "Limits", "summary": "What a limit is",
             "sources": ids[:1] + [99999], "covered": True},
            {"unit": "Unit 1: Calculus", "title": "Derivatives", "summary": "Rates of change",
             "sources": ids[1:2], "covered": True},
        ]
        if outline_files:  # the syllabus lists something the material doesn't teach
            topics.append({"unit": "Unit 2: Series", "title": "Taylor series", "summary": "Approximating functions",
                           "sources": [], "covered": False})
        return {"subject_summary": subject, "topics": topics}

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

    def update_outline(self, subject, material, existing, new_files, outline_files=()):
        self.update_calls = getattr(self, "update_calls", 0) + 1
        self.update_existing = existing
        ids = [int(part.split("]")[0]) for part in material.split("[S")[1:]]
        kept = []
        for i, t in enumerate(existing):
            if t["id"] in self.drop:
                continue
            gap = t["status"] == "missing"
            kept.append({"existing_id": t["id"], "unit": "renamed unit?", "title": "renamed?", "summary": "",
                         "sources": ids[-1:] if (gap and self.fill_gaps) or not gap else [],
                         "covered": self.fill_gaps if gap else True, "extend": i == 0})
        return {"topics": kept + [
            {"existing_id": -1, "unit": "Unit 3: Integration", "title": "Integrals", "summary": "Areas",
             "sources": ids[-1:], "covered": True, "extend": False},
        ]}

    fill_gaps = False

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

    def restyle(self, subject, topic, level):
        self.restyle_calls = getattr(self, "restyle_calls", 0) + 1
        return f"Level {level}: {topic['lesson_md']}"

    def chat(self, subject, material, topic, history, message, level=3):
        self.chat_level = level
        self.chat_args = (topic["title"] if topic else None, [m["content"] for m in history], message)
        yield "You asked: "
        yield message

    def syllabus(self, subject, material, outline_files, topics, existing=()):
        self.syllabus_args = {"outline_files": list(outline_files), "topics": topics, "existing": list(existing)}
        ids = [t["id"] for t in topics]
        return {
            "assessments": [
                {"name": "Final exam", "weight": 60, "format": "3-hour exam", "criteria": "Full working shown"},
                {"name": "Quizzes", "weight": -1, "format": "weekly", "criteria": "Correct answers"},
            ],
            "sections": [
                {"title": "Limits and continuity", "outcome": "Evaluate limits and test continuity", "items": [
                    {"title": "The epsilon-delta definition of a limit", "detail": "State and use it",
                     "marking": "Proofs need explicit delta", "importance": "high",
                     "assessed_in": ["Final exam", "Made-up test"], "topic_ids": ids[:1] + [99999]},
                    {"title": "Why continuity matters", "detail": "IVT", "marking": "Short answer",
                     "importance": "low", "assessed_in": ["Quizzes"], "topic_ids": []},
                ]},
                {"title": "Differentiation", "outcome": "Differentiate functions", "items": [
                    {"title": "The chain rule", "detail": "Compositions", "marking": "Method marks",
                     "importance": "medium", "assessed_in": ["Final exam"], "topic_ids": ids[1:2]},
                ]},
            ],
        }

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
