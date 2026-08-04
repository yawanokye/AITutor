# v5.1 Student Learning Workspace Upgrade

## Purpose

This release simplifies the student portal and turns practice and course-outline teaching into complete multimodal learning workflows.

## Student interface

Students see only course enrolments, course content, tutoring, practice, progress, voice, images and whiteboards. Provider configuration, lecturer uploads and administrator tools are hidden. The **My courses** portal continues to show every enrolled course across different lecturers.

## Lecturer-controlled practice responses

Each course has a `practice_response_mode`:

- `student_choice`
- `typed`
- `voice`
- `whiteboard`

The practice API returns the required and allowed modes for every question. The browser enforces the selected mode before submission, and the backend independently validates it. Voice recordings are uploaded to OpenAI transcription, while handwriting is submitted as a whiteboard image.

## Expandable practice whiteboard

The separate practice board starts at 900 pixels high, grows in 650-pixel blocks to a maximum of 5,000 pixels and uses a vertically scrollable writing shell. It supports pen, eraser, colour, undo, clear and full-screen mode. The teaching whiteboard also supports full-screen mode with a browser fallback.

## Week-by-week course-outline teaching

Course outlines are parsed from Word headings and structured tables. Tables containing Week, Topic and Activities columns produce week entries and selectable subunits. Where the lecturer has supplied weekly topics or outcomes without an uploaded document, the app creates virtual weekly lesson entries.

## Teaching without uploaded readings

When teaching notes and recommended readings are absent, the AI Tutor is authorised to develop instructional notes from the lecturer's objectives, expected outcomes, weekly plan and tutor instructions. The output identifies this as an instructional expansion and does not pretend that generated text was quoted from a lecturer or source.

## Detailed human-style teaching

The lesson prompt requires prerequisite explanation, definitions, importance, logical subtopics, misconceptions, complete worked examples, applications and self-checks. Broad topics may be subdivided beyond the literal outline where the subdivisions are needed for complete understanding.

Whiteboard slides use the same depth as the written notes. Detailed explanations and speaker notes are displayed directly rather than hidden behind a collapsed control.

## Compatibility

Existing courses and `practice_whiteboard_required` remain supported. A legacy whiteboard requirement is converted to `practice_response_mode=whiteboard`. No manual database migration is required.
