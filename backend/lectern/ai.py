"""Every AI call the tutor makes: plan the course, write a topic, mark an answer, chat.

Uses DeepSeek's OpenAI-compatible chat API. DeepSeek's JSON mode guarantees valid JSON
but not its shape, so each reply is checked against a schema here and retried once if
it doesn't match.
"""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

URL = "https://api.deepseek.com/chat/completions"
# Names DeepSeek has retired, and what replaced them (as in Otis).
RETIRED_MODELS = {"deepseek-chat": "deepseek-flash", "deepseek-reasoner": "deepseek-flash",
                  "deepseek-v4-flash": "deepseek-flash"}
MODEL = os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-flash"
MODEL = RETIRED_MODELS.get(MODEL, MODEL)
# deepseek-flash reads up to 1M tokens; leave room for instructions and output.
MAX_MATERIAL_CHARS = 3_000_000
# Thinking mode is on by default and much slower; these tasks don't need it.
NO_THINKING = {"thinking": {"type": "disabled"}}

SYSTEM = """You are a tutor building a course from a student's own lecture slides and textbook.

Teach from the material you are given. When it is thin on a point, you may add standard \
background a lecturer would expect students to know, but never contradict the material, and \
prefer its notation, terms and examples. Every source id you cite must be one of the [S…] ids \
in the material.

Write for a university student: clear, concrete, no filler. Use Markdown. Write maths in LaTeX \
between $…$ (inline) or $$…$$ (display)."""


class AIError(RuntimeError):
    pass


def _status_error(resp: httpx.Response) -> AIError:
    """A message a student can act on, from a failed DeepSeek response."""
    code = resp.status_code
    if code == 401:
        return AIError("DeepSeek rejected the API key. Check DEEPSEEK_API_KEY.")
    if code == 402:
        return AIError("The DeepSeek account is out of credit. Top it up at platform.deepseek.com.")
    if code == 429:
        return AIError("DeepSeek is rate-limiting us. Try again in a minute.")
    if code >= 500:
        return AIError("DeepSeek is busy or down right now. Try again in a few minutes.")
    try:
        detail = resp.json()["error"]["message"]
    except Exception:
        detail = resp.text[:200]
    return AIError(f"DeepSeek rejected the request ({code}): {detail}")


@contextmanager
def _network_errors():
    try:
        yield
    except httpx.TimeoutException as e:
        raise AIError("DeepSeek took too long to answer. Try again.") from e
    except httpx.HTTPError as e:
        raise AIError("Couldn't reach DeepSeek. Check the network connection.") from e


# ---------- reply shapes ----------
# A small subset of JSON Schema: objects (every property required), arrays, strings,
# integers, numbers, booleans and string enums. It's both shown to the model and used
# to check what comes back.

def _obj(**props: dict) -> dict:
    return {"type": "object", "properties": props}


def _arr(items: dict, description: str = "") -> dict:
    return {"type": "array", "items": items, **({"description": description} if description else {})}


STR = {"type": "string"}
INT = {"type": "integer"}
SOURCES = _arr(INT, "S-ids of the chunks this draws on")

UNIT = {"type": "string", "description": "The syllabus unit or module this topic belongs to"}
COVERED = {"type": "boolean", "description": "False if the material doesn't teach this yet (it's only on the syllabus)"}

OUTLINE_SCHEMA = _obj(
    subject_summary=STR,
    topics=_arr(_obj(
        unit=UNIT,
        title=STR,
        summary={"type": "string", "description": "One or two sentences on what this topic covers"},
        sources=SOURCES,
        covered=COVERED,
    ), "In teaching order: prerequisites first, each unit's topics together"),
)

TOPIC_SCHEMA = _obj(
    lesson_md=STR,
    key_points=_arr(STR),
    flashcards=_arr(_obj(front=STR, back=STR, source=INT)),
    questions=_arr(_obj(
        kind={"type": "string", "enum": ["mcq", "short"]},
        prompt=STR,
        options=_arr(STR, "4 options for mcq; empty for short"),
        answer_index={"type": "integer", "description": "Index of the correct option for mcq; -1 for short"},
        model_answer=STR,
        explanation=STR,
        source=INT,
    )),
)

UPDATE_SCHEMA = _obj(
    topics=_arr(_obj(
        existing_id={"type": "integer", "description": "id of the existing topic this is, or -1 if new"},
        unit=UNIT,
        title=STR,
        summary=STR,
        sources=SOURCES,
        covered=COVERED,
        extend={"type": "boolean", "description": "Existing topic that the new material adds substantial content to"},
    ), "The whole updated course in teaching order"),
)

TRANSCRIBE_SCHEMA = _obj(
    pages=_arr(_obj(
        page={"type": "integer", "description": "1-based position of the image in this message"},
        text=STR,
    )),
)

