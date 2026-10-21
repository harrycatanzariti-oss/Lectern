# Lectern

Drop in your lecture slides and textbook and Lectern turns them into a course that
teaches you: ordered lessons, flashcards on spaced repetition, exam-style practice
questions that Claude marks, mock exams, and a tutor you can ask about any of it. One app,
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
   speaker notes included, and keeps track of where each piece came from. Claude reads
   PDF pages that are mostly pictures (scans, diagrams, slides exported as images) during
   the build: it transcribes the text and describes the figures.
2. **Build the course.** Claude reads everything in the subject at once and plans the
   topics in teaching order, prerequisites first. Then, for each topic, it writes a
   lesson, 6–15 flashcards and 4–8 practice questions. Every item points back to the
   page or slide it came from.
3. **Study.** The subject page always shows one next step:
   - **Review**: flashcards that are due. They're scheduled with an SM-2 variant, so each
     one comes back just before you'd forget it.
   - **Learn**: the next lesson on the path. When you finish it, its flashcards and
     questions unlock.
   - **Practise**: multiple-choice questions are marked instantly. Claude marks
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

### Adding material later

Upload the next week's slides and click **Update course**. Claude fits the new material
into the existing course:

- Topics you already have keep their lessons, cards and your progress.
- Where new material deepens an existing topic, that topic gets an extra lesson section,
  new cards and new questions.
- Material the course doesn't cover yet becomes new topics, placed after their
  prerequisites.
- Any topic that failed to write last time is retried.

**Start over from scratch** replans the whole course and resets progress.

## Running it

You need Python 3.11+, Node 20+, and an Anthropic API key.

```bash
./run.sh setup                      # install dependencies
cp .env.example .env                # then put your ANTHROPIC_API_KEY in .env
./run.sh dev                        # API on :8000, app on http://localhost:5173
```

`./run.sh serve` builds the frontend and serves everything from one port (`$PORT`,
default 8000). `./run.sh test` runs the backend tests and the frontend typecheck and
build.

### Putting it online

`render.yaml` is a Render blueprint for the `Dockerfile`: one web service with a 5 GB disk
at `/data` for the database and uploaded PDFs. Set `ANTHROPIC_API_KEY` and
**`LECTERN_PASSWORD`** in Render. Without a password, anyone who finds the URL can spend
your Claude credit. The disk needs a paid instance; on the free tier, data is wiped on
every deploy.

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | |
| `LECTERN_PASSWORD` | none | Turns on the sign-in page |
| `LECTERN_MODEL` | `claude-opus-5-5` | The model for every call |
| `LECTERN_DATA` | `./data` | Database and uploads |

## Layout

| Path | What's there |
|------|--------------|
| `backend/lectern/extract.py` | PDF / PPTX / text → one labelled chunk per page or slide |
| `backend/lectern/ai.py` | Every Claude call: plan the course, write a topic, mark an answer |
| `backend/lectern/builder.py` | The background build: read image pages, plan or update the outline, write topics 4 at a time |
| `backend/lectern/srs.py` | Spaced-repetition scheduling |
| `backend/lectern/api.py` | HTTP API, mastery, next-step logic, chat streaming, exams, sign-in; serves the built frontend |
| `backend/lectern/db.py` | SQLite schema (`data/lectern.db`) |
| `frontend/src/pages/` | Subjects, subject page / course path, lesson, flashcards, practice, mock exam |
| `frontend/src/components/TutorChat.tsx` | The tutor chat panel |

## About the AI calls

- Model: `claude-opus-5-5` by default (set `LECTERN_MODEL` to change it). Calls use
  structured outputs, so the course arrives as validated JSON, and server-side refusal
  fallbacks.
- The whole subject goes to Claude in a single request, up to about 750k tokens, which is
  a couple of full textbooks. A subject bigger than that gets an error asking you to split
  it.
- The material is marked for prompt caching. The first topic pays to read it and the
  other topics read it from cache, which cuts the cost of a build by roughly 10×.
- The tutor chat sends the subject's material with every message. It's cached, so after
  the first message each question costs roughly what a tenth of the material costs to
  read, at `low` effort to keep replies quick.

## Not built yet

- PowerPoint slides that are only images (python-pptx can't render them). Export the deck
  as a PDF and Claude reads the pictures.
- Accounts and sync: it's single-user, with one optional shared password.
- Fresh exam questions. Exams draw from each topic's question pool, which grows when new
  material extends a topic.
- Mobile app. The web app works on a phone. A native app could reuse Parlay's Expo shell.
