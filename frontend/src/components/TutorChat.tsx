import { MessageCircle, RotateCcw, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, sendChat, type ChatMessage } from "../lib/api";
import { ErrorNote, Markdown, Spinner } from "./ui";

const TOPIC_PROMPTS = ["Explain this more simply", "Give me another worked example", "Quiz me on this", "What do students usually get wrong here?"];
const SUBJECT_PROMPTS = ["What are the big ideas in this subject?", "Quiz me on everything so far", "What's most likely to be examined?"];

/** A chat with the tutor about one topic, or the whole subject when topicId is absent. */
export function TutorChat({
  subjectId,
  topicId,
  title,
  onClose,
}: {
  subjectId: number;
  topicId?: number;
  title: string;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory(subjectId, topicId).then((r) => setMessages(r.messages), (e) => setError(e.message));
  }, [subjectId, topicId]);

  useEffect(() => {
    // Scroll only the message list; scrollIntoView would scroll the page behind it too.
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setError("");
    setBusy(true);
    const before = messages ?? [];
    setMessages([...before, { role: "user", content: message }, { role: "assistant", content: "" }]);
    try {
      await sendChat(subjectId, message, topicId, (piece) =>
        setMessages((m) => {
          if (!m) return m;
          const last = m[m.length - 1];
          return [...m.slice(0, -1), { ...last, content: last.content + piece }];
        }),
      );
    } catch (e) {
      setError((e as Error).message);
      // The exchange wasn't saved, so take it back off the screen and return the draft.
      setMessages(before);
      setDraft(message);
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!confirm("Clear this conversation?")) return;
    await api.clearChat(subjectId, topicId).catch((e) => setError(e.message));
    setMessages([]);
  };

  const prompts = topicId ? TOPIC_PROMPTS : SUBJECT_PROMPTS;

  // Portalled to <body> so the page's spacing rules can't touch the overlay.
  return createPortal(
    <div className="fixed inset-0 z-30 flex justify-end bg-black/20" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-lg flex-col border-l border-neutral-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
        aria-label="Tutor chat"
      >
        <header className="flex items-center gap-3 border-b border-neutral-200 px-4 py-3">
          <MessageCircle size={18} className="text-brand-deep" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">Tutor</p>
            <p className="truncate text-xs text-neutral-500">{title}</p>
          </div>
          {!!messages?.length && (
            <button onClick={clear} className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100" aria-label="Clear conversation">
              <RotateCcw size={16} />
            </button>
          )}
          <button onClick={onClose} className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100" aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto p-4">
          {!messages ? (
            <Spinner />
          ) : messages.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-neutral-500">
                Ask anything about {topicId ? "this topic" : "this subject"}. Answers come from your own material, with page references.
              </p>
              <div className="flex flex-wrap gap-2">
                {prompts.map((p) => (
                  <button
                    key={p}
                    onClick={() => send(p)}
                    className="rounded-full border border-neutral-200 px-3 py-1.5 text-sm hover:border-brand hover:bg-brand-50"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="ml-10 rounded-2xl rounded-br-sm bg-brand-50 px-4 py-2.5">
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>
              ) : (
                <div key={i} className="mr-6">
                  {m.content ? <Markdown>{m.content}</Markdown> : <Spinner label="Thinking…" />}
                </div>
              ),
            )
          )}
          {error && <ErrorNote error={error} />}
        </div>

        <form
          className="flex items-end gap-2 border-t border-neutral-200 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            rows={Math.min(5, Math.max(1, draft.split("\n").length))}
            placeholder="Ask the tutor…"
            className="flex-1 resize-none rounded-xl border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-brand"
            autoFocus
          />
          <button
            className="grid h-10 w-10 place-items-center rounded-xl bg-brand text-[#fff] hover:bg-brand-hover disabled:opacity-50"
            disabled={busy || !draft.trim()}
            aria-label="Send"
          >
            <Send size={16} />
          </button>
        </form>
      </aside>
    </div>,
    document.body,
  );
}

export function AskButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="fixed bottom-5 right-5 z-20 flex items-center gap-2 rounded-full bg-brand px-5 py-3 font-medium text-[#fff] shadow-lg hover:bg-brand-hover"
    >
      <MessageCircle size={18} /> Ask the tutor
    </button>
  );
}
