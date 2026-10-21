import { Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { MASTERED } from "../lib/api";

export function Markdown({ children, inline = false }: { children: string; inline?: boolean }) {
  return (
    <div className={inline ? "prose inline" : "prose"}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

export function MasteryRing({ value, size = 44, color = "var(--color-brand)" }: { value: number; size?: number; color?: string }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className="shrink-0" role="img" aria-label={`${Math.round(value * 100)}% mastered`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-neutral-200)" strokeWidth="5" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="5"
        strokeLinecap="round"
        strokeDasharray={`${c * value} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fontSize={size / 4} fill="currentColor">
        {Math.round(value * 100)}
      </text>
    </svg>
  );
}

export function Bar({ value, color = "var(--color-brand)" }: { value: number; color?: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200">
      <div className="h-full rounded-full transition-all" style={{ width: `${Math.round(value * 100)}%`, background: color }} />
    </div>
  );
}

export function masteryLabel(m: number, started: boolean) {
  if (m >= MASTERED) return "Mastered";
  if (started) return "Learning";
  return "Not started";
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-neutral-500">
      <Loader2 size={16} className="animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function ErrorNote({ error }: { error: string }) {
  return <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>;
}

export const btn =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
export const btnPrimary = `${btn} bg-brand text-[#fff] hover:bg-brand-hover`;
export const btnGhost = `${btn} border border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-100`;
export const card = "rounded-2xl border border-neutral-200 bg-white";
