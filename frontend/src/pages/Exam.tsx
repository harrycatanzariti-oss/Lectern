import { Check, Clock, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, ErrorNote, Markdown, Spinner, btnGhost, btnPrimary, card } from "../components/ui";
import { MASTERED, api, type ExamReport, type Question, type Subject } from "../lib/api";

const LENGTHS = [5, 10, 20];
const TIMES = [0, 15, 30, 60]; // minutes; 0 = untimed

function Setup({ subject, onStart }: { subject: Subject; onStart: (n: number, minutes: number, topics: number[]) => void }) {
  const ready = subject.topics.filter((t) => t.status === "ready");
  const [n, setN] = useState(10);
  const [minutes, setMinutes] = useState(30);
  const [topics, setTopics] = useState<number[]>(ready.map((t) => t.id));
  const toggle = (id: number) => setTopics((ts) => (ts.includes(id) ? ts.filter((t) => t !== id) : [...ts, id]));
  const chip = (on: boolean) =>
    `rounded-full px-3 py-1 text-sm ${on ? "bg-brand-50 font-medium text-brand-deep" : "text-neutral-500 hover:bg-neutral-100"}`;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to={`/s/${subject.id}`} className="text-sm text-neutral-500 hover:underline">
          ← {subject.name}
        </Link>
        <h1 className="mt-1 text-2xl font-bold">Mock exam</h1>
        <p className="mt-1 text-neutral-500">
          Mixed questions across the course, no hints, marked at the end. Short answers are marked by Claude.
        </p>
      </div>
      <div className={`${card} space-y-5 p-5`}>
        <div>
          <p className="mb-2 text-sm font-medium">Questions</p>
          <div className="flex gap-2">
            {LENGTHS.map((x) => (
              <button key={x} className={chip(n === x)} onClick={() => setN(x)}>
                {x}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Time limit</p>
          <div className="flex flex-wrap gap-2">
            {TIMES.map((x) => (
              <button key={x} className={chip(minutes === x)} onClick={() => setMinutes(x)}>
                {x ? `${x} min` : "Untimed"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium">Topics</p>
            <button
              className="text-sm text-brand-deep hover:underline"
              onClick={() => setTopics(topics.length === ready.length ? [] : ready.map((t) => t.id))}
            >
              {topics.length === ready.length ? "Clear" : "All"}
            </button>
          </div>
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {ready.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-neutral-50">
                <input type="checkbox" checked={topics.includes(t.id)} onChange={() => toggle(t.id)} className="accent-[var(--color-brand)]" />
                <span className="flex-1">{t.title}</span>
                {t.mastery >= MASTERED && <span className="text-xs text-neutral-400">mastered</span>}
              </label>
            ))}
          </div>
        </div>
        <button className={btnPrimary} disabled={!topics.length} onClick={() => onStart(n, minutes, topics)}>
          Start exam
        </button>
      </div>
    </div>
  );
}

function clock(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function Taking({
  questions,
  minutes,
  onSubmit,
}: {
  questions: Question[];
  minutes: number;
  onSubmit: (answers: Record<number, string>) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [left, setLeft] = useState(minutes * 60);
  const submitted = useRef(false);
  const answersRef = useRef(answers);
  answersRef.current = answers;

  const submit = useCallback(() => {
    if (submitted.current) return;
    submitted.current = true;
    onSubmit(answersRef.current);
  }, [onSubmit]);

  useEffect(() => {
    if (!minutes) return;
    const t = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, [minutes]);
  useEffect(() => {
    if (minutes && left <= 0) submit();
  }, [left, minutes, submit]);

  // Don't lose an exam in progress to a stray tab close.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const answered = questions.filter((q) => (answers[q.id] ?? "").trim() !== "").length;
  const set = (id: number, v: string) => setAnswers((a) => ({ ...a, [id]: v }));

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="sticky top-14 z-10 -mx-4 flex items-center justify-between border-b border-neutral-200 bg-neutral-50/95 px-4 py-3 backdrop-blur">
        <span className="text-sm text-neutral-500">
          {answered} of {questions.length} answered
        </span>
        {minutes > 0 && (
          <span className={`flex items-center gap-1.5 font-mono text-sm ${left < 60 ? "text-rose-700" : ""}`}>
            <Clock size={14} /> {clock(Math.max(0, left))}
          </span>
        )}
      </div>

      {questions.map((q, i) => (
        <section key={q.id} className={`${card} space-y-4 p-6`}>
          <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">
            Question {i + 1} · {q.topic}
          </p>
          <Markdown>{q.prompt}</Markdown>
          {q.kind === "mcq" ? (
            <div className="space-y-2">
              {q.options.map((o, j) => (
                <label
                  key={j}
                  className={`flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 ${answers[q.id] === String(j) ? "border-brand bg-brand-50" : "border-neutral-200 hover:border-neutral-400"}`}
                >
                  <input
                    type="radio"
                    name={`q${q.id}`}
                    checked={answers[q.id] === String(j)}
                    onChange={() => set(q.id, String(j))}
                    className="accent-[var(--color-brand)]"
                  />
                  <Markdown inline>{o}</Markdown>
                </label>
              ))}
            </div>
          ) : (
            <textarea
              value={answers[q.id] ?? ""}
              onChange={(e) => set(q.id, e.target.value)}
              rows={5}
              placeholder="Your answer and working"
              className="w-full rounded-xl border border-neutral-300 bg-white p-3 outline-none focus:border-brand"
            />
          )}
        </section>
      ))}

      <button
        className={btnPrimary}
        onClick={() => {
          if (answered < questions.length && !confirm(`${questions.length - answered} question(s) unanswered. Submit anyway?`)) return;
          submit();
        }}
      >
        Submit exam
      </button>
    </div>
  );
}

function Report({ subjectId, report, onAgain }: { subjectId: number; report: ExamReport; onAgain: () => void }) {
  const pct = Math.round(report.score * 100);
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className={`${card} p-6 text-center`}>
        <p className="text-sm text-neutral-500">Your score</p>
        <p className="text-5xl font-bold">{pct}%</p>
        <p className="mt-2 text-neutral-500">
          {pct >= 85 ? "Exam-ready on these topics." : pct >= 60 ? "Solid. Work on the weak topics below." : "Revisit the weak topics below, then try again."}
        </p>
      </div>

      <section className={`${card} space-y-3 p-5`}>
        <h2 className="font-semibold">By topic, weakest first</h2>
        {report.topics.map((t) => (
          <Link key={t.topic_id} to={`/t/${t.topic_id}`} className="block space-y-1 rounded-lg p-2 hover:bg-neutral-50">
            <div className="flex justify-between text-sm">
              <span>{t.topic}</span>
              <span className="text-neutral-500">
                {Math.round((t.score / t.n) * 100)}% · {t.n} q
              </span>
            </div>
            <Bar value={t.score / t.n} />
          </Link>
        ))}
      </section>

      {report.results.map((r, i) => {
        const right = r.score >= 0.99;
        return (
          <section key={r.id} className={`${card} space-y-3 p-6`}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">
                Question {i + 1} · {r.topic}
              </p>
              <span
                className={`flex items-center gap-1 text-sm font-medium ${right ? "text-emerald-700" : r.score > 0 ? "text-amber-800" : "text-rose-700"}`}
              >
                {right ? <Check size={15} /> : <X size={15} />} {Math.round(r.score * 100)}%
              </span>
            </div>
            <Markdown>{r.prompt}</Markdown>
            <div className="rounded-lg bg-neutral-100 px-3 py-2 text-sm">
              <p className="text-xs font-medium text-neutral-500">Your answer</p>
              {r.kind === "mcq" ? (
                r.answer ? <Markdown inline>{r.options[Number(r.answer)] ?? ""}</Markdown> : <p>—</p>
              ) : (
                <p className="whitespace-pre-wrap">{r.answer || "—"}</p>
              )}
            </div>
            {!right && <Markdown>{r.feedback}</Markdown>}
            {!right && r.kind === "short" && (
              <div>
                <p className="text-sm font-medium text-neutral-500">Model answer</p>
                <Markdown>{r.model_answer}</Markdown>
              </div>
            )}
            {!right && r.explanation && (
              <div>
                <p className="text-sm font-medium text-neutral-500">Why</p>
                <Markdown>{r.explanation}</Markdown>
              </div>
            )}
          </section>
        );
      })}

      <div className="flex gap-2">
        <button className={btnPrimary} onClick={onAgain}>
          New exam
        </button>
        <Link to={`/s/${subjectId}`} className={btnGhost}>
          Back to course
        </Link>
      </div>
    </div>
  );
}

export default function Exam() {
  const id = Number(useParams().id);
  const [subject, setSubject] = useState<Subject | null>(null);
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [minutes, setMinutes] = useState(0);
  const [stage, setStage] = useState<"setup" | "loading" | "taking" | "marking" | "unmarked" | "report">("setup");
  const pending = useRef<Record<number, string>>({});
  const [report, setReport] = useState<ExamReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.subject(id).then(setSubject, (e) => setError(e.message));
  }, [id]);

  const start = async (n: number, mins: number, topics: number[]) => {
    setStage("loading");
    setError("");
    try {
      const r = await api.exam(id, n, topics);
      if (!r.questions.length) throw new Error("These topics have no questions yet.");
      setQuestions(r.questions);
      setMinutes(mins);
      setStage("taking");
      window.scrollTo(0, 0);
    } catch (e) {
      setError((e as Error).message);
      setStage("setup");
    }
  };

  const submit = useCallback(
    async (answers: Record<number, string>) => {
      pending.current = answers;
      setStage("marking");
      window.scrollTo(0, 0);
      try {
        setReport(await api.submitExam(id, (questions ?? []).map((q) => ({ question_id: q.id, answer: answers[q.id] ?? "" }))));
        setStage("report");
      } catch (e) {
        setError((e as Error).message);
        setStage("unmarked"); // keep the answers; offer to try marking again
      }
    },
    [id, questions],
  );

  if (!subject) return error ? <ErrorNote error={error} /> : <Spinner />;
  return (
    <>
      {error && <div className="mx-auto mb-4 max-w-3xl"><ErrorNote error={error} /></div>}
      {stage === "setup" && <Setup subject={subject} onStart={start} />}
      {stage === "loading" && <Spinner label="Setting the exam…" />}
      {stage === "taking" && questions && <Taking questions={questions} minutes={minutes} onSubmit={submit} />}
      {stage === "marking" && <Spinner label="Marking your exam…" />}
      {stage === "unmarked" && (
        <button className={btnPrimary} onClick={() => submit(pending.current)}>
          Try marking again
        </button>
      )}
      {stage === "report" && report && <Report subjectId={id} report={report} onAgain={() => setStage("setup")} />}
    </>
  );
}
