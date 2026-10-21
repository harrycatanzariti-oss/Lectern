import { LEVELS } from "../lib/api";

/** The lesson dial: slide between plain explanations and formal, high-level ones. */
export function LevelDial({ value, onChange, busy }: { value: number; onChange: (level: number) => void; busy?: boolean }) {
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor="level-dial" className="text-sm font-medium">
          Explanation level
        </label>
        <span className="text-sm font-semibold text-brand-deep" aria-live="polite">
          {LEVELS[value - 1]}
          {busy && <span className="font-normal text-neutral-500"> · rewriting…</span>}
        </span>
      </div>
      <input
        id="level-dial"
        type="range"
        min={1}
        max={LEVELS.length}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={LEVELS[value - 1]}
        className="mt-2 w-full cursor-pointer accent-[var(--color-brand)]"
      />
      <div className="mt-1 flex justify-between text-xs text-neutral-500">
        {LEVELS.map((name, i) => (
          <button
            key={name}
            type="button"
            onClick={() => onChange(i + 1)}
            className={`hover:text-neutral-900 ${i + 1 === value ? "font-semibold text-neutral-900" : ""}`}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}
