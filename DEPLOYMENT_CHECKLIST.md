# AI Tutor v4.0 Render Deployment Checklist

## 1. Prepare GitHub

- Extract the v4.0 package or patch.
- Upload the contents to the root of `yawanokye/AITutor`.
- Confirm `render.yaml`, `requirements.txt` and the `app` folder are at repository root.
- Replace the older files and commit to `main`.
- Do not upload `.env` or any API key.

## 2. Protect the database

- Keep the existing Render PostgreSQL database.
- Copy its Internal Database URL into `DATABASE_URL`.
- Take a backup before the production upgrade.
- Do not add a `databases:` section to `render.yaml`.

## 3. Configure DeepSeek

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_ADVANCED_MODEL=deepseek-v4-pro
DEEPSEEK_THINKING=false
DEEPSEEK_ADVANCED_THINKING=false
ADVANCED_ROUTING_ENABLED=true
ADVANCED_ROUTING_MIN_SCORE=4
```

## 4. Configure OpenAI for vision and audio

```text
OPENAI_API_KEY=...
AI_MODEL=gpt-5.6-luna
VISION_MODEL=gpt-5.6-luna
TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
DEFAULT_VOICE=nova
```

## 5. Configure accounts and controls

```text
AUTH_SECRET=long random secret
TEACHER_INVITE_CODE=private teacher code
ALLOW_STUDENT_REGISTRATION=true
REQUIRE_LOGIN_FOR_AI=true
STUDENT_MONTHLY_AI_BUDGET_USD=1.00
ADMIN_KEY=different long random secret
DATABASE_URL=existing Internal Database URL
```

## 6. Enable the institutional model

```text
INSTITUTIONAL_MODE=true
COURSE_LOCK_ENABLED=true
ALLOW_GENERAL_KNOWLEDGE=false
LOW_BANDWIDTH_ENABLED=true
LOW_DATA_MAX_TOKENS=1800
TEXT_ONLY_MAX_TOKENS=1200
```

## 7. Retire live video

```text
LIVE_VIDEO_ENABLED=false
STUDENT_VIDEO_MONTHLY_LIMIT=0
LESSON_VIDEO_ENABLED=true
TEACHER_VIDEO_MONTHLY_LIMIT=20
```

Remove obsolete variables where convenient:

```text
TAVUS_PERSONA_ID
TAVUS_REPLICA_ID
TAVUS_LIVE_MAX_MINUTES
TAVUS_TEST_MODE
```

For optional reusable MP4 lessons, add only:

```text
TAVUS_API_KEY=...
TAVUS_VIDEO_REPLICA_ID=...
```

## 8. Deploy

- Open the `anovlad-ai-tutor` Render service.
- Choose **Manual Deploy**.
- Select **Clear build cache and deploy**.
- Wait until the status is Live.
- Refresh the browser with `Ctrl + Shift + R`.

## 9. Verify

Open `/health` and confirm:

```text
version = 4.0.0
live_video_enabled = false
institutional_mode = true
course_lock_enabled = true
low_bandwidth_enabled = true
```

Then verify:

- Teacher registration works with the invitation code.
- A teacher can create a class and edit its profile.
- Learning outcomes and weekly topics appear in the tutor.
- Official materials can be uploaded to the selected class.
- A student can join with the class code.
- Course-only questions show approved source labels.
- Missing-material questions appear in the teacher dashboard.
- Guided practice and whiteboard checking record progress.
- Low-data and text-only modes work.
- The lesson pack downloads as HTML.
- The old live-video endpoint is not exposed in the interface.
- Reusable lesson scripts and slides are visible to enrolled students.

## 10. Production readiness for large enrolment

- Move the web service and PostgreSQL database off free plans.
- Run a staged load test before opening registration to all students.
- Add institutional SSO or verified institutional email accounts.
- Set provider budgets and alerts.
- Establish data retention, privacy, moderation and incident procedures.
- Train teachers to review unanswered questions and course-source coverage.
