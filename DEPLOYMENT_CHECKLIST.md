# Deployment checklist

## Before deployment

- [ ] Push all project files to a private or controlled repository.
- [ ] Obtain an OpenAI API key with billing and usage limits configured.
- [ ] Decide whether the app is a pilot or production service.
- [ ] Prepare approved course materials.
- [ ] Decide who will hold the administrator key.

## Render setup

- [ ] Create the Blueprint from `render.yaml`.
- [ ] Enter `OPENAI_API_KEY` as a secret.
- [ ] Confirm `DEMO_MODE=false`.
- [ ] Confirm the PostgreSQL database is connected through `DATABASE_URL`.
- [ ] Confirm `/health` returns `status: ok`.
- [ ] Record the generated `ADMIN_KEY` securely.

## Functional test

- [ ] Text question receives a useful answer.
- [ ] Microphone permission and transcription work.
- [ ] JPG or PNG analysis works.
- [ ] Spoken response plays.
- [ ] Avatar animation starts and stops with the audio.
- [ ] Course-material upload accepts the administrator key.
- [ ] A question based on uploaded material shows the filename as a source.
- [ ] Start-new-chat resets the conversation.
- [ ] Export-chat downloads a transcript.

## Institutional readiness

- [ ] Add institutional name, logo and approved colours.
- [ ] Add privacy, consent and acceptable-use notices.
- [ ] Add authentication before collecting identifiable student data.
- [ ] Set student usage and cost limits.
- [ ] Define lecturer review and material-approval responsibility.
- [ ] Define escalation for inaccurate, unsafe or sensitive answers.
- [ ] Move from free resources to paid production services.
- [ ] Configure backups and monitoring.

## When Render says only one free database is allowed

- Use the default `render.yaml` in this fixed package.
- Copy the existing Render database's Internal Database URL.
- Enter it as `DATABASE_URL` during Blueprint deployment.
- Do not delete an existing database unless you have confirmed that no other app needs it.
