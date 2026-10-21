# Lectern

Drop in your lecture slides and textbook and Lectern turns them into a course that
teaches you: ordered lessons, flashcards on spaced repetition, exam-style practice
questions the AI marks, mock exams, and a tutor you can ask about any of it. One app,
as many subjects as you're taking.

It borrows from two other projects:

- **From Parlay:** the learning engine. Active recall on a spaced-repetition deck, drills
  that make you produce answers, and progress measured as real mastery, not streaks.
  Parlay keeps each language in its own pack; Lectern keeps each subject separate in the
  same way.
- **From Otis:** the AI that reads a pile of raw material and turns it into something you
  can act on. Here it reads your slides and textbook and writes the course.

## How it works

1. **Create a subject** (e.g. *MATH1131 Calculus*) and upload its material: PDF,
   PowerPoint (.pptx), .txt or .md. Lectern pulls the text from every page and slide,
   speaker notes included, and keeps track of where each piece came from. The AI reads
   PDF pages that are mostly pictures (scans, diagrams, slides exported as images) during
   the build: it transcribes the text and describes the figures.
2. **Build the course.** The AI reads everything in the subject at once and plans the
   topics in teaching order, prerequisites first. Then, for each topic, it writes a
   lesson, 6–15 flashcards and 4–8 practice questions. Every item points back to the
   page or slide it came from.
3. **Study.** The subject page always shows one next step:
   - **Review**: flashcards that are due. They're scheduled with an SM-2 variant, so each
     one comes back just before you'd forget it.
   - **Learn**: the next lesson on the path. When you finish it, its flashcards and
     questions unlock.
   - **Practise**: multiple-choice questions are marked instantly. The AI marks
     short-answer questions against the model answer, gives partial credit, and says
     what to fix.
4. **Ask the tutor.** Every lesson has a chat that knows that topic, and each subject
   has one that knows the whole subject. Answers come from your material with page
   references, and the tutor will quiz you Socratically if you ask.
5. **Mock exams.** Choose the number of questions, a time limit and the topics. Questions
   are spread evenly across the topics, and marking happens at the end. The report ranks
   topics weakest first and links back to each lesson.
6. **Mastery.** Each topic's score blends how well you know its cards with your latest
   score on each of its questions. A topic counts as mastered at 80%. The home page has a
   *Review all due* session that covers every subject at once.

### Using it in a Claude Project

Each subject page has **Use in a Claude Project**. It downloads one Markdown file with:

- the course in order: lessons, key points, flashcards, practice questions and answers
- your mastery per topic, with weak topics flagged
- flashcards you keep forgetting, and your recent wrong answers
- optionally, the extracted text of all your files

Upload it to a Project's knowledge on claude.ai. Instructions at the top of the file tell
Claude to tutor from it. Export again to refresh it. Claude Projects have no public API
for adding files, so this step is manual.

### The subject dashboard

Each subject opens on a dashboard:

- **Stat tiles:** overall progress, topics mastered, cards due today, and how much of the
  syllabus your files cover.
- **Up next:** the one thing to do now.
- **Course path:** units in course order. Each unit has a progress bar, and each topic in it
  has its own bar plus lesson / flashcards / practice status.

Upload your unit outline or official syllabus as a **Course outline** file, and the units
follow it. Anything it lists that your other files don't teach appears as a greyed-out
topic marked *Not in your material yet*. Gaps count as 0% in the progress bars, because
they're still things you need to know. Add material that covers a gap and **Update
course** fills it in.

### The syllabus

Each subject has a **Syllabus** tab, separate from the dashboard. It's a map of everything
you need to *know* (not things to do), organised for revision:

- **Headers:** the course's learning outcomes.
- **Sub-headers:** the specific concepts, results and methods each outcome requires.
- **Opening an item** shows what depth you need, how it's marked, which assessments test
  it, the lessons that teach it (with your mastery), and your own confidence rating:
  *Not yet / Getting there / Confident*.
- **Assessments across the top:** each with its weighting and marking criteria. Tap one
  to see only what it tests. You can also filter to high-weight items or ones you're not
  confident in yet.

