# AI Tutor v5.5, lesson continuity and course chat memory

## Problems corrected

Earlier lesson follow-up buttons stopped the guided presentation and sent the learner back through the ordinary chat flow. That replaced the visual plan and could cause a Week 2 question to be interpreted from Week 1 conversation history. The presentation could also expose internal phrases about slides being linked to detailed notes, while key-idea cards sometimes retained week labels and numbering.

## New lesson-interruption flow

When a learner asks a question during teaching:

1. The active lecture audio pauses.
2. The current slide, slide number, narration time and revealed teaching cues remain unchanged.
3. A focused popup opens with the learner's exact request.
4. The request is sent with the active course, week, section path, section title, slide title, detailed explanation, equation and example.
5. Conflicting references from earlier weeks are ignored.
6. The answer appears and can be read aloud in the popup.
7. When the clarification ends, the popup closes and the original lecture resumes from the same audio position.

The follow-up response does not generate or replace the visual presentation.

## Course-specific chat memory

Each course now keeps its own:

- Session identifier
- Conversation history
- Latest answer
- Active lesson context
- Visual plan and current slide
- Whiteboard ink
- Selected outcome and weekly topic

Switching courses saves the current workspace and restores the selected course's own workspace. Persistent chat history is reloaded from PostgreSQL after a service restart when the learner's browser still has the course session identifier.

The student Learning memory tab can:

- View memory status for enrolled courses
- Clear the current course conversation
- Clear all course conversations

These controls do not remove course enrolment, assessments, grades, mastery records, revision schedules, private notes or bookmarks.

## Student-facing presentation cleanup

The server and browser both remove:

- Statements that the presentation or slides are linked or aligned to detailed notes
- Instructions telling learners to return to detailed notes
- Pure week, period, session, slide or section labels from key ideas
- Leading list numbers from key-idea and key-term cards

The visible card label is now simply **Key idea**, not Key idea 1, Key idea 2 and so on. The slide header uses **Current topic** rather than an internal section counter.

## Deployment

No new environment variables or manual database migration are required.

1. Back up the existing Render PostgreSQL database.
2. Upload the patch contents to the root of the GitHub repository.
3. Commit to `main`.
4. In Render, select **Manual Deploy**, then **Clear build cache and deploy**.
5. Open `/health` and confirm version `5.5.0`.
6. Sign out, hard-refresh the browser and sign in again so the v5.5 service-worker cache replaces the earlier interface.

## Validation

The release passes 59 automated tests, Python compilation, JavaScript syntax checks and Render YAML validation.
