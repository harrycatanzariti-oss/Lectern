import { Check, ChevronDown, CircleDashed } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { MASTERED, type Subject, type TopicRow, type Unit } from "../lib/api";
import { Bar, card, masteryLabel } from "./ui";

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** The headline numbers across the top of a subject. */
export function StatTiles({ subject }: { subject: Subject }) {
  const p = subject.progress;
  const tiles = [
    {
      label: "Overall progress",
      value: pct(p.mastery),
      detail: <Bar value={p.mastery} color={subject.color} />,
    },
    {
      label: "Topics mastered",
      value: `${p.mastered} / ${p.topics}`,
      detail: <span>{p.lessons_read} lesson{p.lessons_read === 1 ? "" : "s"} read</span>,
    },
    {
      label: "Due today",
      value: String(subject.due),
      detail: subject.due ? (
        <Link to={`/s/${subject.id}/review`} className="text-brand-deep hover:underline">
          Review now →
        </Link>
      ) : (
        <span>{subject.new ? `${subject.new} new cards waiting` : "All caught up"}</span>
      ),
    },
    {
      label: "Syllabus covered",
      value: `${p.covered} / ${p.topics}`,
      detail: p.missing ? (
        <span className="text-amber-800">
          {p.missing} not in your material yet
        </span>
      ) : (
        <span>Everything has material</span>
      ),
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className={`${card} space-y-1.5 p-4`}>
          <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">{t.label}</p>
          <p className="text-2xl font-bold">{t.value}</p>
          <div className="text-xs text-neutral-500">{t.detail}</div>
        </div>
      ))}
    </div>
  );
}

function Chip({ done, children }: { done: boolean; children: React.ReactNode }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${done ? "bg-brand-50 text-brand-deep" : "bg-neutral-100 text-neutral-500"}`}>
      {children}
    </span>
  );
}

function TopicLine({ topic, number, color }: { topic: TopicRow; number: number; color: string }) {
  if (topic.status === "missing") {
    return (
      <div className="flex items-start gap-4 p-4 text-neutral-500">
        <CircleDashed size={32} strokeWidth={1.5} className="shrink-0 text-neutral-300" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{topic.title}</p>
          <p className="text-sm">{topic.summary}</p>
          <p className="mt-1 text-xs text-amber-800">
            Not in your material yet. Add slides or notes that cover it, then update the course.
          </p>
        </div>
      </div>
    );
  }
  if (topic.status !== "ready") {
    return (
      <div className="flex items-center gap-4 p-4 text-neutral-500">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-neutral-100 text-sm">{number}</span>
        <div>
          <p className="font-medium">{topic.title}</p>
          <p className="text-sm">{topic.status === "failed" ? "Couldn't be written. Update the course to retry." : "Being written…"}</p>
        </div>
      </div>
    );
  }
  const done = topic.mastery >= MASTERED;
  const started = topic.lesson_done || topic.attempted > 0 || topic.cards > 0;
  return (
    <Link to={`/t/${topic.id}`} className="flex items-start gap-4 p-4 hover:bg-neutral-50">
      <span
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold ${done ? "text-[#fff]" : "bg-neutral-100 text-neutral-600"}`}
        style={done ? { background: color } : undefined}
      >
        {done ? <Check size={16} /> : number}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <p className="font-medium">{topic.title}</p>
          <span className="shrink-0 text-sm tabular-nums text-neutral-500">{pct(topic.mastery)}</span>
        </div>
        <Bar value={topic.mastery} color={color} />
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip done={topic.lesson_done}>{topic.lesson_done ? "Lesson read" : "Lesson not read"}</Chip>
          <Chip done={topic.cards > 0}>Flashcards {pct(topic.cards)}</Chip>
          <Chip done={topic.attempted > 0}>
            Practice {topic.attempted}/{topic.questions}
          </Chip>
          <span className="text-xs text-neutral-400">{masteryLabel(topic.mastery, started)}</span>
        </div>
      </div>
    </Link>
  );
}

function UnitCard({ unit, topics, numbers, color }: { unit: Unit; topics: TopicRow[]; numbers: Map<number, number>; color: string }) {
  const complete = unit.mastered === unit.topics;
  // Finished units start folded so the page shows what's left.
  const [open, setOpen] = useState(!complete);
  return (
    <section className={`${card} overflow-hidden`}>
      <button onClick={() => setOpen(!open)} className="w-full space-y-2 p-4 text-left hover:bg-neutral-50" aria-expanded={open}>
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">{unit.title}</h3>
          <div className="flex shrink-0 items-center gap-3 text-sm text-neutral-500">
            <span className="tabular-nums">
              {unit.mastered}/{unit.topics} mastered · {pct(unit.mastery)}
            </span>
            <ChevronDown size={16} className={`transition ${open ? "rotate-180" : ""}`} />
          </div>
        </div>
        <Bar value={unit.mastery} color={color} />
        {unit.missing > 0 && (
          <p className="text-xs text-amber-800">
            {unit.missing} topic{unit.missing === 1 ? "" : "s"} not in your material yet
          </p>
        )}
      </button>
      {open && (
        <ol className="divide-y divide-neutral-200 border-t border-neutral-200">
          {topics.map((t) => (
            <li key={t.id}>
              <TopicLine topic={t} number={numbers.get(t.id)!} color={color} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** The course path: units in course order, each with its topics and progress. */
export function CoursePath({ subject }: { subject: Subject }) {
  const byId = new Map(subject.topics.map((t) => [t.id, t]));
  const numbers = new Map(subject.topics.map((t, i) => [t.id, i + 1]));
  return (
    <section className="space-y-3">
      <h2 className="font-semibold">Course path</h2>
      {subject.units.map((u) => (
        <UnitCard
          key={u.title}
          unit={u}
          topics={u.topic_ids.map((id) => byId.get(id)!)}
          numbers={numbers}
          color={subject.color}
        />
      ))}
    </section>
  );
}