MARK_SCHEMA = _obj(
    score={"type": "number", "description": "0 to 1"},
    feedback=STR,
)


def conform(value: Any, schema: dict, path: str = "reply") -> Any:
    """Check value against schema, fixing harmless drift (3.0 for 3, "2" for 2).
    Raises ValueError saying what's wrong."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} should be an object")
        out = {}
        for key, sub in schema["properties"].items():
            if key not in value:
                raise ValueError(f"{path} is missing {key!r}")
            out[key] = conform(value[key], sub, f"{path}.{key}")
        return out
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} should be a list")
        return [conform(v, schema["items"], f"{path}[{i}]") for i, v in enumerate(value)]
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} should be a string")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} should be one of {schema['enum']}")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} should be true or false")
        return value
    if kind in ("integer", "number"):
        if isinstance(value, bool):
            raise ValueError(f"{path} should be a number")
        try:
            n = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{path} should be a number") from None
        if kind == "integer":
            if n != int(n):
                raise ValueError(f"{path} should be a whole number")
            return int(n)
        return n
    raise ValueError(f"unknown schema type {kind}")


def material_text(chunks: list[dict]) -> str:
    return "\n\n".join(f"[S{c['id']}] {c['label']}\n{c['text']}" for c in chunks)


class Tutor:
    def __init__(self, client: httpx.Client | None = None):
        # Topics can take a few minutes to write; connecting should be quick.
        self.client = client or httpx.Client(timeout=httpx.Timeout(600, connect=15))

    def _headers(self) -> dict:
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise AIError("DEEPSEEK_API_KEY isn't set on the server.")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _call(self, *, prompt: str | list, schema: dict, max_tokens: int = 16000, temperature: float = 0.3) -> dict:
        """One JSON reply. The material (if any) leads the prompt, unchanged between calls,
        so DeepSeek's automatic prefix cache serves it after the first call."""
        instructions = (
            "\n\nReply with a single JSON object matching this JSON Schema (every property is "
            f"required):\n{json.dumps(schema)}"
        )
        if isinstance(prompt, str):
            content: str | list = prompt + instructions
        else:
            content = [*prompt, {"type": "text", "text": instructions.strip()}]
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]

        for attempt in range(2):
            with _network_errors():
                resp = self.client.post(URL, headers=self._headers(), json={
                    **NO_THINKING,
                    "model": MODEL,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                })
            if resp.status_code != 200:
                raise _status_error(resp)
            choice = resp.json()["choices"][0]
            text = choice["message"].get("content") or ""
            if choice.get("finish_reason") == "length":
                raise AIError("DeepSeek's answer was cut off before it finished.")
            try:
                return conform(json.loads(text), schema)
            except ValueError as e:  # json.JSONDecodeError is a ValueError too
                problem = str(e) if text.strip() else "the reply was empty"
                if attempt:
                    raise AIError(f"DeepSeek's answer wasn't in the expected format ({problem}).") from e
                # Show it what went wrong and ask again.
                messages = [*messages, {"role": "assistant", "content": text or "{}"},
                            {"role": "user", "content": f"That JSON isn't right: {problem}. Reply again "
                                                        "with the complete JSON object."}]
        raise AssertionError("unreachable")

    @staticmethod
    def _with_material(material: str, task: str) -> str:
        return f"<material>\n{material}\n</material>\n\n{task}"

    @staticmethod
    def _syllabus_rules(outline_files: list[str]) -> str:
        """How to group topics into units, and what counts as covered."""
        if not outline_files:
            return (
                "Group the topics into units the way a course outline would (3–10 units, each a "
                "coherent block such as a chapter or a few weeks of lectures). Every topic is "
                "covered, since the material is all there is."
            )
        return (
            f"{', '.join(outline_files)} {'is' if len(outline_files) == 1 else 'are'} the official course "
            "outline. It's the syllabus: use its units/modules (and their names) as the units, and make "
            "sure every item it says students must learn becomes a topic. Where the rest of the "
            "material teaches an item, set covered true and cite those sources. Where nothing but the "
            "outline mentions it, still include it, with covered false and no sources, so the "
            "student can see the gap. Material the outline doesn't mention goes in the best-fitting unit."
        )

    def outline(self, subject: str, material: str, outline_files: list[str] = ()) -> dict[str, Any]:
        return self._call(
            prompt=self._with_material(material, (
                f"Subject: {subject}\n\n"
                "Plan a course that covers everything in this material. Split it into topics a "
                "student can learn in 15–30 minutes each (usually 6–30 topics, more for a whole "
                "textbook). Order them so each topic only relies on earlier ones. Merge material "
                "that the slides and textbook both cover into the same topic.\n\n"
                + self._syllabus_rules(list(outline_files))
            )),
            schema=OUTLINE_SCHEMA,
        )

    def topic(self, subject: str, material: str, outline: list[dict], index: int) -> dict[str, Any]:
        plan = "\n".join(
            f"{i + 1}. {t['title']}: {t['summary']}" for i, t in enumerate(outline)
        )
        t = outline[index]
        return self._call(
            prompt=self._with_material(material, (
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
                "question, never a bare term. Cover definitions, formulas, and the why. source is "
                "the number of the S-id it comes from.\n"
                "- questions: 4–8 exam-style practice questions, mixing mcq (exactly 4 options, "
                "plausible distractors) and short-answer questions that need reasoning or "
                "calculation. Give a full model answer and an explanation of the method."
            )),
            schema=TOPIC_SCHEMA,
        )

    def update_outline(
        self, subject: str, material: str, existing: list[dict], new_files: list[str],
        outline_files: list[str] = (),
    ) -> dict[str, Any]:
        """Fit newly added files into an existing course without disturbing what's there."""
        current = "\n".join(
            f"[id {t['id']}] ({t.get('unit') or 'no unit yet'}) {t['title']}: {t['summary']}"
            + (" [not covered by the material yet]" if t.get("status") == "missing" else "")
            for t in existing
        )
        return self._call(
            prompt=self._with_material(material, (
                f"Subject: {subject}\n\nThe student already has this course, in order:\n{current}\n\n"
                f"They have since added: {', '.join(new_files)}. Update the course to cover the "
                "new material too. Return the whole course in teaching order:\n"
                "- Keep every existing topic, with its existing_id. You may move it, but don't drop, "
                "merge or retitle it; the student has progress on it.\n"
                "- Where the new material adds substantial content to an existing topic, set extend "
                "to true and list the new sources. Otherwise false.\n"
                "- Add new topics (existing_id -1, extend false) for anything not yet covered, "
                "each 15–30 minutes of learning, placed after their prerequisites.\n"
                "- Give every topic a unit, keeping existing topics in their unit unless it has none.\n"
                "- A topic marked not covered becomes covered (true, with sources) once the material "
                "teaches it.\n\n"
                + self._syllabus_rules(list(outline_files))
            )),
            schema=UPDATE_SCHEMA,
        )

    def extend_topic(
        self, subject: str, material: str, topic: dict, sources: list[int], have: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Extra lesson section, cards and questions for an existing topic, from new material."""
        return self._call(
            prompt=self._with_material(material, (
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
            )),
            schema=TOPIC_SCHEMA,
        )

    def transcribe(self, filename: str, images: list[bytes], pages: list[int]) -> dict[int, str]:
        """Read page images (PNG) that had no usable text layer. Returns {original page: text}."""
        prompt: list[dict] = [{"type": "text", "text": (
            f"These {len(images)} images are pages from {filename}, a student's course material, in "
            "order. For each page, transcribe all the text, with maths in LaTeX, and describe every "
            "diagram, graph, table or figure in enough detail that a student could learn from the "
            "description alone. Skip pages that are blank or purely decorative."
        )}]
        for png in images:
            prompt.append({"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.standard_b64encode(png).decode(),
            }})
        result = self._call(prompt=prompt, schema=TRANSCRIBE_SCHEMA, max_tokens=32000, temperature=0)
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
        # Material first and unchanged, so the prefix cache serves it on every message.
        messages: list[dict] = [{"role": "system", "content": SYSTEM}]
        for i, m in enumerate([*history, {"role": "user", "content": message}]):
            content = self._with_material(material, f"{intro}\n\nStudent: {m['content']}") if i == 0 else m["content"]
            messages.append({"role": m["role"], "content": content})

        with _network_errors(), self.client.stream("POST", URL, headers=self._headers(), json={
            **NO_THINKING,
            "model": MODEL,
            "messages": messages,
            "max_tokens": 8000,
            "temperature": 0.5,
            "stream": True,
        }) as resp:
            if resp.status_code != 200:
                resp.read()
                raise _status_error(resp)
            # Server-sent events: "data: {json}" lines, ending with "data: [DONE]".
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0].get("delta", {})
                if delta.get("content"):
                    yield delta["content"]

    def mark(self, question: dict, answer: str) -> dict[str, Any]:
        result = self._call(
            max_tokens=2000,
            temperature=0,
            prompt=(
                "Mark a student's answer to a practice question.\n\n"
                f"<question>{question['prompt']}</question>\n"
                f"<model_answer>{question['model_answer']}</model_answer>\n"
                f"<student_answer>{answer}</student_answer>\n\n"
                "Give score from 0 (wrong or blank) to 1 (fully correct); give partial credit for "
                "correct method with a slip. Accept any correct answer, not only the model one. "
                "In feedback, speak to the student in 1–4 sentences: what was right, what was "
                "missing or wrong, and how to fix it."
            ),
            schema=MARK_SCHEMA,
        )
        result["score"] = min(1.0, max(0.0, result["score"]))
        return result
