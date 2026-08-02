# Empty response fix

This release fixes cases where GPT-5.6 Luna spends the configured output budget on reasoning before a visible tutor message is emitted.

Changes:

- Raises the default output budget from 1,400 to 6,000 tokens.
- Sets reasoning effort to `low` for normal tutor requests.
- Explicitly requests medium text verbosity.
- Extracts text safely from all message output items.
- Retries once with `reasoning.effort=none` and an 8,000-token budget when the first response has no visible text.
- Adds safe diagnostics to Render logs without logging prompts, API keys, or student content.
- Uses `gpt-4o-mini-transcribe` as the transcription default.

After uploading the replacement files to GitHub, redeploy the Render service with **Clear build cache & deploy**.
