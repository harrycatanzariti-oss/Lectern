import { AlertTriangle, ArrowRight, Check, FileText, Layers, PenLine, RefreshCw, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, ErrorNote, Spinner, btnGhost, btnPrimary, card, masteryLabel } from "../components/ui";
import { MASTERED, api, type Subject } from "../lib/api";

const KINDS = [
  { value: "slides", label: "Lecture slides" },
  { value: "textbook", label: "Textbook" },
  { value: "notes", label: "Notes" },
];

function Uploader({ subject, onUploaded }: { subject: Subject; onUploaded: () => void }) {
  const [kind, setKind] = useState("slides");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const send = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setErrors([]);
    try {
      const r = await api.upload(subject.id, files, kind);
      setErrors(r.errors);
      onUploaded();
    } catch (e) {
      setErrors([(e as Error).message]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {KINDS.map((k) => (
          <button
            key={k.value}
            onClick={() => setKind(k.value)}
            className={`rounded-full px-3 py-1 text-sm ${kind === k.value ? "bg-brand-50 font-medium text-brand-deep" : "text-neutral-500 hover:bg-neutral-100"}`}
          >
            {k.label}
          </button>
        ))}
      </div>
      <button
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          send(Array.from(e.dataTransfer.files));
        }}
        disabled={busy}
        className={`flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${over ? "border-brand bg-brand-50" : "border-neutral-300 hover:border-brand"}`}
      >
        {busy ? <Spinner label="Reading files…" /> : <Upload className="text-neutral-400" />}
        {!busy && (
          <>
            <span className="font-medium">Drop {KINDS.find((k) => k.value === kind)!.label.toLowerCase()} here or click to choose</span>
            <span className="text-sm text-neutral-500">PDF, PowerPoint (.pptx), .txt or .md. Add as many as you like.</span>
          </>
        )}
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept=".pdf,.pptx,.txt,.md"
        className="hidden"
        onChange={(e) => {
          send(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      {errors.map((e) => (
        <ErrorNote key={e} error={e} />
      ))}
    </div>
  );
}

function BuildPanel({ subject, onStarted }: { subject: Subject; onStarted: () => void }) {
  const [error, setError] = useState("");
  const building = subject.build_status === "building";
  const hasCourse = subject.topics.length > 0;

  const start = async () => {
    if (hasCourse && !confirm("Rebuilding writes a fresh course from all your files and resets your flashcard and practice progress for this subject. Continue?")) return;
    setError("");
    try {
      await api.build(subject.id);
      onStarted();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (building) {
    return (
      <div className="space-y-2">
        <Spinner label={subject.build_message || "Building…"} />
        <Bar value={subject.build_progress} />
        <p className="text-sm text-neutral-500">
          Claude is reading everything and writing lessons, flashcards and questions. This takes a few minutes; you can leave this page.
        </p>
      </div>
    );
  }
  const usable = subject.documents.some((d) => d.units > 0);
  return (
    <div className="space-y-3">
      {subject.build_status === "failed" && <ErrorNote error={subject.build_message} />}
      {subject.build_status === "built" && subject.build_message && !subject.stale && (
        <p className="text-sm text-neutral-500">{subject.build_message}</p>
      )}
      {subject.stale && (
        <p className="flex items-center gap-2 text-sm text-amber-800">
          <AlertTriangle size={15} /> You've added files since the course was built. Rebuild to include them.
        </p>
      )}
      <button className={hasCourse ? btnGhost : btnPrimary} onClick={start} disabled={!usable}>
        <RefreshCw size={15} /> {hasCourse ? "Rebuild course" : "Build my course"}
      </button>
      {error && <ErrorNote error={error} />}
    </div>
  );
}

export default function SubjectPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [subject, setSubject] = useState<Subject | null>(null);
  const [error, setError] = useState("");
  const [showFiles, setShowFiles] = useState(false);

  const load = useCallback(() => api.subject(id).then(setSubject, (e) => setError(e.message)), [id]);
  useEffect(() => {
    load();
  }, [load]);
  // Poll while a build runs.
  useEffect(() => {
    if (subject?.build_status !== "building") return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [subject?.build_status, load]);

  if (error) return <ErrorNote error={error} />;
  if (!subject) return <Spinner />;

  const ready = subject.topics.filter((t) => t.status === "ready");
  const mastered = ready.filter((t) => t.mastery >= MASTERED).length;
  const hasCourse = ready.length > 0;
  const filesOpen = showFiles || !hasCourse;

  const remove = async () => {
    if (!confirm(`Delete ${subject.name} and everything in it?`)) return;
    try {
      await api.deleteSubject(subject.id);
      navigate("/");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const goNext = () => {
    const n = subject.next!;
    if (n.action === "review") navigate(`/s/${id}/review`);
    else if (n.action === "learn") navigate(`/t/${n.topic_id}`);
    else navigate(`/s/${id}/practice?topic=${n.topic_id}`);
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-neutral-500 hover:underline">
            ← Subjects
          </Link>
          <h1 className="mt-1 flex items-center gap-3 text-2xl font-bold">
            <span className="h-4 w-4 rounded-full" style={{ background: subject.color }} />
            {subject.name}
          </h1>
          {hasCourse && (
            <p className="mt-1 text-neutral-500">
              {mastered} of {ready.length} topics mastered
            </p>
          )}
        </div>
        {hasCourse && (
          <div className="flex flex-wrap gap-2">
            <Link to={`/s/${id}/review`} className={btnGhost}>
              <Layers size={15} /> Flashcards{subject.due ? ` (${subject.due} due)` : ""}
            </Link>
            <Link to={`/s/${id}/practice`} className={btnGhost}>
              <PenLine size={15} /> Practice questions
            </Link>
          </div>
        )}
      </div>

      {hasCourse && subject.next && (
        <button onClick={goNext} className={`${card} flex w-full items-center justify-between gap-4 border-brand-200 bg-brand-50 p-5 text-left`}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-deep">Up next</p>
            <p className="mt-1 text-lg font-semibold">{subject.next.label}</p>
          </div>
          <ArrowRight className="shrink-0 text-brand-deep" />
        </button>
      )}
      {hasCourse && !subject.next && subject.build_status !== "building" && (
        <div className={`${card} p-5`}>
          <p className="font-semibold">Every topic mastered. 🎉</p>
          <p className="text-sm text-neutral-500">Keep up with flashcard reviews as they fall due so it sticks.</p>
        </div>
      )}

      {hasCourse && (
        <section>
          <h2 className="mb-3 font-semibold">Course path</h2>
          <ol className={`${card} divide-y divide-neutral-200 overflow-hidden`}>
            {subject.topics.map((t, i) => {
              const started = t.lesson_done || t.attempted > 0 || t.cards > 0;
              const done = t.mastery >= MASTERED;
              return (
                <li key={t.id}>
                  {t.status === "ready" ? (
                    <Link to={`/t/${t.id}`} className="flex items-center gap-4 p-4 hover:bg-neutral-50">
                      <span
                        className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold ${done ? "text-[#fff]" : "bg-neutral-100 text-neutral-600"}`}
                        style={done ? { background: subject.color } : undefined}
                      >
                        {done ? <Check size={16} /> : i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{t.title}</p>
                        <p className="truncate text-sm text-neutral-500">{t.summary}</p>
                        <div className="mt-2 flex items-center gap-3">
                          <div className="w-32">
                            <Bar value={t.mastery} color={subject.color} />
                          </div>
                          <span className="text-xs text-neutral-500">{masteryLabel(t.mastery, started)}</span>
                        </div>
                      </div>
                    </Link>
                  ) : (
                    <div className="flex items-center gap-4 p-4 text-neutral-500">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-neutral-100 text-sm">{i + 1}</span>
                      <div>
                        <p className="font-medium">{t.title}</p>
                        <p className="text-sm">{t.status === "failed" ? "Couldn't be written. Rebuild to retry." : "Being written…"}</p>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <section className={`${card} space-y-5 p-5`}>
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Material ({subject.documents.length} file{subject.documents.length === 1 ? "" : "s"})</h2>
          {hasCourse && (
            <button className="text-sm text-brand-deep hover:underline" onClick={() => setShowFiles(!showFiles)}>
              {filesOpen ? "Hide" : "Show / add files"}
            </button>
          )}
        </div>
        {filesOpen && (
          <>
            {subject.documents.length > 0 && (
              <ul className="space-y-2">
                {subject.documents.map((d) => (
                  <li key={d.id} className="flex items-center gap-3 text-sm">
                    <FileText size={16} className="shrink-0 text-neutral-400" />
                    <span className="min-w-0 flex-1 truncate">{d.filename}</span>
                    <span className="text-neutral-500">
                      {d.kind} · {d.units} {d.filename.endsWith(".pptx") ? "slides" : "pages"}
                    </span>
                    {d.warning && (
                      <span title={d.warning}>
                        <AlertTriangle size={15} className="text-amber-800" />
                      </span>
                    )}
                    <button
                      className="text-neutral-400 hover:text-rose-700"
                      aria-label={`Remove ${d.filename}`}
                      onClick={() => api.deleteDocument(d.id).then(load, (e) => setError(e.message))}
                    >
                      <Trash2 size={15} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <Uploader subject={subject} onUploaded={load} />
          </>
        )}
        {subject.documents.length > 0 && <BuildPanel subject={subject} onStarted={load} />}
      </section>

      <button onClick={remove} className="text-sm text-neutral-400 hover:text-rose-700">
        Delete subject
      </button>
    </div>
  );
}
