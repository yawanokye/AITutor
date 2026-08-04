# AI Tutor v5.0 Render Deployment Checklist

## A. Before deployment

- [ ] Back up the existing Render PostgreSQL database.
- [ ] Download and extract the v5.0 full package or patch.
- [ ] Confirm `render.yaml` is at the GitHub repository root.
- [ ] Upload and replace the existing application files.
- [ ] Commit the changes to the `main` branch.
- [ ] Confirm no `.env` file, API key or database password was committed.

## B. Required Render environment

### DeepSeek text tutoring

- [ ] `AI_PROVIDER=deepseek`
- [ ] `DEEPSEEK_API_KEY` is set.
- [ ] `DEEPSEEK_BASE_URL=https://api.deepseek.com`
- [ ] `DEEPSEEK_MODEL=deepseek-v4-flash`
- [ ] `DEEPSEEK_ADVANCED_MODEL=deepseek-v4-pro`
- [ ] `ADVANCED_ROUTING_ENABLED=true`
- [ ] `DEEPSEEK_MAX_TOKENS=7000`

### OpenAI image and audio

- [ ] `OPENAI_API_KEY` is set.
- [ ] `VISION_MODEL=gpt-5.6-luna`
- [ ] `TRANSCRIBE_MODEL=gpt-4o-mini-transcribe`
- [ ] `TTS_MODEL=gpt-4o-mini-tts`
- [ ] `DEFAULT_VOICE=nova`

### Accounts and portals

- [ ] `AUTH_SECRET` is a long random secret.
- [ ] `ADMIN_KEY` is a different long random secret.
- [ ] `ALLOW_PUBLIC_TEACHER_REGISTRATION=false`
- [ ] `ALLOW_STUDENT_REGISTRATION=true`
- [ ] `REQUIRE_LOGIN_FOR_AI=true`
- [ ] `DATABASE_URL` contains the existing database's Internal Database URL.

### Institutional controls

- [ ] `INSTITUTIONAL_MODE=true`
- [ ] `COURSE_LOCK_ENABLED=true`
- [ ] `ALLOW_GENERAL_KNOWLEDGE=true` if lecturers may enable general mode for selected courses.
- [ ] `LOW_BANDWIDTH_ENABLED=true`
- [ ] `MAX_MATERIAL_MB=30`
- [ ] `LIVE_VIDEO_ENABLED=false`
- [ ] `LESSON_VIDEO_ENABLED=true`
- [ ] `DEMO_MODE=false`

## C. Create the first administrator

Choose one method only.

### One-time app bootstrap

- [ ] Keep `ADMIN_EMAIL` and `ADMIN_PASSWORD` blank.
- [ ] Copy `ADMIN_KEY` from Render.
- [ ] Open **Sign in or register → First administrator**.
- [ ] Enter the administrator details and bootstrap key.
- [ ] Confirm the administrator can sign in.

### Automatic Render provisioning

- [ ] Set `ADMIN_EMAIL`.
- [ ] Set a strong `ADMIN_PASSWORD`.
- [ ] Set `ADMIN_DISPLAY_NAME`.
- [ ] Deploy and confirm the administrator can sign in.
- [ ] Remove `ADMIN_PASSWORD` from Render after successful setup.

## D. Deploy

- [ ] Open the `anovlad-ai-tutor` Render web service.
- [ ] Select **Manual Deploy**.
- [ ] Select **Clear build cache and deploy**.
- [ ] Wait for the status to become **Live**.
- [ ] Open `/health`.
- [ ] Confirm `version` is `5.1.0`.
- [ ] Confirm the five new capability flags are `true`.
- [ ] Refresh the browser with `Ctrl + Shift + R`.

## E. Administrator portal test

- [ ] Sign in as administrator.
- [ ] Create a test lecturer account.
- [ ] Copy the generated temporary password.
- [ ] Sign in as the lecturer.
- [ ] Change the temporary password.
- [ ] Test administrator password reset.
- [ ] Test lecturer deactivation and reactivation.

