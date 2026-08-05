# Anovlad Institutional AI Tutor v5.1.1

A Render-ready, role-based AI learning platform for institutions. Administration, teaching and learning use dedicated portals, while lecturer-approved course documents become a structured, selectable AI tutoring environment.

Version 5.1 provides a simpler course-first student interface, lecturer-controlled typed, voice or handwritten practice responses, vertically expandable full-screen whiteboards, week-by-week course-outline activities, outcome-generated teaching notes when readings are absent, and detailed visual teaching that matches the written notes. It retains the document ownership and deletion safeguards introduced in v5.0.3.


## v5.1.1 course-outline table correction

Version 5.1.1 corrects Word course outlines that place the teaching schedule in a table headed **Period**, **Topics**, and **Student’s Preparation**. The parser now preserves each paragraph inside table cells, converts number words such as One–Twenty into Week 1–20, creates selectable week topics and subtopics, extracts preparation activities, reads the course title from the course-information table, and combines course objectives with expected outcomes.

Outlines uploaded before v5.1.1 do not contain the original Word file bytes in the database. After deploying this release, the lecturer must re-upload each affected outline once. Uploading the same filename and category replaces the old parsed structure and indexed text.

## v5.1 student learning workspace

- Students work from **My courses**, open an enrolled course, and select a week, section or subsection. Provider, administrator and lecturer-only controls are hidden.
- Lecturers set each course to student choice, typed response, recorded voice response or handwritten whiteboard response for practice activities.
- The practice whiteboard grows downward, scrolls vertically and opens full screen. The teaching whiteboard also opens full screen.
- Word course outlines can be organised with Heading styles or Week, Topic and Activities tables. Weeks and subunits become selectable lessons.
- When readings or detailed notes are missing, the tutor develops a complete instructional expansion from objectives, expected outcomes, weekly topics and lecturer instructions.
- Broad topics are divided into prerequisite and supporting subtopics when needed for complete understanding.
- Every slide displays its detailed explanation, worked example, self-check and teaching note, so the whiteboard is not less informative than the written lesson.

## What is new in v5.0

### Administrator portal

The first administrator can be created securely through a one-time bootstrap screen or provisioned from Render environment variables. Administrators can then:

- Create lecturer accounts without allowing public lecturer registration
- Generate or enter a temporary lecturer password
- Copy lecturer credentials for secure delivery
- Activate or deactivate lecturer accounts
- Reset lecturer passwords
- View institutional users, courses, activity and AI usage

Lecturers created by an administrator are required to change their temporary password.

### Lecturer portal

Each lecturer can:

- Create and manage courses
- Receive an automatically generated student enrolment code
- Copy or regenerate an enrolment code
- Define course objectives and weekly topics
- Add recommended readings and lecturer-specific tutor instructions
- Select the permitted knowledge mode for each course
- Require handwritten responses for practice activities
- Upload teaching notes, a detailed course outline and recommended reading materials
- Review the detected document structure before students use it
- Remove outdated course documents
- View student progress, misconceptions, weak topics and AI usage

### Student portal

Students can:

- Create a student account and sign in
- Enrol in a course using the lecturer-generated code
- Open a course and browse its uploaded documents
- Expand documents into sections and subsections
- Select a subsection and generate a detailed AI lesson grounded in that subsection
- Receive detailed slides, worked examples, definitions, explanations and self-check questions
- Ask text or audio questions
- Upload images or photographs of handwritten work
- Use the visual explanation whiteboard
- Use a separate practice whiteboard when handwriting is required
- Complete guided practice and view progress

## Structured course-content workflow

The lecturer uploads one or more of the following document types:

1. **Detailed course outline**
   - Course description
   - Course objectives or learning outcomes
   - Weekly topics
   - Recommended readings

2. **Teaching notes**
   - Units, chapters, sections and subsections
   - Definitions, explanations, examples and exercises

3. **Recommended reading**
   - Approved articles, chapters, handouts or other supplementary materials

The app extracts headings and builds a nested course structure. When a student selects a section or subsection, the tutor receives:

- The selected section text
- Relevant extracts from approved teaching notes
- Relevant extracts from recommended readings
- The course objectives
- The lecturer's instructions
- The course knowledge restrictions

The tutor then produces a grounded explanation and a detailed slide lesson.

## Preparing documents for accurate section detection

For DOCX files, use Word heading styles:

- **Heading 1** for units or major topics
- **Heading 2** for sections
- **Heading 3** for subsections

For PDF, TXT and Markdown files, use clear numbered headings such as:

```text
Unit 1: Introduction
1.1 Meaning and scope
1.2 Key concepts
1.2.1 Worked example
```

Use recognisable headings such as **Course Objectives**, **Learning Outcomes**, **Recommended Reading** or **References** in the detailed course outline.

The app extracts selectable text. A scanned PDF containing only page images must first be converted into a searchable PDF with OCR before upload.

