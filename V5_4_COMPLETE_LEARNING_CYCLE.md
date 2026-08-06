# AI Tutor v5.4 Complete Learning Cycle

Version 5.4 turns the course tutor into a connected learning cycle:

**Diagnose → Teach → Practise → Mark → Diagnose the error → Remediate → Reassess → Schedule revision → Record mastery → Recommend the next action.**

## Student learning experience

- Entry diagnostics are created automatically for courses that require them, with question-level mapping to course outcomes and weekly topics.
- Each enrolled course receives a personalised pathway based on its objectives, weekly topics, diagnostic results, mastery evidence and review schedule.
- The Student Portal opens with one recommended next action instead of an undifferentiated set of tools.
- Mastery is recorded as Not started, Needs foundation, Developing, Competent or Mastered.
- Weak outcomes open a remedial mini-lesson that diagnoses the misconception, rebuilds the prerequisite, gives a fresh example and ends with a retry question.
- Spaced-revision items are scheduled from assessed performance and shown in Due for review.
- Students can save private notes, bookmark the latest explanation, open a printable revision sheet and download the sheet as DOCX.
- Weekly activity goals, learning streaks and mastery milestones support motivation without awarding progress merely for time spent.
- A printable course-mastery certificate becomes available only after the diagnostic and every configured outcome are mastered.
- Accessibility controls provide larger text, high contrast and a reading-friendly layout. Existing Standard, Low data and Text only modes remain available.

## Assessment and practice

Lecturers can generate an AI draft question bank, then edit every prompt, response method, expected answer, marking guide, hint, explanation, difficulty and point value before publishing.

Assessment controls include:

- Diagnostic, practice, quiz, assignment and mastery-check types
- Attempts allowed
- Hints allowed
- Answer reveal after submission
- Pass mark
- Deadline enforcement
- Contribution to mastery
- Learning, hint-only, graded and examination integrity modes
- Typed, oral, handwritten-image and uploaded-file responses

Oral responses are transcribed. Handwritten images and uploaded documents are converted into markable text. The existing guided-practice workspace continues to support typing, voice and the full-screen scrolling whiteboard.

## Lecturer intelligence

The Lecturer Portal now combines:

- Outcome mastery
- Weak topics
- Common misconceptions
- Students with low scores
- Students with very limited or no activity
- Students inactive for 14 days
- Questions that lack approved course grounding
- Spaced-revision backlog
- Recommended lecturer action for each intervention case

## Academic integrity

Each course can control:

- Whether direct answers are allowed
- Whether hints are allowed
- Whether assignment help is concept teaching only, guided after an attempt, or fully allowed
- Whether the course is in normal learning, hint-only or assessment-restricted mode

These controls are inserted into the tutor’s governing instructions for every course-locked conversation.

## Lesson interaction and source transparency

Students can interrupt a lesson with:

- Explain more simply
- Another example
- Show the working
- Why is this important?
- Test me now
- Repeat explanation

The guided lecture stops before the follow-up begins. Course retrieval labels answer sources as Course material or Approved reading. AI-generated lessons based only on course objectives remain identified as generated from lecturer objectives and outcomes.

## Database upgrade

The app creates these tables automatically in the existing PostgreSQL database:

- `ai_tutor_course_policies`
- `ai_tutor_assessments`
- `ai_tutor_assessment_attempts`
- `ai_tutor_mastery_records`
- `ai_tutor_revision_items`
- `ai_tutor_student_notes`

Back up the database before deployment. No manual SQL script or new environment variable is required.

## Validation

The release is validated through Python compilation, JavaScript syntax checks, YAML parsing and 54 automated tests covering diagnostics, pathways, mastery, revision, assessment editing, deadlines, private notes, response extraction, intervention detection, course policies and existing portal behaviour.
