# AI Tutor v5.3 Guided Lecture Presentation

## Purpose

The earlier teaching mode generated and played many short audio clips, one sentence at a time. That caused repeated voice restarts, equal pauses and an artificial rhythm. It also displayed all slide content at once, even when the tutor had not reached that part of the explanation.

## New teaching flow

1. The selected lesson section opens with the detailed notes visible.
2. The tutor builds a connected lecture script from the slide title, organising ideas, detailed explanation, lecturer note, equation, worked example, key terms and check question.
3. One continuous audio file is generated for the section whenever it fits within the speech limit. Very long sections use only a small number of connected chunks.
4. The app estimates the position of each teaching beat from the actual audio duration and the relative length of each part.
5. The current note sentence is highlighted while the related visual cue appears on the slide.
6. The next section opens only after the current detailed explanation is complete.

## Natural pacing

The speech request now identifies guided teaching separately from ordinary read-aloud. It requests a warm, conversational university-lecturer delivery, natural variation in pace and emphasis, brief pauses after definitions and before examples, and slower delivery for technical terms and equations. The guided lecture uses a speech speed of 0.94.

## Interface changes

- Detailed teaching notes form the main reading panel.
- A separate visual stage displays progressive concept cards, equations, examples, key terms and understanding checks.
- Future note sentences are subdued. The active sentence is highlighted and previously covered sentences remain readable.
- The visual stage is scrollable on long lessons and stacks below the notes on smaller screens.
- The action is now labelled **Teach like a lecturer**.

## Deployment

Upload the v5.3 patch to the repository root, replace existing files, deploy with a cleared Render build cache, and hard-refresh the browser. No environment-variable or database change is required.
