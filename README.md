# Anovlad AI Tutor v2.1

A Render-ready multimodal tutoring application with text, voice, image understanding, course-material grounding, an interactive visual whiteboard, guided practice and AI feedback on learner working.

## What v2.1 adds

### Guided practice and assessment

- generates two to six questions for a selected topic,
- moves from foundation to standard and challenge questions,
- accepts typed answers or whiteboard working,
- marks equivalent wording and valid alternative methods,
- provides a focused hint after an unsuccessful attempt,
- reveals a worked solution when requested,
- tracks progress and the current activity score.

### Whiteboard work checking

Learners can write, calculate, label or highlight on the board, then select **Check my work**. The tutor evaluates the method and result, identifies strengths and corrections, recommends the next step, and can place colour-coded annotations over the submitted board image.

### Synchronised visual teaching

The **Teach step by step** control presents one visual step at a time and speaks the matching narration. Learners can pause, stop, move between steps, replay an explanation and continue at their own pace.

### Editable visuals

- graph and table values can be edited as CSV,
- diagram nodes can be dragged to improve the layout,
- uploaded-image annotations distinguish information, correct work, cautions and errors,
- learner pen strokes are preserved with undo, redo and clear controls.

### Automatic workspace recovery

The browser saves the current conversation, visual plan, learner ink and interface settings locally. Reopening or refreshing the page restores the latest workspace on that browser.

## Visual whiteboard capabilities

The tutor can display:

- step-by-step mathematics and statistical workings,
- equations rendered with MathJax,
- line graphs with labelled axes and multiple series,
- comparison and calculation tables,
- labelled concept and process diagrams,
- highlighted regions on an uploaded image,
- short lesson-slide presentations,
- a live board with pen, highlighter and eraser tools,
- full-screen presentation and PNG export,
- a board snapshot attached to the learner's next question.

## Other capabilities retained

- text questions and multi-turn chat,
- browser microphone recording,
- speech-to-text transcription,
- spoken answers with selectable voices,
- image questions from photographs, screenshots and uploads,
- animated tutor while speech is playing,
- PDF, DOCX, TXT, MD and CSV course-material uploads,
- retrieval of relevant approved course extracts,
- source labels in tutor answers,
- guided, direct, revision and examination-practice modes,
- PostgreSQL storage on Render,
- local JSON fallback when PostgreSQL is absent,
- administrator-protected material uploads,
- responsive desktop and mobile views,
- demonstration mode without API calls.

## Architecture

```text
Student browser
  ├─ typed or recorded question
  ├─ uploaded or photographed image
  ├─ learner whiteboard working
  └─ guided-practice answer
            │
            ▼
FastAPI service on Render
  ├─ course-material retrieval
  ├─ multimodal tutoring response
  ├─ structured visual-plan generation
  ├─ practice generation and marking
  ├─ whiteboard image evaluation
  └─ transcription and speech generation
            │
            ▼
Written answer + audio + visual lesson + feedback + score
```

The API key stays on the server and is never sent to the learner's browser.

## Repository structure

```text
app/
  main.py             API routes, tutoring, practice and work checking
  config.py           environment settings
  knowledge.py        extraction, chunking and retrieval
  prompts.py          tutor, visual, assessment and feedback instructions
  schemas.py          typed API, visual and assessment models
  static/
    index.html         chat, practice and whiteboard interface
    styles.css         responsive visual and assessment styling
    app.js             core chat, audio, visual and drawing features
    v2_1.js            practice, work checking, editing and recovery

tests/
  test_app.py          API and feature tests

data/
  sample-course-note.txt

render.yaml            Render Blueprint using an existing database
requirements.txt
.env.example
```

## Upgrade the existing Render deployment

1. Extract this ZIP or the smaller v2.1 patch.
2. Upload the contents to the root of the existing `AITutor` GitHub repository and replace older files.
3. Commit to the `main` branch.
4. Open the existing `anovlad-ai-tutor` web service in Render.
5. Confirm the environment values below.
6. Select **Manual Deploy**, then **Clear build cache and deploy**.
7. Wait until the service becomes **Live**.
8. Refresh the tutor with `Ctrl + Shift + R`.

No database migration is required. The default `render.yaml` creates only the web service and uses your existing Render PostgreSQL database.

## Render environment values

```text
OPENAI_API_KEY=your-current-secret-key
AI_MODEL=gpt-5.6-luna
AI_REASONING_EFFORT=low
AI_VERBOSITY=medium
MAX_OUTPUT_TOKENS=6000
VISUAL_PLAN_ENABLED=true
VISUAL_MAX_OUTPUT_TOKENS=3500
IMAGE_DETAIL=high
TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
DEFAULT_VOICE=nova
DEMO_MODE=false
DATABASE_URL=your-existing-Render-internal-database-URL
```

Keep `OPENAI_API_KEY`, `DATABASE_URL` and `ADMIN_KEY` only in Render Environment settings. Never commit real secret values to GitHub.

## How guided practice works

1. The learner enters a topic and selects the number of questions.
2. The backend grounds the activity in retrieved course extracts where available.
3. The learner answers in text or writes on the board.
4. The marking service compares the response with the expected answer and marking guide.
5. A correct response advances to the next question. An incomplete response receives feedback and a hint.
6. The learner may request the solution, which advances the activity without awarding the question score.

Practice sessions are held in the running web service's memory. A Render restart can therefore end an unfinished practice activity. Persistent cross-device practice records require student accounts and database-backed activity storage in a later institutional release.

## How whiteboard checking works

The browser captures the current board as a PNG and sends it with the problem and visual context. The tutor returns a structured evaluation containing:

```text
verdict | score | summary | strengths | corrections | next step | annotations
```

Annotations use a normalised 1000 by 1000 coordinate system and are rendered over the captured board.

## Mobile use

On smaller screens, use:

- **Conversation** for chat and guided practice,
- **Whiteboard** for visuals, handwriting and work checking.

The Image control can open the phone camera when the browser supports camera capture.

## Course-material behaviour

Each uploaded document is checked, converted to text, divided into overlapping extracts, stored, and searched when a learner asks a question. The tutor receives the most relevant extracts and labels material used as `[Source: filename]`.

Scanned image-only PDFs need OCR before upload because the current material uploader reads embedded document text.

## Run locally

```bash
python -m venv .venv
```

Activate the environment.

Windows:

```bash
.venv\Scripts\activate
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Install and configure:

```bash
pip install -r requirements.txt
cp .env.example .env
```

Add the API key and set `DEMO_MODE=false`, then run:

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Testing

```bash
DEMO_MODE=true ADMIN_KEY=test-admin pytest -q
```

The v2.1 package contains 15 automated tests covering health and configuration, visual responses, audio MIME compatibility, guided practice, solution reveal, work checking, image validation and administrator protection.

## Scope of this release

This release implements interactive teaching and assessment. It retains the lightweight animated tutor and spoken audio. It does not yet include student login, cross-device records, a teacher dashboard, a photorealistic WebRTC avatar or exported MP4 lesson videos.

## Production recommendations

Before institution-wide use, add authenticated student and teacher accounts, enrolment controls, database-backed progress records, quotas, persistent conversation history, accessibility review, privacy notices, monitoring, backups and a paid Render service/database sized for the expected number of learners.
