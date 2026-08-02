# Audio recording compatibility fix, version 1.2

This release fixes microphone recordings rejected with:

`Unsupported audio format. Use WebM, WAV, MP3, MP4 or OGG.`

## Cause

Browsers commonly send a parameterised MIME type such as
`audio/webm;codecs=opus`. The earlier backend compared that complete string
against `audio/webm`, so a valid recording was rejected.

## Changes

- Removes MIME parameters before validating the upload.
- Supports WebM, WAV, MP3, MP4/M4A, OGG, AAC and FLAC MIME variants.
- Uses the browser-selected recording format instead of always naming the file
  `question.webm`.
- Gives the OpenAI transcription request a matching filename extension.
- Adds browser fallbacks for WebM, MP4/M4A and OGG recording.
- Adds cache-busting to the JavaScript and CSS URLs.
- Adds regression tests for parameterised WebM and MP4 MIME types.
