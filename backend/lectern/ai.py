"""Every Claude call the tutor makes: plan the course, write a topic, mark an answer."""
from __future__ import annotations

import json
import os
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
        try:
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                system=SYSTEM,
                messages=messages,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise AIError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from e
        except anthropic.RateLimitError as e:
            raise AIError("Claude is rate-limiting us. Try again in a minute.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Claude returned an error ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Couldn't reach Claude. Check the network connection.") from e

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
