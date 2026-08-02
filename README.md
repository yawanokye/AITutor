# Anovlad AI Tutor

A Render-ready multimodal AI tutoring application. Students can type questions, record voice questions, upload images, and receive written or spoken explanations. Administrators can upload approved course materials so the tutor grounds its answers in institutional content.

## Included features

- Text questions and multi-turn chat
- Microphone recording and speech-to-text transcription
- Spoken AI answers with selectable voices
- Image-question analysis for diagrams, handwritten work, screenshots and textbook pages
- Animated visual tutor that moves while audio plays
- Course-material upload for PDF, DOCX, TXT, MD and CSV files
- Retrieval of relevant course extracts with source labels
- Education-level and teaching-mode controls
- Guided, direct, revision and exam-practice modes
- PostgreSQL storage for uploaded course extracts on Render
- Local JSON fallback when PostgreSQL is not configured
- Administrator-protected material uploads
- File-size limits, basic per-IP rate limiting and safe error responses
- Exportable chat transcript
- Responsive desktop and mobile interface
- Demonstration mode for testing without an API key

## Architecture

```text
Student browser
  ├─ text question
  ├─ microphone recording
  └─ image upload
        │
        ▼
FastAPI application on Render
  ├─ OpenAI transcription
  ├─ course-material retrieval
  ├─ OpenAI Responses API for tutoring and image analysis
  ├─ OpenAI speech generation
  └─ Render PostgreSQL for learning-material extracts
        │
        ▼
Text response + audio response + animated tutor
```

The OpenAI API key remains on the server. It is never sent to the student's browser.

## Repository structure

```text
app/
  main.py             API routes and OpenAI integration
  config.py           environment configuration
  knowledge.py        document extraction, chunking and retrieval
  prompts.py          tutoring and learner-safety instructions
  schemas.py          API response models
  static/
    index.html         student interface
    styles.css         responsive styling and animated tutor
    app.js             microphone, image, chat and audio controls
data/
  sample-course-note.txt
render.yaml            Render Blueprint
Dockerfile             optional Docker deployment
requirements.txt
.env.example
```

## Deploy on Render

### 1. Create the repository

1. Extract the ZIP.
2. Create a new GitHub, GitLab or Bitbucket repository.
3. Upload or push all files from the extracted folder.

### 2. Create the Render Blueprint

1. Sign in to Render.
2. Select **New +** and then **Blueprint**.
3. Connect the repository.
4. Render will detect `render.yaml` and propose:
   - one Python web service
   - one PostgreSQL database
5. Enter your `OPENAI_API_KEY` when Render requests the secret value.
6. Apply the Blueprint.

The service start command is already configured as:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 3. Find the administrator key

`ADMIN_KEY` is generated automatically by the Blueprint.

1. Open the web service in Render.
2. Select **Environment**.
3. Copy the generated `ADMIN_KEY`.
4. Open the deployed tutor.
5. Expand **Course materials**, enter the key, and upload approved learning documents.

### 4. Test the tutor

Test all four paths:

1. Type a question.
2. Record and transcribe a voice question.
3. Attach an image and ask the tutor to explain it.
4. Turn on **Read answers aloud** and confirm that the animated tutor speaks.

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

Edit `.env` and set:

```env
OPENAI_API_KEY=your-key
DEMO_MODE=false
ADMIN_KEY=your-long-random-admin-key
```

Start the app:

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Demonstration mode

To test the interface without making OpenAI API calls:

```env
DEMO_MODE=true
```

Text chat returns a demonstration response. Transcription and speech generation remain disabled until a valid API key is supplied.

## Main environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | empty | Server-side OpenAI API key |
| `AI_MODEL` | `gpt-5.6-luna` | Text and image tutoring model |
| `TRANSCRIBE_MODEL` | `gpt-transcribe` | Recorded-audio transcription model |
| `TTS_MODEL` | `tts-1` | Speech-generation model |
| `DEFAULT_VOICE` | `nova` | Initial tutor voice |
| `ADMIN_KEY` | generated on Render | Protects course-material uploads |
| `DATABASE_URL` | supplied by Render | PostgreSQL connection string |
| `DEMO_MODE` | `false` on Render | Enables no-key demonstration mode |
| `ALLOW_GENERAL_KNOWLEDGE` | `true` | Allows clearly labelled general explanations when course material is insufficient |
| `RATE_LIMIT_PER_MINUTE` | `30` | Basic requests-per-IP limit |
| `HISTORY_TURNS` | `8` | Number of recent conversation turns kept in memory |

## Course-material behaviour

Each uploaded document is:

1. checked for type and size,
2. converted to text,
3. divided into overlapping learning extracts,
4. stored in PostgreSQL or the local JSON fallback,
5. searched for relevant extracts when a student asks a question.

The tutor receives only the most relevant extracts, not every uploaded document. When it uses one, it is instructed to identify it as `[Source: filename]`.

Scanned image-only PDFs need OCR before upload because this MVP extracts embedded text rather than performing OCR.

## Visual and video tutor

The included visual tutor is a lightweight animated avatar. It speaks using the generated audio and works without a separate avatar subscription.

A photorealistic, live video tutor can be added later by replacing the avatar panel with a WebRTC-based avatar provider. Keep the FastAPI tutoring, course retrieval and student controls as the intelligence layer. Let the avatar provider handle only live video rendering and lip synchronisation.

## Production recommendations

Before opening the tutor to a large student population, add:

- student and lecturer authentication,
- programme, course and class enrolment controls,
- usage quotas and API cost controls,
- a lecturer dashboard for approved materials and tutor instructions,
- consent and privacy notices suitable for minors,
- database-backed conversation history when required,
- institutional logging and incident review,
- automated content-safety checks,
- accessibility testing,
- a paid Render service and persistent production database,
- backups and disaster-recovery procedures.

Render's free web service is suitable for testing but can sleep when idle. Free PostgreSQL is also temporary, so use a paid database for a real institutional rollout.

## Tests

Run:

```bash
DEMO_MODE=true ADMIN_KEY=test-admin pytest -q
```

The supplied test suite checks health, configuration, demonstration chat and administrator protection.

## Existing free Render database

The default `render.yaml` now creates only the web service. During Blueprint deployment, paste the Internal Database URL of your existing Render Postgres database into `DATABASE_URL`. See `RENDER_EXISTING_DATABASE_FIX.md`.

A separate `render-new-database.yaml` is retained for workspaces that have a free-database slot or will use a paid database.


## Version 1.1 response reliability

This package includes the empty-response retry fix described in `EMPTY_RESPONSE_FIX.md`. Recommended Render values are `AI_REASONING_EFFORT=low`, `AI_VERBOSITY=medium`, and `MAX_OUTPUT_TOKENS=6000`.
