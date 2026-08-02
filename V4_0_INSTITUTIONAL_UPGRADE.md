# v4.0 Institutional Upgrade Summary

## Strategic change

Live one-to-one avatar video has been retired. It adds high per-student cost, bandwidth demand and concurrency pressure without being essential to the tutor's learning purpose.

The replacement is a scalable learning combination:

```text
Course-locked text tutoring
+ optional voice
+ image and handwriting analysis
+ interactive whiteboard
+ guided practice
+ teacher intelligence
+ reusable class lessons
```

## Implemented competitive advantages

### Course-locked tutoring

- Per-class knowledge mode
- Class-scoped official materials
- Approved-external source category
- Global institutional material option
- Clear source labels
- Detection and recording of questions that approved materials cannot answer

### Outcome-based teaching

- Teacher-defined learning outcomes
- Teacher-defined weekly topics
- Course-specific tutor instructions
- Outcome and topic carried through chat, practice and work checking
- Outcome mastery evidence in dashboards

### Step-level whiteboard assessment

- Ordered step assessment
- First-error detection
- Correct, warning, error and unreadable status
- Image-region annotations
- Corrective feedback and next action
- Recorded misconceptions and outcome evidence

### Teacher intelligence dashboard

- Weak topics
- Outcome mastery
- Common misconceptions
- Intervention candidates
- Popular questions
- Unanswered course-locked questions
- Student activity and scores
- AI model, token and estimated-cost reporting

### Low-bandwidth delivery

- Standard, low-data and text-only modes
- Lower output-token ceilings for low-data use
- No automatic speech in low-data mode
- Whiteboard hidden in text-only mode
- Offline application shell
- Local workspace recovery
- Downloadable HTML lesson packs
- Reusable class lesson scripts and slides

## Video model

- Student live video is disabled.
- Teachers generate one reusable lesson package for a class.
- Every package contains a script and slides.
- Optional Tavus MP4 generation remains available for shared lessons.
- Enrolled students access the same saved lesson instead of generating individual video sessions.

## Database changes

Startup migrations add:

- Class knowledge mode
- Learning outcomes
- Weekly topics
- Tutor instructions
- Knowledge-chunk class scope
- Knowledge material type
- Display source label

No second database is created.
