# AI Tutor v5.4 Render Deployment Checklist

## 1. Before deployment

- [ ] Back up the existing Render PostgreSQL database.
- [ ] Extract the v5.4 full package or upgrade patch.
- [ ] Upload the contents to the root of the GitHub `AITutor` repository.
- [ ] Replace existing files and commit to `main`.
- [ ] Confirm `render.yaml`, `requirements.txt` and the `app` folder are at the repository root.
- [ ] Confirm no `.env` file or secret was committed.

## 2. Existing Render variables

Keep the current variables. No new v5.4 variable is required.

### DeepSeek

- [ ] `AI_PROVIDER=deepseek`
- [ ] `DEEPSEEK_API_KEY` is set.
- [ ] `DEEPSEEK_BASE_URL=https://api.deepseek.com`
- [ ] `DEEPSEEK_MODEL=deepseek-v4-flash`
- [ ] `DEEPSEEK_ADVANCED_MODEL=deepseek-v4-pro`
- [ ] `ADVANCED_ROUTING_ENABLED=true`

### OpenAI vision and audio

- [ ] `OPENAI_API_KEY` is set.
- [ ] `VISION_MODEL=gpt-5.6-luna`
- [ ] `TRANSCRIBE_MODEL=gpt-4o-mini-transcribe`
- [ ] `TTS_MODEL=gpt-4o-mini-tts`
- [ ] `DEFAULT_VOICE=nova`

### Accounts and institutional controls

- [ ] `DATABASE_URL` is the existing Render Internal Database URL.
- [ ] `AUTH_SECRET` remains unchanged.
- [ ] `ADMIN_KEY` is private.
- [ ] `ALLOW_PUBLIC_TEACHER_REGISTRATION=false`
- [ ] `ALLOW_STUDENT_REGISTRATION=true`
- [ ] `REQUIRE_LOGIN_FOR_AI=true`
- [ ] `INSTITUTIONAL_MODE=true`
- [ ] `COURSE_LOCK_ENABLED=true`
- [ ] `LOW_BANDWIDTH_ENABLED=true`
- [ ] `LIVE_VIDEO_ENABLED=false`
- [ ] `DEMO_MODE=false`

## 3. Deploy

- [ ] Open the `anovlad-ai-tutor` Render web service.
- [ ] Select **Manual Deploy**.
- [ ] Select **Clear build cache and deploy**.
- [ ] Wait until the service is **Live**.
- [ ] Open `https://anovlad-ai-tutor.onrender.com/health`.
- [ ] Confirm `version` is `5.5.0`.
- [ ] Confirm the diagnostic, pathway, assessment, remediation, revision, notes, integrity and accessibility flags are `true`.

## 4. Browser refresh

- [ ] Sign out of the app.
- [ ] Press `Ctrl + Shift + R`.
- [ ] Sign in again.
- [ ] On a phone, close and reopen the browser tab if the old interface remains.

## 5. Lecturer checks

- [ ] Open a course profile.
- [ ] Confirm Entry diagnostic, Spaced revision, Mastery pass mark and Academic integrity controls are visible.
- [ ] Save the course profile and reopen it to confirm the values persist.
- [ ] Open **Assessment and question bank**.
- [ ] Generate an editable draft.
- [ ] Edit a question, expected answer and marking guide.
- [ ] Configure attempts, hints, answer reveal, pass mark and integrity mode.
- [ ] Publish the assessment.
- [ ] Confirm Students needing intervention, Common misconceptions and Revision backlog are visible.

## 6. Student checks

- [ ] Open the Student Portal.
- [ ] Confirm Recommended next appears above the course list.
- [ ] Start and submit the entry diagnostic.
- [ ] Confirm the personalised pathway and question-level outcome/topic mastery evidence update.
- [ ] Complete typed, oral and handwritten guided-practice responses.
- [ ] Start a published assessment.
- [ ] Test an oral response and an uploaded written or handwritten response.
- [ ] Save a private note and bookmark the latest explanation.
- [ ] Open the printable revision sheet and download the DOCX version.
- [ ] Confirm Due for review displays scheduled retrieval practice after assessment.
- [ ] Test Explain more simply, Another example, Show the working, Why is this important and Test me now.
- [ ] Test Larger text, Reading-friendly font and High contrast.

## 7. Database checks

The following tables are created automatically:

- `ai_tutor_course_policies`
- `ai_tutor_assessments`
- `ai_tutor_assessment_attempts`
- `ai_tutor_mastery_records`
- `ai_tutor_revision_items`
- `ai_tutor_student_notes`

- [ ] Confirm the service logs show no database migration error.
- [ ] Do not run a separate SQL migration unless startup reports a database-permission problem.

## 8. Production notes

- [ ] Keep a paid PostgreSQL plan and regular backups for institutional use.
- [ ] Pilot diagnostics and mastery thresholds with representative lecturers before applying them widely.
- [ ] Review AI-generated draft questions before publication.
- [ ] Treat mastery certificates as learning evidence generated from the app, not as official University awards unless formally approved.

## v5.5 lesson continuity checks

- [ ] During an active guided lecture, select **Ask about this point**.
- [ ] Confirm the slide remains visible behind the popup and the main lecture audio pauses.
- [ ] Ask a question during a Week 2 lesson and confirm the response refers to the active Week 2 section, not an earlier week.
- [ ] Confirm the clarification uses the separate popup audio player.
- [ ] Select **Continue lesson** and confirm the original audio resumes from the same position.
- [ ] Switch between two enrolled courses and confirm each restores a separate conversation and visual workspace.
- [ ] Open **Learning memory** and clear the current course memory.
- [ ] Confirm assessment scores, mastery, notes and enrolment remain unchanged.
- [ ] Confirm slides do not display statements about being linked to detailed notes.
- [ ] Confirm key-idea cards do not include week labels or numbering.