Supported course-document formats are PDF, DOCX, TXT, MD and CSV. The default upload limit is 30 MB per file.

## Detailed slide teaching

A subsection lesson can generate 4 to 14 detailed slides. Slides can include:

- A clear teaching title and learning focus
- Detailed explanatory paragraphs
- Ordered teaching points
- Equations
- Worked examples
- Key terms and definitions
- Common misconceptions and corrections
- Check-your-understanding questions
- Expanded speaker notes for narrated teaching

Students can move through slides manually or use step-by-step narrated teaching. The slides are generated from the selected subsection and relevant approved readings rather than from a topic title alone.

## Two whiteboards

### Visual explanation whiteboard

Used by the AI Tutor to display:

- Step-by-step calculations
- Graphs and tables
- Labelled diagrams
- Lesson slides
- Image annotations

### Practice-response whiteboard

A separate student workspace used for handwritten responses. It supports:

- Mouse, touch and stylus writing
- Pen and eraser
- Colour selection
- Undo and clear
- Submission as a white-background PNG for AI marking

A lecturer can make this whiteboard compulsory for a course. When compulsory, a typed-only practice answer is rejected until the student submits written work from the practice board.

## AI provider routing

The cost-control strategy remains:

- **DeepSeek V4 Flash** for ordinary tutoring, course-section lessons, guided practice, marking, visual plans and lesson scripts
- **DeepSeek V4 Pro** only when the complexity router identifies advanced work
- **OpenAI vision** for images, handwriting, diagrams and screenshots
- **OpenAI transcription** for spoken student questions
- **OpenAI text-to-speech** for optional spoken answers

Live one-to-one avatar video remains disabled. Reusable lesson scripts and slides are available for classes, with optional shared MP4 generation when Tavus credentials are configured.

## Repository structure

```text
app/
  accounts.py          Users, roles, courses, enrolment and dashboards
  course_content.py    Document parsing, hierarchy and section retrieval
  config.py            Environment settings
  knowledge.py         Course-scoped retrieval store
  main.py              FastAPI routes and orchestration
  prompts.py           Tutor, course-section and slide instructions
  providers.py         DeepSeek and OpenAI routing
  schemas.py           API and structured-output models
  tavus.py             Optional shared lesson-video generation
  static/
    index.html
    styles.css
    portal.js
    app.js
    v2_1.js
    practice_board.js
    service-worker.js
    manifest.webmanifest
tests/
render.yaml
requirements.txt
```

## Deploying to Render

This release uses the existing Render PostgreSQL database. It does not create a second database.

1. Back up the existing database.
2. Extract the v5.0 package or patch.
3. Upload the contents to the root of the GitHub `AITutor` repository.
4. Replace the older files and commit to `main`.
5. Open the `anovlad-ai-tutor` web service in Render.
6. Add or confirm the environment variables below.
7. Select **Manual Deploy**, then **Clear build cache and deploy**.
8. Wait until the service is Live.
9. Open `/health` and confirm version `5.1.1`.
10. Refresh the browser with `Ctrl + Shift + R`.

Expected health fields include:

```json
{
  "status": "ok",
  "version": "5.1.1",
  "administrator_portal_enabled": true,
  "lecturer_managed_enrolment": true,
  "structured_course_content_enabled": true,
  "separate_practice_whiteboard_enabled": true,
  "detailed_slide_teaching_enabled": true,
  "live_video_enabled": false
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
DEEPSEEK_MAX_TOKENS=7000

OPENAI_API_KEY=your OpenAI API key
AI_MODEL=gpt-5.6-luna
VISION_MODEL=gpt-5.6-luna
TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
DEFAULT_VOICE=nova

AUTH_SECRET=a long random secret
ACCESS_TOKEN_MINUTES=1440
ALLOW_PUBLIC_TEACHER_REGISTRATION=false
ALLOW_STUDENT_REGISTRATION=true
REQUIRE_LOGIN_FOR_AI=true
STUDENT_MONTHLY_AI_BUDGET_USD=1.00
ADMIN_KEY=a separate long random bootstrap secret
DATABASE_URL=the existing Render Internal Database URL

INSTITUTIONAL_MODE=true
COURSE_LOCK_ENABLED=true
ALLOW_GENERAL_KNOWLEDGE=true
LOW_BANDWIDTH_ENABLED=true
MAX_MATERIAL_MB=30
LIVE_VIDEO_ENABLED=false
LESSON_VIDEO_ENABLED=true
DEMO_MODE=false
```

`ALLOW_GENERAL_KNOWLEDGE=true` only makes the lecturer-controlled general mode available. It does not automatically remove the course lock from every course. New courses can remain restricted to course materials.

## Creating the first administrator

There are two supported methods.

### Method A: one-time setup through the app

