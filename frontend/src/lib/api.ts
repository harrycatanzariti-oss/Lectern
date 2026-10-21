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
  missing: number;
}

export interface Doc {
  id: number;
  filename: string;
  kind: "slides" | "textbook" | "notes" | "outline";
  units: number;
  chars: number;
  warning: string;
  image_pages: number[];
  in_course: number;
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
  unit: string;
  title: string;
  summary: string;
  sources: string[];
  /** missing: on the syllabus, but nothing in the material teaches it yet */
  status: "pending" | "ready" | "failed" | "missing";
  lesson_done: boolean;
}

export interface Progress {
  mastery: number;
  topics: number;
  mastered: number;
  covered: number;
  missing: number;
  lessons_read: number;
}

export interface Unit extends Progress {
  title: string;
  topic_ids: number[];
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
  failed_topics: number;
  units: Unit[];
  progress: Progress;
}

export interface Topic extends TopicRow {
  subject_id: number;
  lesson_md: string;
  key_points: string[];
  prev: { id: number; title: string } | null;
  next: { id: number; title: string } | null;
}

export interface Assessment {
  id: number;
  name: string;
  weight: number | null;
  format: string;
  criteria: string;
}

/** 0 unrated, 1 not yet, 2 getting there, 3 confident */
export type Confidence = 0 | 1 | 2 | 3;

export interface SyllabusItem {
  id: number;
  position: number;
  title: string;
  detail: string;
  marking: string;
  importance: "high" | "medium" | "low";
  assessed_in: string[];
  confidence: Confidence;
  /** Average mastery of the linked topics; null when no topic teaches it. */
  mastery: number | null;
  topics: { id: number; title: string; status: TopicRow["status"]; mastery: number }[];
}

export interface SyllabusProgress {
  items: number;
  mastery: number | null;
  confident: number;
  rated: number;
  high: number;
}

export interface SyllabusSection {
  id: number;
  title: string;
  outcome: string;
  items: SyllabusItem[];
  progress: SyllabusProgress;
}

export interface SyllabusData {
  subject: { id: number; name: string; color: string; build_status: BuildStatus; build_message: string };
  has_outline: boolean;
  assessments: Assessment[];
  sections: SyllabusSection[];
  progress: SyllabusProgress;
}

export interface Card {
  id: number;
  front: string;
  back: string;
  source: string;
  reps: number;
  topic: string;
  topic_id: number;
  subject?: string;
  color?: string;
}

export interface ChatMessage {
  id?: number;
  role: "user" | "assistant";
  content: string;
}

export interface ExamResult extends Question, Marked {
  answer: string;
  unmarked?: boolean;
}

export interface ExamReport {
  score: number;
  results: ExamResult[];
  topics: { topic_id: number; topic: string; score: number; n: number }[];
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

/** Called when the server says we need to sign in (LECTERN_PASSWORD is set). */
let onSignedOut = () => {};
export const setSignedOutHandler = (f: () => void) => {
  onSignedOut = f;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (res.status === 401 && path !== "/login") onSignedOut();
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
  build: (id: number, fresh: boolean) => req<{ ok: true }>(`/subjects/${id}/build`, json("POST", { fresh })),
  topic: (id: number) => req<Topic>(`/topics/${id}`),
  lesson: (id: number, level: number) => req<{ level: number; lesson_md: string }>(`/topics/${id}/lesson?level=${level}`),
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
  syllabus: (subjectId: number) => req<SyllabusData>(`/subjects/${subjectId}/syllabus`),
  rateItem: (itemId: number, confidence: Confidence) =>
    req<{ confidence: Confidence }>(`/syllabus/items/${itemId}`, json("PATCH", { confidence })),
  rebuildSyllabus: (subjectId: number) => req<{ ok: true }>(`/subjects/${subjectId}/syllabus`, { method: "POST" }),
  reviewAll: () => req<{ cards: Card[]; due: number; new: number }>("/review"),
  exam: (subjectId: number, n: number, topics: number[]) =>
    req<{ questions: Question[] }>(`/subjects/${subjectId}/exam?n=${n}&topics=${topics.join(",")}`),
  submitExam: (subjectId: number, answers: { question_id: number; answer: string }[]) =>
    req<ExamReport>(`/subjects/${subjectId}/exam`, json("POST", { answers })),
  session: () => req<{ signed_in: boolean; password_required: boolean }>("/session"),
  login: (password: string) => req<{ ok: true }>("/login", json("POST", { password })),
  chatHistory: (subjectId: number, topicId?: number) =>
    req<{ messages: ChatMessage[] }>(`/subjects/${subjectId}/chat${topicId ? `?topic_id=${topicId}` : ""}`),
  clearChat: (subjectId: number, topicId?: number) =>
    req<void>(`/subjects/${subjectId}/chat${topicId ? `?topic_id=${topicId}` : ""}`, { method: "DELETE" }),
};

/** The lesson dial, from plainest to most formal. The lesson as built is STANDARD. */
export const LEVELS = ["Simplest", "Simple", "Standard", "Detailed", "Rigorous"] as const;
export const STANDARD = 3;
const LEVEL_KEY = "lectern.level";

/** The dial's setting, remembered on this device for every lesson and the tutor. */
export function savedLevel(): number {
  try {
    const n = Number(localStorage.getItem(LEVEL_KEY));
    return n >= 1 && n <= LEVELS.length ? n : STANDARD;
  } catch {
    return STANDARD;
  }
}

export function saveLevel(level: number) {
  try {
    localStorage.setItem(LEVEL_KEY, String(level));
  } catch {
    /* private mode: it just isn't remembered */
  }
}

/** Send a chat message; onText gets the reply as it streams in. Resolves when it's complete. */
export async function sendChat(
  subjectId: number,
  message: string,
  topicId: number | undefined,
  onText: (piece: string) => void,
): Promise<void> {
  const res = await fetch(`/api/subjects/${subjectId}/chat`, json("POST", { message, topic_id: topicId ?? null, level: savedLevel() }));
  if (res.status === 401) onSignedOut();
  if (!res.ok || !res.body) {
    let msg = `Request failed (${res.status})`;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!;
    for (const line of lines) {
      if (!line) continue;
      const event = JSON.parse(line);
      if (event.error) throw new Error(event.error);
      if (event.text) onText(event.text);
    }
  }
}
