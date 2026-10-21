import { ChevronDown, MessageCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SubjectHeader } from "../components/SubjectHeader";
import { TutorChat } from "../components/TutorChat";
import { Bar, ErrorNote, Markdown, Spinner, btnGhost, btnPrimary, card } from "../components/ui";
import { api, type Assessment, type Confidence, type SyllabusData, type SyllabusItem, type SyllabusSection } from "../lib/api";

const pct = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}%`);

const CONFIDENCE: { value: Confidence; label: string; on: string }[] = [
  { value: 1, label: "Not yet", on: "border-rose-700 bg-rose-50 text-rose-700" },
  { value: 2, label: "Getting there", on: "border-amber-800 bg-amber-50 text-amber-800" },
  { value: 3, label: "Confident", on: "border-emerald-700 bg-emerald-50 text-emerald-700" },
];

const IMPORTANCE = {
  high: { label: "High weight", className: "bg-brand-50 text-brand-deep" },
  medium: { label: "Core", className: "bg-neutral-100 text-neutral-600" },
  low: { label: "Background", className: "bg-neutral-100 text-neutral-400" },
};

function ConfidencePicker({ item, onRate }: { item: SyllabusItem; onRate: (c: Confidence) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="How confident are you?">
      {CONFIDENCE.map((c) => {
        const on = item.confidence === c.value;
        return (
          <button
            key={c.value}
            role="radio"
            aria-checked={on}
            // Clicking the current rating clears it.
            onClick={() => onRate(on ? 0 : c.value)}
            className={`rounded-full border px-3 py-1 text-sm transition ${on ? c.on : "border-neutral-200 text-neutral-500 hover:border-neutral-400"}`}
          >
            {c.label}
          </button>
        );
      })}
    </div>
  );
}

function ItemRow({
  item,
  color,
  open,
  onToggle,
  onRate,
  onAsk,
}: {
  item: SyllabusItem;
  color: string;
  open: boolean;
  onToggle: () => void;
  onRate: (c: Confidence) => void;
  onAsk: () => void;
}) {
  const imp = IMPORTANCE[item.importance];
  const conf = CONFIDENCE.find((c) => c.value === item.confidence);
  return (
    <li>
      <button onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-neutral-50" aria-expanded={open}>
        <ChevronDown size={16} className={`mt-1 shrink-0 text-neutral-400 transition ${open ? "rotate-180" : ""}`} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="font-medium">{item.title}</span>
            <span className="flex shrink-0 items-center gap-2">
              {conf && <span className={`rounded-full border px-2 py-0.5 text-xs ${conf.on}`}>{conf.label}</span>}
              <span className={`rounded-full px-2 py-0.5 text-xs ${imp.className}`}>{imp.label}</span>
            </span>
          </div>
          {item.mastery !== null && (
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <Bar value={item.mastery} color={color} />
              </div>
              <span className="w-10 text-right text-xs tabular-nums text-neutral-500">{pct(item.mastery)}</span>
            </div>
          )}
        </div>
      </button>
      {open && (
        <div className="space-y-4 px-4 pb-5 pl-11">
          {item.detail && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">What you need to know</p>
              <Markdown>{item.detail}</Markdown>
            </div>
          )}
          {item.marking && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">How it's marked</p>
              <Markdown>{item.marking}</Markdown>
            </div>
          )}
          {item.assessed_in.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-neutral-400">Assessed in</span>
              {item.assessed_in.map((a) => (
                <span key={a} className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
                  {a}
                </span>
              ))}
            </div>
          )}
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Where it's taught</p>
            {item.topics.length ? (
              <ul className="space-y-1">
                {item.topics.map((t) => (
                  <li key={t.id} className="flex items-center justify-between gap-3 text-sm">
                    {t.status === "ready" ? (
                      <Link to={`/t/${t.id}`} className="text-brand-deep hover:underline">
                        {t.title}
                      </Link>
                    ) : (
                      <span className="text-neutral-500">
                        {t.title} {t.status === "missing" && <span className="text-amber-800">(not in your material yet)</span>}
                      </span>
                    )}
                    <span className="text-xs tabular-nums text-neutral-500">{pct(t.mastery)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-amber-800">No lesson covers this yet. Add material on it, or ask the tutor.</p>
            )}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">How confident are you?</p>
            <ConfidencePicker item={item} onRate={onRate} />
          </div>
          <button onClick={onAsk} className="flex items-center gap-1.5 text-sm text-brand-deep hover:underline">
            <MessageCircle size={14} /> Ask the tutor about this
          </button>
        </div>
      )}
    </li>
  );
}

function SectionCard({
  section,
  items,
  color,
  open,
  openItems,
  onToggle,
  onToggleItem,
  onRate,
  onAsk,
}: {
  section: SyllabusSection;
  items: SyllabusItem[];
  color: string;
  open: boolean;
  openItems: Set<number>;
  onToggle: () => void;
  onToggleItem: (id: number) => void;
  onRate: (item: SyllabusItem, c: Confidence) => void;
  onAsk: (item: SyllabusItem) => void;
}) {
  const p = section.progress;
  return (
    <section className={`${card} overflow-hidden`}>
      <button onClick={onToggle} className="w-full space-y-2 p-5 text-left hover:bg-neutral-50" aria-expanded={open}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{section.title}</h2>
            {section.outcome && <p className="mt-0.5 text-sm text-neutral-500">{section.outcome}</p>}
          </div>
          <ChevronDown size={18} className={`mt-1 shrink-0 text-neutral-400 transition ${open ? "rotate-180" : ""}`} />
        </div>
        <Bar value={p.mastery ?? 0} color={color} />
        <p className="text-xs text-neutral-500">
          {pct(p.mastery)} mastered in practice · {p.confident}/{p.items} confident
          {p.high > 0 && ` · ${p.high} high-weight`}
        </p>
      </button>
      {open && (
        <ul className="divide-y divide-neutral-200 border-t border-neutral-200">
          {items.map((it) => (
            <ItemRow
              key={it.id}
              item={it}
              color={color}
              open={openItems.has(it.id)}
              onToggle={() => onToggleItem(it.id)}
              onRate={(c) => onRate(it, c)}
              onAsk={() => onAsk(it)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function AssessmentCard({ a, active, onClick }: { a: Assessment; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`${card} space-y-1 p-4 text-left transition ${active ? "border-brand bg-brand-50" : "hover:border-neutral-400"}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{a.name}</span>
        {a.weight !== null && <span className="text-lg font-bold tabular-nums">{a.weight}%</span>}
      </div>
      {a.format && <p className="text-xs text-neutral-500">{a.format}</p>}
      {a.criteria && <p className="line-clamp-3 text-sm text-neutral-600">{a.criteria}</p>}
    </button>
  );
}

