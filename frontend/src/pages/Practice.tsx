import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ErrorNote, Markdown, Spinner, btnGhost, btnPrimary, card } from "../components/ui";
import { api, type Marked, type Question } from "../lib/api";

export default function Practice() {
  const subjectId = Number(useParams().id);
  const [params] = useSearchParams();
  const topicId = params.get("topic") ? Number(params.get("topic")) : undefined;

  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [result, setResult] = useState<Marked | null>(null);
  const [marking, setMarking] = useState(false);
  const [scores, setScores] = useState<number[]>([]);
  const [error, setError] = useState("");

  const load = () => {
    setQuestions(null);
    setIndex(0);
    setScores([]);
    api.practice(subjectId, topicId).then((r) => setQuestions(r.questions), (e) => setError(e.message));
  };
  useEffect(load, [subjectId, topicId]);

  if (error) return <ErrorNote error={error} />;
  if (!questions) return <Spinner />;

  const back = topicId ? `/t/${topicId}` : `/s/${subjectId}`;
  const q = questions[index];

  if (!q) {
    const total = scores.reduce((a, b) => a + b, 0);
    return (
      <div className={`${card} mx-auto max-w-xl space-y-4 p-8 text-center`}>
        {scores.length ? (
          <>
            <p className="text-xl font-semibold">
              {Math.round((total / scores.length) * 100)}% on {scores.length} question{scores.length === 1 ? "" : "s"}
            </p>
            <p className="text-neutral-500">Questions you got wrong come back next time.</p>
          </>
        ) : (
          <>
            <p className="text-xl font-semibold">No questions waiting</p>
            <p className="text-neutral-500">
              {topicId ? "You've answered everything for this topic correctly." : "Read a lesson to unlock its practice questions."}
            </p>
          </>
        )}
        <div className="flex justify-center gap-2">
          {scores.length > 0 && (
            <button className={btnGhost} onClick={load}>
              More questions
            </button>
          )}
          <Link to={back} className={btnPrimary}>
            Back
          </Link>
        </div>
      </div>
    );
  }

  const submit = async () => {
    const answer = q.kind === "mcq" ? String(picked) : text;
    setMarking(true);
    try {
      const r = await api.answer(q.id, answer);
      setResult(r);
      setScores((s) => [...s, r.score]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setMarking(false);
    }
  };

  const next = () => {
    setResult(null);
    setPicked(null);
    setText("");
    setIndex((i) => i + 1);
  };

  const verdict = result && (result.score >= 0.99 ? "right" : result.score > 0 ? "partial" : "wrong");

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between text-sm text-neutral-500">
        <Link to={back} className="hover:underline">
          ← Back
        </Link>
        <span>
          Question {index + 1} of {questions.length}
        </span>
      </div>

      <div className={`${card} space-y-5 p-6`}>
        <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{q.topic}</p>
        <div className="text-lg">
          <Markdown>{q.prompt}</Markdown>
        </div>

        {q.kind === "mcq" ? (
          <div className="space-y-2">
            {q.options.map((o, i) => {
              const isAnswer = result && result.answer_index === i;
              const isWrongPick = result && picked === i && !isAnswer;
              return (
                <button
                  key={i}
                  disabled={!!result}
                  onClick={() => setPicked(i)}
                  className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition ${
                    isAnswer
                      ? "border-emerald-700 bg-emerald-50"
                      : isWrongPick
                        ? "border-rose-700 bg-rose-50"
                        : picked === i
                          ? "border-brand bg-brand-50"
                          : "border-neutral-200 hover:border-neutral-400"
                  }`}
                >
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-neutral-300 text-xs">
                    {isAnswer ? <Check size={14} /> : isWrongPick ? <X size={14} /> : String.fromCharCode(65 + i)}
                  </span>
                  <Markdown inline>{o}</Markdown>
                </button>
              );
            })}
          </div>
        ) : (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!!result}
            rows={6}
            placeholder="Write your answer and working. Claude marks it against the model answer."
            className="w-full rounded-xl border border-neutral-300 bg-white p-3 outline-none focus:border-brand"
          />
        )}

        {!result && (
          <button
            className={btnPrimary}
            onClick={submit}
            disabled={marking || (q.kind === "mcq" ? picked === null : !text.trim())}
          >
            {marking ? "Marking…" : "Check answer"}
          </button>
        )}
      </div>

      {result && (
        <div className={`${card} space-y-4 p-6`}>
          <p
            className={`font-semibold ${verdict === "right" ? "text-emerald-700" : verdict === "partial" ? "text-amber-800" : "text-rose-700"}`}
          >
            {verdict === "right" ? "Correct" : verdict === "partial" ? `Partly right (${Math.round(result.score * 100)}%)` : "Not quite"}
          </p>
          {q.kind === "short" && <Markdown>{result.feedback}</Markdown>}
          {q.kind === "short" && result.model_answer && (
            <div>
              <p className="text-sm font-medium text-neutral-500">Model answer</p>
              <Markdown>{result.model_answer}</Markdown>
            </div>
          )}
          {result.explanation && (
            <div>
              <p className="text-sm font-medium text-neutral-500">Why</p>
              <Markdown>{result.explanation}</Markdown>
            </div>
          )}
          {q.source && <p className="text-xs text-neutral-400">{q.source}</p>}
          <button className={btnPrimary} onClick={next}>
            {index + 1 < questions.length ? "Next question" : "Finish"}
          </button>
        </div>
      )}
    </div>
  );
}
