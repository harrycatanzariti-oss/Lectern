"""The DeepSeek client, against a fake server."""
import json

import httpx
import pytest

from lectern import ai


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")


def tutor(*replies):
    """A Tutor whose server answers with these replies in turn, recording each request."""
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        reply = replies[len(requests) - 1]
        if isinstance(reply, httpx.Response):
            return reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    t = ai.Tutor(httpx.Client(transport=httpx.MockTransport(handle)))
    t.requests = requests
    return t


GOOD_MARK = {"score": 0.5, "feedback": "Half right."}
QUESTION = {"prompt": "What is 2+2?", "model_answer": "4"}


def test_request_shape():
    t = tutor(GOOD_MARK)
    assert t.mark(QUESTION, "3") == GOOD_MARK
    body = t.requests[0]
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"][0] == {"role": "system", "content": ai.SYSTEM}
    assert '"feedback"' in body["messages"][1]["content"]  # schema is in the prompt
    assert "JSON" in body["messages"][1]["content"]  # DeepSeek's JSON mode requires the word


def test_material_leads_the_prompt_for_caching():
    t = tutor({"subject_summary": "s", "topics": []}, {"subject_summary": "s", "topics": []})
    t.outline("Calc", "[S1] a\nlimits")
    t.update_outline("Calc", "[S1] a\nlimits", [], ["b.pdf"])
    first, second = (r["messages"][1]["content"] for r in t.requests)
    prefix = "<material>\n[S1] a\nlimits\n</material>"
    assert first.startswith(prefix) and second.startswith(prefix)


def test_coerces_harmless_drift():
    t = tutor({"score": "1", "feedback": "Yes."})
    assert t.mark(QUESTION, "4")["score"] == 1.0
    assert ai.conform({"a": 3.0}, ai._obj(a=ai.INT)) == {"a": 3}


def test_retries_once_on_wrong_shape():
    t = tutor({"score": 1}, GOOD_MARK)
    assert t.mark(QUESTION, "3") == GOOD_MARK
    retry = t.requests[1]["messages"]
    assert retry[-1]["role"] == "user" and "missing 'feedback'" in retry[-1]["content"]


def test_retries_once_on_empty_reply():
    t = tutor("", GOOD_MARK)
    assert t.mark(QUESTION, "3") == GOOD_MARK
    assert "empty" in t.requests[1]["messages"][-1]["content"]


def test_gives_up_after_two_bad_replies():
    t = tutor("not json", {"score": "high", "feedback": ""})
    with pytest.raises(ai.AIError, match="expected format"):
        t.mark(QUESTION, "3")


@pytest.mark.parametrize("status,message", [
    (401, "rejected the API key"), (402, "out of credit"), (429, "rate-limiting"), (503, "busy or down"),
])
def test_http_errors(status, message):
    t = tutor(httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ai.AIError, match=message):
        t.mark(QUESTION, "3")


def test_bad_request_says_why():
    t = tutor(httpx.Response(400, json={"error": {"message": "Model Not Exist"}}))
    with pytest.raises(ai.AIError, match="Model Not Exist"):
        t.mark(QUESTION, "3")


def test_missing_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ai.AIError, match="DEEPSEEK_API_KEY"):
        tutor(GOOD_MARK).mark(QUESTION, "3")


def test_cut_off_answer():
    t = ai.Tutor(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"choices": [{"message": {"content": "{\"sc"}, "finish_reason": "length"}]}))))
    with pytest.raises(ai.AIError, match="cut off"):
        t.mark(QUESTION, "3")


def test_transcribe_maps_back_to_pdf_pages():
    t = tutor({"pages": [{"page": 1, "text": "Fig 1"}, {"page": 2, "text": " "}, {"page": 9, "text": "x"}]})
    assert t.transcribe("w1.pdf", [b"png1", b"png2"], [4, 7]) == {4: "Fig 1"}
    content = t.requests[0]["messages"][1]["content"]
    images = [c for c in content if c["type"] == "image_url"]
    assert len(images) == 2 and images[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_chat_streams():
    events = [{"choices": [{"delta": {"role": "assistant"}}]},
              {"choices": [{"delta": {"content": "A limit "}}]},
              {"choices": [{"delta": {"content": "is…"}}]}]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    t = ai.Tutor(httpx.Client(transport=httpx.MockTransport(handle)))
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert "".join(t.chat("Calc", "[S1] x", None, history, "What's a limit?")) == "A limit is…"
    msgs = seen[0]["messages"]
    assert seen[0]["stream"] is True
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"].startswith("<material>") and msgs[1]["content"].endswith("Student: hi")


def test_chat_error_before_streaming():
    t = ai.Tutor(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, json={}))))
    with pytest.raises(ai.AIError, match="out of credit"):
        list(t.chat("Calc", "x", None, [], "hi"))
