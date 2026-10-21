import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ErrorNote, Markdown, Spinner, btnPrimary, card } from "../components/ui";
import { api, type Card } from "../lib/api";

const GRADES = [
  { grade: "again", label: "Again", hint: "Forgot", key: "1" },
  { grade: "hard", label: "Hard", hint: "Struggled", key: "2" },
  { grade: "good", label: "Good", hint: "Got it", key: "3" },
  { grade: "easy", label: "Easy", hint: "Trivial", key: "4" },
];

export default function Review() {
  const subjectId = Number(useParams().id);
  const [params] = useSearchParams();
  const topicId = params.get("topic") ? Number(params.get("topic")) : undefined;
  const thenPractice = params.get("then") === "practice";
  const navigate = useNavigate();

  const [queue, setQueue] = useState<Card[] | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    api.review(subjectId, topicId).then((r) => setQueue(r.cards), (e) => setError(e.message));
  }, [subjectId, topicId]);

  const current = queue?.[0];

  const grade = useCallback(
    async (g: string) => {
      if (!current) return;
      try {
        await api.grade(current.id, g);
      } catch (e) {
        setError((e as Error).message);
        return;
      }
      setFlipped(false);
      setDone((n) => n + 1);
      // "Again" cards come back at the end of this session.
      setQueue((q) => (q ? [...q.slice(1), ...(g === "again" ? [q[0]] : [])] : q));
    },
    [current],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        setFlipped(true);
      } else if (flipped) {
        const g = GRADES.find((x) => x.key === e.key);
        if (g) grade(g.grade);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, grade]);

  if (error) return <ErrorNote error={error} />;
  if (!queue) return <Spinner />;

  const back = topicId ? `/t/${topicId}` : `/s/${subjectId}`;

  if (!current) {
    return (
      <div className={`${card} mx-auto max-w-xl space-y-4 p-8 text-center`}>
        <p className="text-xl font-semibold">{done ? `Done: ${done} card${done === 1 ? "" : "s"} reviewed` : "Nothing to review right now"}</p>
        <p className="text-neutral-500">
          {done ? "They'll come back just before you'd forget them." : "Read a lesson to unlock its flashcards, or come back when cards fall due."}
        </p>
        <div className="flex justify-center gap-2">
          {thenPractice && topicId ? (
            <button className={btnPrimary} onClick={() => navigate(`/s/${subjectId}/practice?topic=${topicId}`)}>
              Now try the practice questions
            </button>
          ) : (
            <Link to={back} className={btnPrimary}>
              Back
            </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between text-sm text-neutral-500">
        <Link to={back} className="hover:underline">
          ← Back
        </Link>
        <span>
          {done} done · {queue.length} left
        </span>
      </div>

      <div className="flip">
        <div className={`flip-inner ${flipped ? "flipped" : ""}`}>
          <button
            onClick={() => setFlipped(true)}
            className={`flip-face ${card} flex min-h-72 w-full flex-col justify-between p-8 text-left`}
            aria-label="Show answer"
          >
            <span className="text-xs font-medium uppercase tracking-wide text-neutral-400">{current.topic}</span>
            <div className="py-6 text-xl font-medium">
              <Markdown>{current.front}</Markdown>
            </div>
            <span className="text-sm text-neutral-400">Click or press space to reveal</span>
          </button>
          <div className={`flip-face flip-back ${card} flex flex-col justify-between overflow-auto p-8`}>
            <div className="text-sm text-neutral-500">
              <Markdown>{current.front}</Markdown>
            </div>
            <div className="py-4 text-lg">
              <Markdown>{current.back}</Markdown>
            </div>
            {current.source && <span className="text-xs text-neutral-400">{current.source}</span>}
          </div>
        </div>
      </div>

      {flipped ? (
        <div className="grid grid-cols-4 gap-2">
          {GRADES.map((g) => (
            <button
              key={g.grade}
              onClick={() => grade(g.grade)}
              className={`${card} px-2 py-3 text-center hover:border-brand hover:bg-brand-50`}
            >
              <span className="block font-medium">{g.label}</span>
              <span className="text-xs text-neutral-500">
                {g.hint} · {g.key}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-center text-sm text-neutral-500">Say the answer to yourself before you flip. That's what makes it stick.</p>
      )}
    </div>
  );
}
