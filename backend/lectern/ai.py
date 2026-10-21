"""Every Claude call the tutor makes: plan the course, write a topic, mark an answer."""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anthropic

MODEL = os.environ.get("LECTERN_MODEL", "claude-opus-5-5")
# Claude reads up to 1M tokens; leave room for instructions and output.
MAX_MATERIAL_CHARS = 3_000_000

SYSTEM = """You are a tutor building a course from a student's own lecture slides and textbook.

Teach from the material you are given. When it is thin on a point, you may add standard \
background a lecturer would expect students to know, but never contradict the material, and \
prefer its notation, terms and examples. Every source id you cite must be one of the [S…] ids \
in the material.

Write for a university student: clear, concrete, no filler. Use Markdown. Write maths in LaTeX \
between $…$ (inline) or $$…$$ (display)."""


class AIError(RuntimeError):
    pass


@contextmanager
def _api_errors():
    """Turn SDK errors into messages a student can act on."""
    try:
        yield
    except anthropic.AuthenticationError as e:
        raise AIError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise AIError("Claude is rate-limiting us. Try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude returned an error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Couldn't reach Claude. Check the network connection.") from e


FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


def _strict(schema: dict) -> dict:
    """Structured outputs need every object closed and every property required."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        schema["required"] = list(schema["properties"])
        for prop in schema["properties"].values():
            _strict(prop)
    elif schema.get("type") == "array":
        _strict(schema["items"])
    return schema


SOURCES = {"type": "array", "items": {"type": "integer"}, "description": "S-ids of the chunks this draws on"}

OUTLINE_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "subject_summary": {"type": "string"},
        "topics": {
            "type": "array",
            "description": "In teaching order: prerequisites first",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string", "description": "One or two sentences on what this topic covers"},
                    "sources": SOURCES,
                },
            },
        },
    },
})

TOPIC_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "lesson_md": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "flashcards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                    "source": {"type": "integer"},
                },
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["mcq", "short"]},
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "4 options for mcq; empty for short"},
                    "answer_index": {"type": "integer", "description": "Index of the correct option for mcq; -1 for short"},
                    "model_answer": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source": {"type": "integer"},
                },
            },
        },
    },
})

UPDATE_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "description": "The whole updated course in teaching order",
            "items": {
                "type": "object",
                "properties": {
                    "existing_id": {"type": "integer", "description": "id of the existing topic this is, or -1 if new"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "sources": SOURCES,
                    "extend": {
                        "type": "boolean",
                        "description": "Existing topic that the new material adds substantial content to",
                    },
                },
            },
        },
    },
})

TRANSCRIBE_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "1-based page number within the attached PDF"},
                    "text": {"type": "string"},
                },
            },
        },
    },
})

MARK_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "score": {"type": "number", "description": "0 to 1"},
        "feedback": {"type": "string"},
    },
})


def material_text(chunks: list[dict]) -> str:
    return "\n\n".join(f"[S{c['id']}] {c['label']}\n{c['text']}" for c in chunks)


class Tutor:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def _call(self, *, messages: list, schema: dict, effort: str, max_tokens: int = 32000) -> dict:
        with _api_errors(), self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=SYSTEM,
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            **FALLBACK,
        ) as stream:
            msg = stream.get_final_message()

        if msg.stop_reason == "refusal":
            raise AIError("Claude declined to process this material.")
        if msg.stop_reason == "max_tokens":
            raise AIError("Claude's answer was cut off before it finished.")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            raise AIError("Claude returned no answer.")
        return json.loads(text)

    @staticmethod
    def _material_block(material: str) -> dict:
        # Identical across every call in a build, so cache it: the first topic pays to
        # read the material, the rest read it from cache at a tenth of the price.
        return {
            "type": "text",
            "text": f"<material>\n{material}\n</material>",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }

    def outline(self, subject: str, material: str) -> dict[str, Any]:
        return self._call(
            effort="high",
            messages=[{"role": "user", "content": [
                self._material_block(material),
                {"type": "text", "text": (
                    f"Subject: {subject}\n\n"
                    "Plan a course that covers everything in this material. Split it into topics a "
                    "student can learn in 15–30 minutes each (usually 6–30 topics, more for a whole "
                    "textbook). Order them so each topic only relies on earlier ones. Merge material "
                    "that the slides and textbook both cover into the same topic."
                )},
            ]}],
            schema=OUTLINE_SCHEMA,
        )

    def topic(self, subject: str, material: str, outline: list[dict], index: int) -> dict[str, Any]:
        plan = "\n".join(
            f"{i + 1}. {t['title']}: {t['summary']}" for i, t in enumerate(outline)
        )
        t = outline[index]
        return self._call(
            effort="medium",
            messages=[{"role": "user", "content": [
                self._material_block(material),
                {"type": "text", "text": (
                    f"Subject: {subject}\n\nCourse plan:\n{plan}\n\n"
                    f"Write topic {index + 1}, \"{t['title']}\" ({t['summary']}). "
                    f"Its main sources are {', '.join(f'S{s}' for s in t['sources']) or 'spread through the material'}.\n\n"
                    "- lesson_md: teach the topic as a good tutor would, in 400–1200 words. Don't repeat "
                    "the topic title as a heading; the page already shows it. Build "
                    "intuition before formalism, include a worked example where the subject has them, "
                    "and point out the usual mistakes. Assume the student knows the earlier topics, "
                    "not the later ones.\n"
                    "- key_points: 3–7 one-line takeaways.\n"
                    "- flashcards: 6–15 cards for active recall. One fact per card; the front is a "
                    "question, never a bare term. Cover definitions, formulas, and the why.\n"
                    "- questions: 4–8 exam-style practice questions, mixing mcq (exactly 4 options, "
                    "plausible distractors) and short-answer questions that need reasoning or "
                    "calculation. Give a full model answer and an explanation of the method."
                )},
            ]}],
            schema=TOPIC_SCHEMA,
        )

    def update_outline(
        self, subject: str, material: str, existing: list[dict], new_files: list[str]
    ) -> dict[str, Any]:
        """Fit newly added files into an existing course without disturbing what's there."""
        current = "\n".join(f"[id {t['id']}] {t['title']}: {t['summary']}" for t in existing)
        return self._call(
            effort="high",
            messages=[{"role": "user", "content": [
                self._material_block(material),
                {"type": "text", "text": (
                    f"Subject: {subject}\n\nThe student already has this course, in order:\n{current}\n\n"
                    f"They have since added: {', '.join(new_files)}. Update the course to cover the "
                    "new material too. Return the whole course in teaching order:\n"
                    "- Keep every existing topic, with its existing_id. You may move it, but don't drop, "
                    "merge or retitle it; the student has progress on it.\n"
                    "- Where the new material adds substantial content to an existing topic, set extend "
                    "to true and list the new sources. Otherwise false.\n"
                    "- Add new topics (existing_id -1, extend false) for anything not yet covered, "
                    "each 15–30 minutes of learning, placed after their prerequisites."
                )},
            ]}],
            schema=UPDATE_SCHEMA,
        )

    def extend_topic(
        self, subject: str, material: str, topic: dict, sources: list[int], have: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Extra lesson section, cards and questions for an existing topic, from new material."""
        return self._call(
            effort="medium",
            messages=[{"role": "user", "content": [
                self._material_block(material),
                {"type": "text", "text": (
                    f"Subject: {subject}\n\nThe topic \"{topic['title']}\" ({topic['summary']}) already has a "
                    f"lesson with these key points:\n- " + "\n- ".join(have["key_points"]) + "\n\n"
                    "and flashcards asking:\n- " + "\n- ".join(have["cards"]) + "\n\n"
                    "and practice questions:\n- " + "\n- ".join(have["questions"]) + "\n\n"
                    f"New material on it has been added: {', '.join(f'S{s}' for s in sources)}. Write only "
                    "what's new:\n"
                    "- lesson_md: a section to append to the lesson, starting with a ## heading, 200–800 "
                    "words, teaching what the new material adds.\n"
                    "- key_points: 1–4 new takeaways.\n"
                    "- flashcards: 3–10 cards for the new content, none repeating the existing ones.\n"
                    "- questions: 2–5 new exam-style questions (mcq with exactly 4 options, or short)."
                )},
            ]}],
            schema=TOPIC_SCHEMA,
        )

    def transcribe(self, filename: str, pdf: bytes, pages: list[int]) -> dict[int, str]:
        """Read PDF pages that have no usable text layer. Returns {original page: text}."""
        result = self._call(
            effort="low",
            max_tokens=64000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf).decode(),
                }},
                {"type": "text", "text": (
                    f"These are pages from {filename}, a student's course material. For each page, "
                    "transcribe all the text, with maths in LaTeX, and describe every diagram, graph, "
                    "table or figure in enough detail that a student could learn from the description "
                    "alone. Skip pages that are blank or purely decorative."
                )},
            ]}],
            schema=TRANSCRIBE_SCHEMA,
        )
        out = {}
        for p in result["pages"]:
            if 1 <= p["page"] <= len(pages) and p["text"].strip():
                out[pages[p["page"] - 1]] = p["text"].strip()
        return out

    def chat(
        self, subject: str, material: str, topic: dict | None, history: list[dict], message: str
    ) -> Iterator[str]:
        """Stream the tutor's reply, a piece of text at a time."""
        focus = (
            f"The student is studying the topic \"{topic['title']}\". Its lesson:\n<lesson>\n"
            f"{topic['lesson_md']}\n</lesson>"
            if topic else "The student is asking about the subject as a whole."
        )
        intro = (
            f"Subject: {subject}\n\nYou are now the student's tutor in a chat. {focus}\n\n"
            "Answer from the material. Cite where things come from in parentheses using the labels in "
            "the material, like (Week 3.pdf, p.12). If something isn't in the material, say so before "
            "answering from general knowledge. Keep replies short and conversational unless asked for "
            "depth. If the student asks you to quiz them or says they don't get something, teach "
            "Socratically: one question at a time, and let them try before you explain."
        )
        # Material first and unchanged, so it shares the cache with the course build.
        messages: list[dict] = []
        for i, m in enumerate([*history, {"role": "user", "content": message}]):
            if i == 0:
                messages.append({"role": "user", "content": [
                    self._material_block(material),
                    {"type": "text", "text": f"{intro}\n\nStudent: {m['content']}"},
                ]})
            else:
                messages.append({"role": m["role"], "content": m["content"]})
        with _api_errors(), self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=messages,
            output_config={"effort": "low"},
            cache_control={"type": "ephemeral"},
            **FALLBACK,
        ) as stream:
            yield from stream.text_stream
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise AIError("Claude declined to answer that.")

    def mark(self, question: dict, answer: str) -> dict[str, Any]:
        result = self._call(
            effort="low",
            max_tokens=8000,
            messages=[{"role": "user", "content": (
                "Mark a student's answer to a practice question.\n\n"
                f"<question>{question['prompt']}</question>\n"
                f"<model_answer>{question['model_answer']}</model_answer>\n"
                f"<student_answer>{answer}</student_answer>\n\n"
                "Give score from 0 (wrong or blank) to 1 (fully correct); give partial credit for "
                "correct method with a slip. Accept any correct answer, not only the model one. "
                "In feedback, speak to the student in 1–4 sentences: what was right, what was "
                "missing or wrong, and how to fix it."
            )}],
            schema=MARK_SCHEMA,
        )
        result["score"] = min(1.0, max(0.0, float(result["score"])))
        return result
