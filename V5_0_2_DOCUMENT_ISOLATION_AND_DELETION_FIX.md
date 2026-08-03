# AI Tutor v5.0.2 Document Isolation and Deletion Fix

Version 5.0.2 corrects document ownership, visibility and removal across the Administrator, Lecturer and Student portals.

## What changed

### Administrator repository

- The Administrator Portal now contains a private document repository.
- Administrators can upload, list and delete institution-level documents.
- Administrator documents are not displayed in any lecturer or student portal.
- Administrator documents are not automatically used to answer questions in lecturer-created courses.
- Existing administrator uploads from earlier versions remain visible to administrators so they can be removed.

### Lecturer course isolation

- A lecturer sees and manages documents only in courses owned by that lecturer.
- Course-material listing no longer adds institution-wide administrator documents.
- A lecturer cannot open or delete another lecturer's course documents.
- Re-uploading a document with the same filename and category removes the previous indexed extracts before replacement.

### Complete deletion

Deleting a lecturer document now removes:

1. The document record
2. Parsed sections and subsections
3. Indexed retrieval chunks used by the AI Tutor

This prevents deleted or replaced text from continuing to influence tutor responses.

### Student course visibility

- The Student Portal lists every course joined with a valid enrolment code.
- Courses from different lecturers appear together under **All enrolled courses**.
- The course selector also contains every enrolled course.

## Deployment

Upload the v5.0.2 patch to the root of the GitHub repository, replace existing files, commit to `main`, and in Render select **Manual Deploy → Clear build cache and deploy**.

No new environment variables or manual database migration are required.

After deployment, refresh the browser with `Ctrl + Shift + R`. The health endpoint should report version `5.0.2`.
