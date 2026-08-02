# Anovlad AI Tutor v2.0

A Render-ready multimodal AI tutoring application with text, voice, image understanding, course-material grounding and an interactive visual whiteboard.

## What v2.0 adds

The tutor now converts suitable answers into a structured visual plan and displays it on a live whiteboard. The board supports:

- step-by-step mathematical and statistical workings,
- equations rendered with MathJax,
- line graphs with one or more data series,
- comparison and calculation tables,
- labelled concept and process diagrams,
- highlighted regions on an uploaded image,
- short lesson-slide presentations,
- pen, highlighter and eraser tools,
- undo, redo and clear-ink controls,
- full-screen presentation,
- PNG download,
- attaching the current board to the learner's next question.

The last feature lets a student mark a step, label or region, then ask the tutor to explain the part they marked.

## Existing capabilities retained

- text questions and multi-turn chat,
- browser microphone recording,
- speech-to-text transcription,
- spoken answers with selectable voices,
- image questions from photographs, screenshots and uploaded files,
- animated tutor while audio is playing,
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
  ├─ typed question
  ├─ recorded voice
  ├─ uploaded or photographed image
  └─ annotated whiteboard snapshot
            │
            ▼
FastAPI service on Render
  ├─ course-material retrieval
  ├─ multimodal tutoring response
  ├─ structured visual-plan generation
  ├─ speech transcription and generation
  └─ PostgreSQL learning-material storage
            │
            ▼
Written answer + audio + interactive visual whiteboard
```

The API key remains on the server and is never sent to the learner's browser.

## Repository structure

```text
app/
  main.py             API routes, image handling and visual-plan generation
  config.py           environment settings
  knowledge.py        extraction, chunking and retrieval
  prompts.py          tutor and visual-planner instructions
  schemas.py          typed API and visual-plan models
  static/
    index.html         chat and whiteboard interface
    styles.css         responsive styling and board presentation
    app.js             chat, audio, visual rendering and drawing tools
data/
  sample-course-note.txt
render.yaml            Render Blueprint using an existing database
requirements.txt
.env.example
```

## Upgrade the existing Render deployment

1. Extract this ZIP.
2. Replace the files in the root of the existing `AITutor` GitHub repository with the contents of this folder.
3. Commit the changes to the `main` branch.
4. Open the `anovlad-ai-tutor` service in Render.
5. Add or confirm the environment variables below.
6. Select **Manual Deploy**, then **Clear build cache and deploy**.
7. After the service becomes live, refresh the browser with `Ctrl + Shift + R`.

The default `render.yaml` creates only the web service. It does not attempt to create a second free PostgreSQL database.

## Required Render environment values

```text
OPENAI_API_KEY=your-current-secret-key
AI_MODEL=gpt-5.6-luna
AI_REASONING_EFFORT=low
AI_VERBOSITY=medium
MAX_OUTPUT_TOKENS=6000
VISUAL_PLAN_ENABLED=true
VISUAL_MAX_OUTPUT_TOKENS=3500
IMAGE_DETAIL=original
TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
DEFAULT_VOICE=nova
DEMO_MODE=false
DATABASE_URL=your-existing-Render-internal-database-URL
```

Keep `OPENAI_API_KEY`, `DATABASE_URL` and `ADMIN_KEY` in Render Environment settings. Do not place real secret values in GitHub.

## How the visual board works

The written tutor answer is generated first. When visual explanations are enabled, a second structured response selects one of these formats:

```text
steps | graph | table | diagram | image_annotation | slides | none
```

The browser renders the returned structure with HTML and SVG. This keeps graphs, tables, equations and diagrams sharp and editable without generating a separate image for every question.

For uploaded-image highlighting, coordinates are normalised to a 1000 by 1000 board. The interface maps those coordinates over the displayed image.

## Mobile use

On smaller screens, the interface shows two tabs:

- **Conversation** for questions and answers
- **Whiteboard** for the visual explanation and drawing tools

The Image button can open the phone camera where the browser supports camera capture.

## Course-material behaviour

Each uploaded document is:

1. checked for type and size,
2. converted to text,
3. divided into overlapping extracts,
4. stored in PostgreSQL or the local fallback,
5. searched when a learner asks a question.

The tutor receives the most relevant extracts and is instructed to label material it uses as `[Source: filename]`.

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

Set the API key and turn off demonstration mode in `.env`, then run:

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Testing

```bash
DEMO_MODE=true ADMIN_KEY=test-admin pytest -q
```

The v2.0 package includes tests for health, configuration, demo chat, visual-plan output, whiteboard snapshots, image annotation validation, audio MIME compatibility and administrator protection.

## Scope of this release

This release implements the interactive visual-explanation and whiteboard priority. It retains the lightweight animated tutor and spoken audio. A photorealistic WebRTC avatar and exported MP4 lesson-video service are separate integrations and are not included in v2.0.

## Production recommendations

Before institution-wide use, add student authentication, enrolment controls, lecturer dashboards, quotas, persistent conversation storage, accessibility review, privacy notices, monitoring, backups and a paid Render service/database sized for the expected number of learners.
