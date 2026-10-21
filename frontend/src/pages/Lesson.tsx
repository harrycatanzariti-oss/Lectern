import { ArrowLeft, ArrowRight, Check, Layers, PenLine } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { LevelDial } from "../components/LevelDial";
import { AskButton, TutorChat } from "../components/TutorChat";
import { ErrorNote, Markdown, Spinner, btnGhost, btnPrimary, card } from "../components/ui";
import { LEVELS, STANDARD, api, saveLevel, savedLevel, type Topic } from "../lib/api";

export default function Lesson() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [topic, setTopic] = useState<Topic | null>(null);
  const [error, setError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [level, setLevel] = useState(savedLevel);
  // The lesson shown at `level`; null while it's being rewritten for the first time.
  const [lesson, setLesson] = useState<{ level: number; md: string } | null>(null);
  const [lessonError, setLessonError] = useState("");

  useEffect(() => {
    setTopic(null);
    setLesson(null);
    setChatOpen(false);
    api.topic(id).then(setTopic, (e) => setError(e.message));
    window.scrollTo(0, 0);
  }, [id]);

  useEffect(() => {
    if (!topic || topic.id !== id) return;
    setLessonError("");
    if (level === STANDARD) {
      setLesson({ level, md: topic.lesson_md });
      return;
    }
    let live = true;
    api.lesson(id, level).then(
      (r) => live && setLesson({ level, md: r.lesson_md }),
      (e) => live && setLessonError(e.message),
    );
    return () => {
      live = false;
    };
  }, [topic, id, level]);

  const turnDial = (n: number) => {
    setLevel(n);
    saveLevel(n);
  };

  if (error) return <ErrorNote error={error} />;
  if (!topic) return <Spinner />;

  const finish = async () => {
    try {
      await api.completeTopic(topic.id);
      navigate(`/s/${topic.subject_id}/review?topic=${topic.id}&then=practice`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <article className="mx-auto max-w-3xl space-y-8 pb-16">
      {chatOpen ? (
        <TutorChat subjectId={topic.subject_id} topicId={topic.id} title={topic.title} onClose={() => setChatOpen(false)} />
      ) : (
        <AskButton onClick={() => setChatOpen(true)} />
      )}
      <div>
        <Link to={`/s/${topic.subject_id}`} className="text-sm text-neutral-500 hover:underline">
          ← Course path
        </Link>
        <p className="mt-3 text-sm font-medium text-brand-deep">
          {topic.unit ? `${topic.unit} · ` : ""}Topic {topic.position + 1}
        </p>
        <h1 className="text-3xl font-bold">{topic.title}</h1>
        <p className="mt-2 text-neutral-500">{topic.summary}</p>
      </div>

      <LevelDial value={level} onChange={turnDial} busy={!lessonError && lesson?.level !== level} />

      {lessonError ? (
        <ErrorNote error={`Couldn't rewrite this at the ${LEVELS[level - 1]} level: ${lessonError}`} />
      ) : !lesson ? (
        <Spinner label={`Writing the ${LEVELS[level - 1]} version…`} />
      ) : (
        // While another level is being written, the last one stays up, faded.
        <div className={`lesson transition-opacity ${lesson.level !== level ? "opacity-40" : ""}`}>
          <Markdown>{lesson.md}</Markdown>
        </div>
      )}

      {topic.key_points.length > 0 && (
        <section className={`${card} p-5`}>
          <h2 className="mb-2 font-semibold">Key points</h2>
          <ul className="space-y-2">
            {topic.key_points.map((p) => (
              <li key={p} className="flex gap-2">
                <Check size={16} className="mt-1.5 shrink-0 text-brand-deep" />
                <Markdown inline>{p}</Markdown>
              </li>
            ))}
          </ul>
        </section>
      )}

      {topic.sources.length > 0 && (
        <p className="text-sm text-neutral-500">From your material: {topic.sources.join("; ")}</p>
      )}

      <div className="flex flex-wrap gap-2 border-t border-neutral-200 pt-6">
        {topic.lesson_done ? (
          <>
            <Link to={`/s/${topic.subject_id}/review?topic=${topic.id}`} className={btnGhost}>
              <Layers size={15} /> Flashcards for this topic
            </Link>
            <Link to={`/s/${topic.subject_id}/practice?topic=${topic.id}`} className={btnGhost}>
              <PenLine size={15} /> Practise this topic
            </Link>
          </>
        ) : (
          <button onClick={finish} className={btnPrimary}>
            <Check size={15} /> I've read this. Test me
          </button>
        )}
      </div>

      <nav className="flex justify-between gap-4 text-sm">
        {topic.prev ? (
          <Link to={`/t/${topic.prev.id}`} className="flex items-center gap-1 text-neutral-500 hover:underline">
            <ArrowLeft size={14} /> {topic.prev.title}
          </Link>
        ) : (
          <span />
        )}
        {topic.next && (
          <Link to={`/t/${topic.next.id}`} className="flex items-center gap-1 text-right text-neutral-500 hover:underline">
            {topic.next.title} <ArrowRight size={14} />
          </Link>
        )}
      </nav>
    </article>
  );
}
