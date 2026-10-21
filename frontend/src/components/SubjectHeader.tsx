import { ClipboardList, Layers, MessageCircle, PenLine } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { btnGhost } from "./ui";

/** Name, study actions and the Dashboard / Syllabus tabs, shared by a subject's pages. */
export function SubjectHeader({
  id,
  name,
  color,
  due,
  hasCourse,
  onAsk,
}: {
  id: number;
  name: string;
  color: string;
  due: number;
  hasCourse: boolean;
  onAsk: () => void;
}) {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `-mb-px border-b-2 px-1 pb-2 text-sm font-medium ${isActive ? "border-brand text-brand-deep" : "border-transparent text-neutral-500 hover:text-neutral-800"}`;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-neutral-500 hover:underline">
            ← Subjects
          </Link>
          <h1 className="mt-1 flex items-center gap-3 text-2xl font-bold">
            <span className="h-4 w-4 rounded-full" style={{ background: color }} />
            {name}
          </h1>
        </div>
        {hasCourse && (
          <div className="flex flex-wrap gap-2">
            <Link to={`/s/${id}/review`} className={btnGhost}>
              <Layers size={15} /> Flashcards{due ? ` (${due} due)` : ""}
            </Link>
            <Link to={`/s/${id}/practice`} className={btnGhost}>
              <PenLine size={15} /> Practice
            </Link>
            <Link to={`/s/${id}/exam`} className={btnGhost}>
              <ClipboardList size={15} /> Mock exam
            </Link>
            <button onClick={onAsk} className={btnGhost}>
              <MessageCircle size={15} /> Ask the tutor
            </button>
          </div>
        )}
      </div>
      {hasCourse && (
        <nav className="flex gap-6 border-b border-neutral-200" aria-label="Subject sections">
          <NavLink end to={`/s/${id}`} className={tab}>
            Dashboard
          </NavLink>
          <NavLink to={`/s/${id}/syllabus`} className={tab}>
            Syllabus
          </NavLink>
        </nav>
      )}
    </div>
  );
}