1. Leave `ADMIN_EMAIL` and `ADMIN_PASSWORD` blank.
2. Copy the generated `ADMIN_KEY` from Render Environment.
3. Open the app and select **Sign in or register**.
4. Select **First administrator**.
5. Enter the administrator name, email, password and `ADMIN_KEY`.
6. Submit the form.

The bootstrap endpoint works only when no administrator account exists.

### Method B: automatic setup from Render

Set:

```text
ADMIN_EMAIL=administrator@institution.edu
ADMIN_PASSWORD=a strong initial password
ADMIN_DISPLAY_NAME=System Administrator
```

The app creates the administrator at startup if that email does not already exist. Remove `ADMIN_PASSWORD` from Render after the account has been created and tested.

## Administrator workflow

1. Sign in to the **Administrator portal**.
2. Select **Create lecturer account**.
3. Enter the lecturer's name and institutional email.
4. Leave the temporary-password field blank to generate one automatically, or enter a temporary password.
5. Copy the generated credentials and deliver them privately.
6. The lecturer signs in and changes the temporary password.
7. Use the portal to deactivate an account or reset its password when required.

Public lecturer registration should remain disabled in production.

## Lecturer workflow

1. Sign in to the **Lecturer portal**.
2. Create a course by entering the course name and subject.
3. Copy the generated enrolment code.
4. Configure:
   - Knowledge mode
   - Course objectives
   - Weekly topics
   - Recommended readings
   - Tutor instructions
   - Handwritten-practice requirement
5. Upload the detailed course outline.
6. Upload teaching notes.
7. Upload approved recommended readings.
8. Review the detected document sections.
9. Share the enrolment code with the appropriate students.
10. Review student activity, mastery, misconceptions and unanswered questions.

Uploading a detailed course outline can automatically merge detected objectives and readings into the course profile. The lecturer can still edit the course profile afterwards.

## Student workflow

1. Register as a student and sign in.
2. Open the **Student portal**.
3. Enter the lecturer's enrolment code.
4. Open the enrolled course.
5. Expand a document and select a section or subsection.
6. Choose the required lesson detail.
7. Generate the grounded AI Tutor lesson.
8. Review the detailed slides and narrated explanation.
9. Start guided practice where required.
10. Use the separate practice whiteboard when the course requires handwritten work.

## Database upgrade

At startup, the app creates missing v5.0 tables, columns and indexes. Existing users, courses, enrolments and learning events are retained. New persistent structures include:

- Lecturer accounts created by administrators
- Account status and temporary-password flags
- Course recommended readings
- Course handwriting requirements
- Uploaded course documents
- Nested document sections and subsections

Back up the database before deploying to a production service.

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


## v5.1 rollout checks

1. Sign in as a lecturer and open a course profile. Set **Required practice-response format** to Student choice, Typed, Recorded voice or Whiteboard.
2. Upload a Word course outline that uses Heading styles or a table with Week, Topic and Activities columns.
3. Sign in as a student, open **My courses**, select the course and confirm that the weekly activities and subunits appear.
4. Start practice and verify that only the lecturer-approved response method is available.
5. Test the practice board's **Writing space** and **Full screen** buttons.
6. Open a detailed course lesson and confirm that expanded teaching notes are visible on each whiteboard slide.

No manual database migration or new environment variable is required. The `practice_response_mode` column is created automatically at startup.

## Validation

```bash
python -m compileall -q app
node --check app/static/app.js
node --check app/static/v2_1.js
node --check app/static/portal.js
node --check app/static/practice_board.js
pytest -q
```

The supplied release passes 37 automated tests. External DeepSeek, OpenAI and optional Tavus calls require the institution's own API credentials and should be verified after deployment.

## Security and scale

- Keep every API key and database URL in Render Environment, never in GitHub.
- Keep `ALLOW_PUBLIC_TEACHER_REGISTRATION=false`.
- Deliver temporary lecturer passwords through a private channel.
- Use institutional email verification or single sign-on before a 30,000-student rollout.
- Use a paid PostgreSQL service with backups, monitoring and adequate connection limits.
- Add background workers and object storage for large document and media workloads.
- Pilot document parsing with representative course outlines and notes.
- Review copyright permissions before uploading recommended readings.
- Review institutional privacy, retention and AI-governance requirements before production use.


## v5.1.0 document ownership and deletion

- Administrator repository uploads remain private to administrators and are not mixed into lecturer courses.
- Lecturers can upload and delete documents only inside courses they manage.
- Deleting a lecturer document removes its parsed sections and retrieval index, so deleted text cannot continue influencing the tutor.
- Replacing a same-name document clears the old index before creating the new one.
- Students see every course they have joined, including courses taught by different lecturers.

See `V5_0_3_EFFECTIVE_DOCUMENT_ISOLATION_FIX.md` for the current corrective upgrade notes. The v5.0.2 document is retained only as historical release information.