export default function SyllabusPage() {
  const id = Number(useParams().id);
  const [data, setData] = useState<SyllabusData | null>(null);
  const [due, setDue] = useState(0);
  const [error, setError] = useState("");
  const [assessment, setAssessment] = useState<string | null>(null);
  const [onlyHigh, setOnlyHigh] = useState(false);
  const [onlyUnsure, setOnlyUnsure] = useState(false);
  const [closed, setClosed] = useState<Set<number>>(new Set());
  const [openItems, setOpenItems] = useState<Set<number>>(new Set());
  const [chat, setChat] = useState<{ starter: string } | null>(null);

  const load = useCallback(() => api.syllabus(id).then(setData, (e) => setError(e.message)), [id]);
  useEffect(() => {
    load();
    api.subject(id).then((s) => setDue(s.due), () => {});
  }, [id, load]);
  const building = data?.subject.build_status === "building";
  useEffect(() => {
    if (!building) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [building, load]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.sections
      .map((s) => ({
        section: s,
        items: s.items.filter(
          (it) =>
            (!assessment || it.assessed_in.includes(assessment)) &&
            (!onlyHigh || it.importance === "high") &&
            (!onlyUnsure || it.confidence < 3),
        ),
      }))
      .filter((s) => s.items.length > 0);
  }, [data, assessment, onlyHigh, onlyUnsure]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;

  const rate = async (item: SyllabusItem, c: Confidence) => {
    // Show it straight away; put it back if saving fails.
    const set = (value: Confidence) =>
      setData((d) =>
        d && {
          ...d,
          sections: d.sections.map((s) => ({ ...s, items: s.items.map((i) => (i.id === item.id ? { ...i, confidence: value } : i)) })),
        },
      );
    set(c);
    try {
      await api.rateItem(item.id, c);
      load(); // refresh the counts
    } catch (e) {
      set(item.confidence);
      setError((e as Error).message);
    }
  };

  const rebuild = async () => {
    if (data.sections.length && !confirm("Redraft the syllabus from your material? Your confidence ratings are kept where items stay the same.")) return;
    try {
      await api.rebuildSyllabus(id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggle = (set: Set<number>, value: number) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };
  const allIds = data.sections.flatMap((s) => s.items.map((i) => i.id));
  const filtering = !!assessment || onlyHigh || onlyUnsure;
  const p = data.progress;
  const chip = (on: boolean) =>
    `rounded-full border px-3 py-1 text-sm ${on ? "border-brand bg-brand-50 text-brand-deep" : "border-neutral-200 text-neutral-500 hover:border-neutral-400"}`;

  return (
    <div className="space-y-6">
      {chat && <TutorChat subjectId={id} title={data.subject.name} starter={chat.starter} onClose={() => setChat(null)} />}
      <SubjectHeader
        id={id}
        name={data.subject.name}
        color={data.subject.color}
        due={due}
        hasCourse
        onAsk={() => setChat({ starter: "" })}
      />

      {building ? (
        <div className={`${card} p-6`}>
          <Spinner label={data.subject.build_message || "Mapping the syllabus…"} />
        </div>
      ) : data.sections.length === 0 ? (
        <div className={`${card} space-y-3 p-6`}>
          <h2 className="text-lg font-semibold">No syllabus yet</h2>
          <p className="text-neutral-500">
            The syllabus maps everything you need to know for this course, organised by its learning outcomes and how each part is
            marked.
            {!data.has_outline && " For the best result, upload your course outline (unit outline) first, as a Course outline file on the Dashboard."}
          </p>
          <button className={btnPrimary} onClick={rebuild}>
            <RefreshCw size={15} /> Draft my syllabus
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm text-neutral-500">
                {p.items} things to know · {p.confident} confident · {pct(p.mastery)} mastered in practice
              </p>
              {!data.has_outline && (
                <p className="mt-1 text-sm text-amber-800">
                  Drafted from your material alone. Upload the official course outline, then rebuild, to base it on the real outcomes
                  and marking.
                </p>
              )}
            </div>
            <button onClick={rebuild} className={btnGhost}>
              <RefreshCw size={15} /> Rebuild syllabus
            </button>
          </div>

          {data.assessments.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">How you're assessed</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {data.assessments.map((a) => (
                  <AssessmentCard
                    key={a.id}
                    a={a}
                    active={assessment === a.name}
                    onClick={() => setAssessment(assessment === a.name ? null : a.name)}
                  />
                ))}
              </div>
            </section>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button className={chip(onlyHigh)} onClick={() => setOnlyHigh(!onlyHigh)}>
              High weight only
            </button>
            <button className={chip(onlyUnsure)} onClick={() => setOnlyUnsure(!onlyUnsure)}>
              Not confident yet
            </button>
            {filtering && (
              <button
                className="text-sm text-neutral-500 hover:underline"
                onClick={() => {
                  setAssessment(null);
                  setOnlyHigh(false);
                  setOnlyUnsure(false);
                }}
              >
                Clear filters
              </button>
            )}
            <span className="flex-1" />
            <button className="text-sm text-brand-deep hover:underline" onClick={() => { setClosed(new Set()); setOpenItems(new Set(allIds)); }}>
              Expand all
            </button>
            <button
              className="text-sm text-brand-deep hover:underline"
              onClick={() => { setOpenItems(new Set()); setClosed(new Set(data.sections.map((s) => s.id))); }}
            >
              Collapse all
            </button>
          </div>
          {assessment && <p className="text-sm text-neutral-500">Showing what {assessment} tests.</p>}

          <div className="space-y-4">
            {filtered.length === 0 ? (
              <p className="text-neutral-500">Nothing matches these filters.</p>
            ) : (
              filtered.map(({ section, items }) => (
                <SectionCard
                  key={section.id}
                  section={section}
                  items={items}
                  color={data.subject.color}
                  open={!closed.has(section.id)}
                  openItems={openItems}
                  onToggle={() => setClosed(toggle(closed, section.id))}
                  onToggleItem={(itemId) => setOpenItems(toggle(openItems, itemId))}
                  onRate={rate}
                  onAsk={(it) => setChat({ starter: `Help me understand: ${it.title}` })}
                />
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
