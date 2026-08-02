# Render Deployment Checklist, AI Tutor v2.1

## GitHub

- [ ] The repository root directly contains `app`, `tests`, `render.yaml`, `requirements.txt` and `README.md`.
- [ ] `app/static/v2_1.js` is present.
- [ ] The v2.1 files have been committed to the `main` branch.
- [ ] No `.env` file, API key or database password was committed.

## Render environment

- [ ] `OPENAI_API_KEY` contains the active project key.
- [ ] `AI_MODEL` is `gpt-5.6-luna`.
- [ ] `AI_REASONING_EFFORT` is `low`.
- [ ] `AI_VERBOSITY` is `medium`.
- [ ] `MAX_OUTPUT_TOKENS` is `6000`.
- [ ] `VISUAL_PLAN_ENABLED` is `true`.
- [ ] `VISUAL_MAX_OUTPUT_TOKENS` is `3500`.
- [ ] `IMAGE_DETAIL` is `high`.
- [ ] `TRANSCRIBE_MODEL` is `gpt-4o-mini-transcribe`.
- [ ] `TTS_MODEL` is `gpt-4o-mini-tts`.
- [ ] `DEFAULT_VOICE` is `nova`.
- [ ] `DEMO_MODE` is `false`.
- [ ] `DATABASE_URL` contains the existing database's Internal Database URL.
- [ ] `ADMIN_KEY` is stored safely.

## Deploy

- [ ] Open the current `anovlad-ai-tutor` web service.
- [ ] Select **Manual Deploy**.
- [ ] Select **Clear build cache and deploy**.
- [ ] Wait for the service status to become **Live**.
- [ ] Open `/health` and confirm version `2.1.0`.
- [ ] Confirm `openai_enabled: true`, `visual_plan_enabled: true` and `image_detail: high`.
- [ ] Refresh the tutor with `Ctrl + Shift + R`.

## Functional test

- [ ] Ask for a worked calculation and select **Teach step by step**.
- [ ] Pause or stop the synchronised narration.
- [ ] Start a guided practice activity with at least two questions.
- [ ] Submit one typed answer and review the hint or score.
- [ ] Use the whiteboard for a practice answer.
- [ ] Select **Show solution** and confirm the activity advances.
- [ ] Write on the board and select **Check my work**.
- [ ] Confirm feedback includes a score, strengths, corrections and next step.
- [ ] Edit graph or table data through **Edit visual**.
- [ ] Drag a diagram node.
- [ ] Refresh the browser and confirm the workspace is restored.
- [ ] Upload an image and request highlighted corrections.
- [ ] Test Pen, Highlighter, Eraser, Undo, Redo and Clear ink.
- [ ] Download the board as PNG.
- [ ] Attach the board and ask a follow-up question.
- [ ] Record and transcribe an audio question.
- [ ] Play the spoken answer.
