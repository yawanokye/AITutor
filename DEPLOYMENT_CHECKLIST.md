# Render Deployment Checklist, AI Tutor v2.0

## GitHub

- [ ] The repository root directly contains `app`, `render.yaml`, `requirements.txt` and `README.md`.
- [ ] The v2.0 files have been committed to the `main` branch.
- [ ] No `.env` file, API key or database password was committed.

## Render environment

- [ ] `OPENAI_API_KEY` contains the active project key.
- [ ] `AI_MODEL` is `gpt-5.6-luna`.
- [ ] `AI_REASONING_EFFORT` is `low`.
- [ ] `AI_VERBOSITY` is `medium`.
- [ ] `MAX_OUTPUT_TOKENS` is `6000`.
- [ ] `VISUAL_PLAN_ENABLED` is `true`.
- [ ] `VISUAL_MAX_OUTPUT_TOKENS` is `3500`.
- [ ] `IMAGE_DETAIL` is `original`.
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
- [ ] Open `/health` and confirm version `2.0.0` and `visual_plan_enabled: true`.
- [ ] Refresh the tutor with `Ctrl + Shift + R`.

## Functional test

- [ ] Ask for a worked calculation and move through the steps.
- [ ] Ask for a graph.
- [ ] Ask for a comparison table.
- [ ] Ask for a labelled diagram.
- [ ] Upload an image and request highlighted corrections.
- [ ] Ask for lesson slides.
- [ ] Draw with Pen and Highlighter.
- [ ] Test Undo, Redo and Clear ink.
- [ ] Download the board as PNG.
- [ ] Attach the board and ask a follow-up question.
- [ ] Record and transcribe an audio question.
- [ ] Play the spoken answer.
