# Anovlad Institutional AI Tutor v4.0

A Render-ready, course-controlled AI learning system for large student populations. Version 4.0 removes one-to-one live avatar video from normal student use and concentrates spending on text tutoring, voice, image analysis, visual explanations, guided practice and reusable class lessons.

## What makes v4.0 different

### 1. Course-locked tutoring

Each class has a teacher-controlled knowledge setting:

- **Course materials only**: answers are restricted to uploaded official materials.
- **Course materials plus approved sources**: the tutor may also use teacher-approved external readings.
- **General knowledge**: available only when the teacher deliberately enables it.

Materials can be uploaded globally by an administrator or directly into a teacher's class. Class materials are isolated from other classes.

### 2. Outcome-based teaching

Teachers define:

- Course learning outcomes
- Weekly topics
- Course-specific tutor instructions
- The permitted knowledge mode

Students select the relevant outcome and weekly topic before asking a question. Tutoring, practice, whiteboard checks and dashboard evidence are then connected to that learning context.

### 3. Step-level whiteboard assessment

Students can write with a mouse, stylus or finger, or upload a photograph of handwritten work. The tutor can:

- Review steps in their original order
- Mark each step as correct, warning, error or unreadable
- Identify the first incorrect step
- Highlight relevant regions on the image
- Explain the misconception
- Suggest the next action without immediately replacing the learner's work
- Record the result against the selected learning outcome

### 4. Teacher intelligence dashboard

The teacher dashboard includes:

- Student activity and average scores
- Weak topics
- Outcome mastery evidence
- Common misconceptions
- Students requiring intervention
- Frequently asked questions
- Questions the course-locked tutor could not answer from approved materials
- Provider, model, token and estimated cost summaries
- Course-profile editing and class join codes

### 5. Low-bandwidth learning

Students can choose:

- **Standard**: full text and visual explanations
- **Low data**: shorter responses, reduced visual load and no automatic speech
- **Text only**: compact answers without the whiteboard or voice

The app also provides:

- A service-worker application shell for faster repeat visits
- Browser recovery of the current workspace
- Downloadable self-contained HTML lesson packs
- Reusable class lesson scripts and slides
- Optional shared MP4 generation for a whole class

## AI provider routing

The default cost-control strategy is:

- **DeepSeek V4 Flash** for ordinary tutoring, practice, marking, whiteboard plans, dashboard-support tasks and lesson scripts
- **DeepSeek V4 Pro** only when the complexity router detects advanced work
- **OpenAI vision** for uploaded images, handwritten work, diagrams and screenshots
- **OpenAI transcription** for spoken student questions
- **OpenAI text-to-speech** for optional spoken answers

The teacher dashboard records model usage and estimated text-generation costs.

## Live video decision

One-to-one Tavus live conversations are retired. The old endpoint returns HTTP 410 with a migration message. The app's animated tutor, text, audio and interactive whiteboard remain available without per-minute avatar charges.

Teachers can create one reusable lesson package for a class. A package always includes a script and slides. Tavus MP4 generation is optional and is used only when `TAVUS_API_KEY` and `TAVUS_VIDEO_REPLICA_ID` are configured.

## Main student features

- Student registration and sign-in
- Class joining through a code
- Text and microphone questions
- Spoken tutor responses
- Image and camera input
- Interactive whiteboard
- Step-by-step explanations
- Graphs, tables, diagrams and lesson slides
- Guided practice with hints and marking
- Step-level work checking
- Learning-outcome and weekly-topic selection
- Personal progress dashboard
- Shared class lesson library
- Low-data and text-only modes
- Session recovery and downloadable lesson packs

## Main teacher features

- Teacher registration through a private invitation code
- Class creation and join-code management
- Course profile and knowledge-mode control
- Official and approved-external material uploads
- Student progress and intervention dashboard
- Outcome mastery and misconception reports
- Unanswered-question review
- AI usage and estimated cost monitoring
- Reusable lesson package generation

## Repository structure

