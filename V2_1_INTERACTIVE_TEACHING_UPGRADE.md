# AI Tutor v2.1 Interactive Teaching Upgrade

## Implemented features

### 1. Guided practice

The learner can choose a topic and request two to six questions. Each activity provides progressive difficulty, hints, structured marking, feedback, scoring and optional solution reveal. Answers may be typed or submitted from the whiteboard.

### 2. Whiteboard work checking

The current board is captured and analysed as learner work. The response includes a verdict, score, strengths, corrections, next step and optional positional annotations. This supports calculations, diagrams, graphs, labels and highlighted problem areas.

### 3. Synchronised visual narration

Visual steps can be taught sequentially. The current step is highlighted and its matching narration is spoken. Learners remain in control through the step navigation and stop controls.

### 4. Editable visual content

Graph and table values can be revised through a CSV editor. Diagram nodes can be repositioned by dragging. Updated visuals stay available for drawing, checking and follow-up questions.

### 5. Workspace recovery

The browser stores the latest conversation, visual plan, learner strokes and settings in local storage and restores them after a refresh on the same browser.

## New API routes

```text
POST /api/practice/start
POST /api/practice/check
POST /api/practice/reveal
POST /api/work/check
```

## Current persistence boundary

Course materials remain stored in PostgreSQL. Guided-practice runtime state is held in web-service memory, while workspace recovery is browser-local. A server restart can end an unfinished activity, and another device will not see the local workspace. Student accounts and database-backed progress are reserved for a later release.

## Deployment impact

No database migration is required. Replace the application files, confirm `IMAGE_DETAIL=high`, clear the Render build cache and deploy.
