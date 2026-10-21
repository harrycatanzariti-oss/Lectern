import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorNote, MasteryRing, Spinner, btnPrimary, card } from "../components/ui";
import { api, type SubjectSummary } from "../lib/api";

export const COLORS = ["#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626", "#c026d3", "#475569"];

function NewSubject({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLORS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const s = await api.createSubject(name, color);
      navigate(`/s/${s.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className={`${card} space-y-4 p-5`}>
      <label className="block">
        <span className="text-sm font-medium">Subject name</span>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. MATH1131 Calculus"
          className="mt-1 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-brand"
        />
      </label>
      <div>
        <span className="text-sm font-medium">Colour</span>
        <div className="mt-2 flex gap-2">
          {COLORS.map((c) => (
            <button
              type="button"
              key={c}
              onClick={() => setColor(c)}
              className={`h-7 w-7 rounded-full ring-offset-2 ring-offset-white ${color === c ? "ring-2 ring-neutral-500" : ""}`}
              style={{ background: c }}
              aria-label={`Colour ${c}`}
            />
          ))}
        </div>
      </div>
      {error && <ErrorNote error={error} />}
      <div className="flex gap-2">
        <button className={btnPrimary} disabled={busy || !name.trim()}>
          Create subject
        </button>
        <button type="button" onClick={onDone} className="px-3 text-sm text-neutral-500">
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function Home() {
  const [subjects, setSubjects] = useState<SubjectSummary[] | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api.subjects().then(setSubjects, (e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!subjects) return <Spinner />;

  const due = subjects.reduce((n, s) => n + s.due, 0);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Your subjects</h1>
          <p className="mt-1 text-neutral-500">
            {subjects.length === 0
              ? "Add a subject, drop in your lecture slides and textbook, and Lectern turns them into a course."
              : due
                ? `${due} card${due === 1 ? "" : "s"} due for review today.`
                : "Nothing due for review. Keep going on your next topic."}
          </p>
        </div>
        {!adding && (
          <button className={btnPrimary} onClick={() => setAdding(true)}>
            <Plus size={16} /> New subject
          </button>
        )}
      </div>

      {(adding || subjects.length === 0) && <NewSubject onDone={() => setAdding(false)} />}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {subjects.map((s) => (
          <Link key={s.id} to={`/s/${s.id}`} className={`${card} group block overflow-hidden transition hover:shadow-md`}>
            <div className="h-1.5" style={{ background: s.color }} />
            <div className="flex items-start justify-between gap-3 p-5">
              <div className="min-w-0">
                <h2 className="truncate font-semibold group-hover:underline">{s.name}</h2>
                <p className="mt-1 text-sm text-neutral-500">
                  {s.build_status === "building"
                    ? "Building course…"
                    : s.topics
                      ? `${s.mastered}/${s.topics} topics mastered`
                      : s.documents
                        ? `${s.documents} file${s.documents === 1 ? "" : "s"} uploaded, not built yet`
                        : "No material yet"}
                </p>
                {s.due > 0 && (
                  <span className="mt-3 inline-block rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-deep">
                    {s.due} due
                  </span>
                )}
              </div>
              {s.topics > 0 && <MasteryRing value={s.mastery} color={s.color} />}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
