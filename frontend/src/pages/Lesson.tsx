import { ArrowLeft, ArrowRight, Check, Layers, PenLine } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AskButton, TutorChat } from "../components/TutorChat";
import { ErrorNote, Markdown, Spinner, btnGhost, btnPrimary, card } from "../components/ui";
import { api, type Topic } from "../lib/api";

export default function Lesson() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [topic, setTopic] = useState<Topic | null>(null);
  const [error, setError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    setTopic(null);
    setChatOpen(false);
    api.topic(id).then(setTopic, (e) => setError(e.message));
    window.scrollTo(0, 0);
  }, [id]);

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
        <p className="mt-3 text-sm font-medium text-brand-deep">Topic {topic.position + 1}</p>
        <h1 className="text-3xl font-bold">{topic.title}</h1>
        <p className="mt-2 text-neutral-500">{topic.summary}</p>
      </div>

      <Markdown>{topic.lesson_md}</Markdown>

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