```text
app/
  accounts.py       Accounts, classes, progress, dashboards and lesson records
  config.py         Environment configuration
  knowledge.py      Scoped course-material storage and retrieval
  main.py           FastAPI routes and orchestration
  prompts.py        Institutional teaching and assessment instructions
  providers.py      DeepSeek and OpenAI provider routing
  schemas.py        Validated API and structured-output models
  tavus.py          Optional reusable MP4 lesson generation
  static/
    index.html
    styles.css
    app.js
    v2_1.js
    portal.js
    manifest.webmanifest
    service-worker.js
tests/
render.yaml
requirements.txt
```

## Render deployment

This version is designed to use the existing Render PostgreSQL database. It does not declare or create another database.

1. Extract the package.
2. Upload the contents to the root of the GitHub `AITutor` repository.
3. Replace existing files and commit to `main`.
4. In Render, open `anovlad-ai-tutor`.
5. Add or confirm the variables below.
6. Select **Manual Deploy**, then **Clear build cache and deploy**.
7. After the service becomes Live, open `/health`.

Expected health fields include:

```json
{
  "status": "ok",
  "version": "4.0.0",
  "live_video_enabled": false,
  "institutional_mode": true,
  "course_lock_enabled": true,
  "low_bandwidth_enabled": true
}
```

## Required Render variables

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your DeepSeek API key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_ADVANCED_MODEL=deepseek-v4-pro
DEEPSEEK_THINKING=false
DEEPSEEK_ADVANCED_THINKING=false
ADVANCED_ROUTING_ENABLED=true
ADVANCED_ROUTING_MIN_SCORE=4
DEEPSEEK_MAX_TOKENS=6000

OPENAI_API_KEY=your OpenAI API key
AI_MODEL=gpt-5.6-luna
VISION_MODEL=gpt-5.6-luna
TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
DEFAULT_VOICE=nova

AUTH_SECRET=a long random secret
TEACHER_INVITE_CODE=a private teacher registration code
ALLOW_STUDENT_REGISTRATION=true
REQUIRE_LOGIN_FOR_AI=true
STUDENT_MONTHLY_AI_BUDGET_USD=1.00
ADMIN_KEY=a different long random secret
DATABASE_URL=the Internal Database URL of the existing Render database

INSTITUTIONAL_MODE=true
COURSE_LOCK_ENABLED=true
LOW_BANDWIDTH_ENABLED=true
LOW_DATA_MAX_TOKENS=1800
TEXT_ONLY_MAX_TOKENS=1200
ALLOW_GENERAL_KNOWLEDGE=false
LIVE_VIDEO_ENABLED=false
LESSON_VIDEO_ENABLED=true
STUDENT_VIDEO_MONTHLY_LIMIT=0
TEACHER_VIDEO_MONTHLY_LIMIT=20
DEMO_MODE=false
```

## Optional generated MP4 variables

Leave these blank when scripts and slides are sufficient:

```text
TAVUS_API_KEY=
TAVUS_VIDEO_REPLICA_ID=
```

No Tavus Persona ID, live Replica ID or live-minute setting is needed.

## First institutional setup

1. Sign in as a teacher.
2. Create a class.
3. Open the dashboard and edit the course profile.
4. Set the knowledge mode.
5. Add learning outcomes and weekly topics, one per line.
6. Add course-specific tutor instructions.
7. Upload official course materials into that class.
8. Share the class join code with students.
9. Review unanswered questions and add missing approved materials where necessary.

## Existing database upgrade

The app creates missing v4.0 columns and indexes during startup. Existing users, classes and learning events are retained. The new class fields include knowledge mode, learning outcomes, weekly topics and tutor instructions. Knowledge chunks gain class and material-type scope.

Back up the database before a production upgrade.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

## Validation

```bash
python -m compileall -q app
node --check app/static/app.js
node --check app/static/v2_1.js
node --check app/static/portal.js
pytest -q
```

The supplied release passes 24 automated tests. External DeepSeek, OpenAI and Tavus calls require the institution's own API credentials and should be verified after deployment.

## Security and scale

- Keep all API keys in Render Environment, never in GitHub.
- Keep `REQUIRE_LOGIN_FOR_AI=true` in production.
- Use a paid Render PostgreSQL plan for a large institutional deployment.
- Add email verification or institutional single sign-on before broad public registration.
- Put rate limits and monthly budgets behind authenticated student identities.
- Pilot with representative courses before enabling 30,000 accounts.
- Review provider retention and institutional data-governance requirements before uploading sensitive student records.
