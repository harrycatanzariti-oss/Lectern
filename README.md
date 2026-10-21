# Lectern

Drop in your lecture slides and textbook and Lectern turns them into a course that
teaches you: ordered lessons, flashcards on spaced repetition, and exam-style practice
questions that Claude marks. One app, as many subjects as you're taking.

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
   speaker notes included, and keeps track of where each piece came from.
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
4. **Mastery.** Each topic's score blends how well you know its cards with your latest
   score on each of its questions. A topic counts as mastered at 80%.

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

## Layout

| Path | What's there |
|------|--------------|
| `backend/lectern/extract.py` | PDF / PPTX / text → one labelled chunk per page or slide |
| `backend/lectern/ai.py` | Every Claude call: plan the course, write a topic, mark an answer |
| `backend/lectern/builder.py` | The background build: outline, then topics 4 at a time |
| `backend/lectern/srs.py` | Spaced-repetition scheduling |
| `backend/lectern/api.py` | HTTP API, mastery, next-step logic; serves the built frontend |
| `backend/lectern/db.py` | SQLite schema (`data/lectern.db`) |
| `frontend/src/pages/` | Subjects, subject page / course path, lesson, flashcards, practice |

## About the AI calls

- Model: `claude-opus-5-5` by default (set `LECTERN_MODEL` to change it). Calls use
  structured outputs, so the course arrives as validated JSON, and server-side refusal
  fallbacks.
- The whole subject goes to Claude in a single request, up to about 750k tokens, which is
  a couple of full textbooks. A subject bigger than that gets an error asking you to split
  it.
- The material is marked for prompt caching. The first topic pays to read it and the
  other topics read it from cache, which cuts the cost of a build by roughly 10×.
- A rebuild writes a fresh course and **resets that subject's progress**. The app warns
  before rebuilding, and shows a banner when you've uploaded files since the last build.

## Not built yet

- Scanned PDFs (images with no text layer) are flagged at upload. Running OCR on them, or
  sending page images to Claude, is the next step.
- A chat tutor ("explain this differently", Socratic follow-ups).
- Accounts and sync: it's single-user, with local SQLite storage.
- Mobile app. The web app works on a phone. A native app could reuse Parlay's Expo shell.
