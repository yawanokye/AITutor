# v5.2 Paced Teaching and Practice Capture Fix

## Problem corrected

A handwritten practice response could be submitted as a very tall whiteboard image. When the image was reduced for vision analysis, the writing could become too small and the marker could return “No markable response received”. An inconsistent structured response could also set `correct=true` while awarding zero, causing an activity to finish at 0%.

## Handwriting changes

- Commits an in-progress final stroke before capture.
- Crops the exported image to the learner's actual ink bounds.
- Enlarges small handwriting and avoids sending unused white space.
- Rejects a genuinely blank capture before API submission.
- Sends stroke count, image dimensions and estimated ink coverage to the marker.
- Retries image marking once when verified writing is wrongly reported as blank.
- Awards partial credit for correct visible steps in unfinished answers.
- Derives `correct` from the score threshold, preventing zero-score completion.
- Preserves the best score for each question and displays partial activity credit.
- Redirects the general whiteboard check action to the practice board when handwritten practice is active.

## Teaching changes

- Narrates one logical section at a time.
- Highlights the exact sentence, equation, example, term or self-check being discussed.
- Completes all detailed explanation for the active visual section before advancing.
- Uses short natural pauses between ideas and longer pauses before learner checks.
- Adds Pause, Resume and Stop controls.

## Deployment

No database or environment-variable change is required. Clear the Render build cache, deploy, sign out, hard-refresh, and sign in again.
