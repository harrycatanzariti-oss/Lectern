export type BuildStatus = "empty" | "ready_to_build" | "building" | "built" | "failed";

export interface SubjectSummary {
  id: number;
  name: string;
  color: string;
  build_status: BuildStatus;
  build_message: string;
  build_progress: number;
  topics: number;
  mastered: number;
  mastery: number;
  documents: number;
  due: number;
  new: number;
}

export interface Doc {
  id: number;
  filename: string;
  kind: "slides" | "textbook" | "notes";
  units: number;
  chars: number;
  warning: string;
}

export interface Mastery {
  mastery: number;
  cards: number;
  practice: number;
  attempted: number;
  questions: number;
}

export interface TopicRow extends Mastery {
  id: number;
  position: number;
  title: string;
  summary: string;
  sources: string[];
  status: "pending" | "ready" | "failed";
  lesson_done: boolean;
}

export interface NextStep {
  action: "review" | "learn" | "practice";
  topic_id?: number;
  label: string;
}

export interface Subject {
  id: number;
  name: string;
  color: string;
  build_status: BuildStatus;
  build_message: string;
  build_progress: number;
  built_at: string | null;
  documents: Doc[];
  topics: TopicRow[];
  due: number;
  new: number;
  next: NextStep | null;
  stale: boolean;
}

export interface Topic extends TopicRow {
  subject_id: number;
  lesson_md: string;
  key_points: string[];
  prev: { id: number; title: string } | null;
  next: { id: number; title: string } | null;
}

export interface Card {
  id: number;
  front: string;
  back: string;
  source: string;
  reps: number;
  topic: string;
  topic_id: number;
}

export interface Question {
  id: number;
  topic_id: number;
  topic: string;
  kind: "mcq" | "short";
  prompt: string;
  options: string[];
  source: string;
}

export interface Marked {
  score: number;
  feedback: string;
  answer_index: number | null;
  model_answer: string;
  explanation: string;
}

export const MASTERED = 0.8;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  subjects: () => req<SubjectSummary[]>("/subjects"),
  createSubject: (name: string, color: string) => req<Subject>("/subjects", json("POST", { name, color })),
  updateSubject: (id: number, patch: { name?: string; color?: string }) =>
    req<Subject>(`/subjects/${id}`, json("PATCH", patch)),
  deleteSubject: (id: number) => req<void>(`/subjects/${id}`, { method: "DELETE" }),
  subject: (id: number) => req<Subject>(`/subjects/${id}`),
  upload: (id: number, files: File[], kind: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("kind", kind);
    return req<{ documents: Doc[]; errors: string[] }>(`/subjects/${id}/documents`, { method: "POST", body: form });
  },
  deleteDocument: (id: number) => req<void>(`/documents/${id}`, { method: "DELETE" }),
  build: (id: number) => req<{ ok: true }>(`/subjects/${id}/build`, { method: "POST" }),
  topic: (id: number) => req<Topic>(`/topics/${id}`),
  completeTopic: (id: number) => req<{ ok: true }>(`/topics/${id}/complete`, { method: "POST" }),
  review: (subjectId: number, topicId?: number) =>
    req<{ cards: Card[]; due: number; new: number }>(
      `/subjects/${subjectId}/review${topicId ? `?topic_id=${topicId}` : ""}`,
    ),
  grade: (cardId: number, grade: string) => req<unknown>(`/cards/${cardId}/grade`, json("POST", { grade })),
  practice: (subjectId: number, topicId?: number) =>
    req<{ questions: Question[] }>(`/subjects/${subjectId}/practice${topicId ? `?topic_id=${topicId}` : ""}`),
  answer: (questionId: number, answer: string) =>
    req<Marked>(`/questions/${questionId}/answer`, json("POST", { answer })),
};