It's drafted at build time, and redrafted on each update. Your ratings carry over wherever
an item is unchanged. With a **Course outline** uploaded, the syllabus follows the
official learning outcomes, assessment details and marking criteria. Without one it's
inferred from your material, and the page says so. **Rebuild syllabus** redrafts just the
syllabus, e.g. after you upload the outline.

### Adding material later

Upload the next week's slides and click **Update course**. The AI fits the new material
into the existing course:

- Topics you already have keep their lessons, cards and your progress.
- Where new material deepens an existing topic, that topic gets an extra lesson section,
  new cards and new questions.
- Material the course doesn't cover yet becomes new topics, placed after their
  prerequisites.
- Any topic that failed to write last time is retried.

**Start over from scratch** replans the whole course and resets progress.

## Running it

You need Python 3.11+, Node 20+, and a DeepSeek API key (platform.deepseek.com).

```bash
./run.sh setup                      # install dependencies
cp .env.example .env                # then put your DEEPSEEK_API_KEY in .env
./run.sh dev                        # API on :8000, app on http://localhost:5173
```

`./run.sh serve` builds the frontend and serves everything from one port (`$PORT`,
default 8000). `./run.sh test` runs the backend tests and the frontend typecheck and
build.

### Putting it online

`render.yaml` is a Render blueprint for the `Dockerfile`: one web service with a 5 GB disk
at `/data` for the database and uploaded PDFs. Set `DEEPSEEK_API_KEY` and
**`LECTERN_PASSWORD`** in Render. Without a password, anyone who finds the URL can spend
your DeepSeek credit. The disk needs a paid instance; on the free tier, data is wiped on
every deploy.

| Variable | Default | |
|---|---|---|
| `DEEPSEEK_API_KEY` | (required) | |
| `LECTERN_PASSWORD` | none | Turns on the sign-in page |
| `DEEPSEEK_MODEL` | `deepseek-flash` | The model for every call |
| `LECTERN_DATA` | `./data` | Database and uploads |

## Layout

| Path | What's there |
|------|--------------|
| `backend/lectern/extract.py` | PDF / PPTX / text → one labelled chunk per page or slide |
| `backend/lectern/ai.py` | Every AI call (DeepSeek): plan the course, write a topic, mark an answer, chat |
| `backend/lectern/builder.py` | The background build: read image pages, plan or update the outline, write topics 4 at a time |
| `backend/lectern/srs.py` | Spaced-repetition scheduling |
| `backend/lectern/api.py` | HTTP API, mastery, next-step logic, chat streaming, exams, sign-in; serves the built frontend |
| `backend/lectern/db.py` | SQLite schema (`data/lectern.db`) |
| `frontend/src/pages/` | Subjects, subject page / course path, lesson, flashcards, practice, mock exam |
| `frontend/src/components/TutorChat.tsx` | The tutor chat panel |

## About the AI calls

- **Provider:** DeepSeek's chat API, with `deepseek-flash` by default (set
  `DEEPSEEK_MODEL` to change it). Thinking mode is off, as in Otis, to keep calls quick.
- **Checking replies:** DeepSeek's JSON mode returns valid JSON but doesn't enforce its
  shape. `ai.py` checks every reply against a schema, fixes harmless drift (like `"2"` for
  `2`), and asks once more if something is missing.
- **Context size:** the whole subject goes in a single request, up to about 750k tokens of
  the model's 1M, which is a couple of full textbooks. A subject bigger than that gets an
  error asking you to split it.
- **Caching:** DeepSeek caches repeated prompt prefixes automatically. Every call puts
  the material first, unchanged, so after the first topic the material is billed at the
  cache-hit price, about 2% of the normal rate. The tutor chat works the same way.
- **Image pages:** these are rendered to PNGs and sent as images. If DeepSeek can't read
  them, the build carries on without them and the file shows a note.

## Not built yet

- PowerPoint slides that are only images (python-pptx can't render them). Export the deck
  as a PDF and the AI reads the pictures.
- Accounts and sync: it's single-user, with one optional shared password.
- Fresh exam questions. Exams draw from each topic's question pool, which grows when new
  material extends a topic.
- Mobile app. The web app works on a phone. A native app could reuse Parlay's Expo shell.