## F. Lecturer portal test

- [ ] Create a test course.
- [ ] Copy the generated enrolment code.
- [ ] Regenerate the code and confirm the old code is replaced.
- [ ] Add course objectives.
- [ ] Add weekly topics.
- [ ] Add recommended readings.
- [ ] Add lecturer tutor instructions.
- [ ] Enable or disable required handwritten practice.
- [ ] Upload a detailed course outline.
- [ ] Upload teaching notes.
- [ ] Upload a recommended reading.
- [ ] Confirm headings are displayed as sections and subsections.
- [ ] Confirm extracted objectives and readings appear in the course profile.

## G. Student portal test

- [ ] Register a student account.
- [ ] Enrol using the lecturer-generated code.
- [ ] Open the course.
- [ ] Expand the detailed outline and teaching notes.
- [ ] Select a subsection.
- [ ] Confirm the AI Tutor response cites uploaded course sources.
- [ ] Confirm detailed slides contain explanations, examples and self-checks.
- [ ] Test text and audio questions.
- [ ] Test image and handwriting analysis.
- [ ] Test the visual explanation whiteboard.
- [ ] Test the separate practice whiteboard.
- [ ] Confirm typed-only practice is blocked when handwriting is compulsory.

## H. Document quality test

- [ ] DOCX files use Heading 1, Heading 2 and Heading 3 styles.
- [ ] PDF files contain selectable text.
- [ ] Scanned PDFs have been OCR-processed before upload.
- [ ] Recommended readings have institutional copyright permission.
- [ ] Uploaded documents belong to the correct course.

## I. Production readiness

- [ ] Move from Render's free database to a paid, backed-up PostgreSQL plan.
- [ ] Configure institutional email verification or SSO.
- [ ] Review rate limits and per-student AI budgets.
- [ ] Configure monitoring and alerting.
- [ ] Define lecturer-account approval and offboarding procedures.
- [ ] Define document copyright and data-retention rules.
- [ ] Pilot with representative courses before a 30,000-student rollout.


## Document isolation checks

- [ ] Administrator repository documents are visible only in the Administrator Portal.
- [ ] Lecturer A cannot see Lecturer B's uploaded documents.
- [ ] Deleting a lecturer document removes it from both course contents and indexed materials.
- [ ] A student enrolled in two or more courses sees every enrolled course.

## Effective v5.1.0 document verification

- [ ] Open the Administrator Portal and confirm each private document has a Delete button.
- [ ] Delete one older administrator upload and confirm the success message reports indexed extracts removed.
- [ ] Sign in as a lecturer and confirm no administrator-private document appears.
- [ ] Upload a document to Lecturer A's course and confirm Lecturer B cannot see it.
- [ ] Delete a lecturer course document and confirm it disappears from both the course tree and course-material list.
- [ ] Ask a question containing a unique phrase from the deleted document and confirm the source is no longer retrieved.
- [ ] Confirm `/health` reports version `5.1.0`.

## v5.1 functional verification

- [ ] Student sign-in shows a course-first interface without provider, administrator or lecturer controls.
- [ ] **My courses** lists every course in which the student is enrolled.
- [ ] Course outline weeks, activities and subunits are visible and selectable.
- [ ] Lecturer can choose Student choice, Typed, Recorded voice or Whiteboard for practice responses.
- [ ] Typed practice response submits successfully.
- [ ] Voice practice response records, previews, transcribes and submits successfully.
- [ ] Practice whiteboard accepts handwriting and submits the image for marking.
- [ ] **Writing space** increases the board height and the board scrolls vertically.
- [ ] Both teaching and practice whiteboards open full screen.
- [ ] A course with objectives and outcomes but no reading upload still produces a detailed lesson.
- [ ] Detailed whiteboard slides show explanations and teaching notes at the same depth as the written lesson.

