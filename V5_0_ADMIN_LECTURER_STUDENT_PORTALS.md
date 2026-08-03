# v5.0 Upgrade: Administrator, Lecturer and Student Portals

## Purpose

Version 5.0 converts the AI Tutor from a shared tutoring interface into a managed institutional learning platform. It establishes role separation, lecturer-managed enrolment, structured course navigation and grounded subsection teaching.

## 1. Administrator portal

The administrator is now responsible for lecturer identity management. Public lecturer self-registration is disabled by default.

Implemented functions:

- One-time first-administrator setup
- Optional administrator provisioning from Render
- Lecturer account creation
- Generated temporary passwords
- Mandatory temporary-password change
- Lecturer activation and deactivation
- Lecturer password reset
- Institutional dashboard metrics

This prevents an enrolment or invitation code from being used to create an unauthorised lecturer account.

## 2. Lecturer portal and enrolment codes

A lecturer creates a course and receives a unique enrolment code. The code can be copied or regenerated. Students use it only after creating a student account.

Each course stores:

- Name and subject
- Knowledge mode
- Learning objectives
- Weekly topics
- Recommended readings
- Lecturer tutor instructions
- Whether handwritten practice is compulsory

## 3. Structured teaching documents

Lecturers can upload:

- Teaching notes
- Detailed course outlines
- Recommended readings

The parser creates a persistent document and section hierarchy. DOCX heading styles provide the best hierarchy. The course outline parser also detects objectives and reading lists and can merge them into the course profile.

## 4. Section-driven AI tutoring

Students enter the Student portal, open an enrolled course and browse the detected hierarchy. Selecting a subsection sends that subsection, related approved material and the course profile to the AI Tutor.

The response includes:

- A detailed written lesson
- Learning objectives
- Key ideas and definitions
- Detailed teaching-note blocks
- Worked examples
- Common misconceptions
- Self-check questions
- A detailed slide deck
- Source labels from approved course documents

## 5. Separate practice whiteboard

The existing whiteboard remains responsible for AI-generated visual explanations. Version 5.0 adds an independent practice-response board for student handwriting.

When a lecturer requires handwritten practice:

- The practice board opens automatically
- The student writes using mouse, finger or stylus
- Typed-only submission is blocked
- The board is submitted as an image for marking
- The AI identifies the first incorrect step and provides guidance

## 6. Detailed slide teaching

Slides are no longer short bullet summaries only. Each slide can include:

- Detailed explanation
- Worked example
- Key terms
- Equation
- Check question
- Expanded teaching note for narration

The generated deck can contain up to 14 slides and is grounded in the selected subsection and approved reading material.

## 7. Database changes

The application adds or upgrades persistent structures for:

- User account status
- Temporary-password enforcement
- Course recommended readings
- Handwritten-practice requirements
- Course documents
- Document hierarchy
- Section text and metadata

Migrations are applied during startup. A database backup is still required before production deployment.

## 8. Security defaults

Recommended production settings:

```text
ALLOW_PUBLIC_TEACHER_REGISTRATION=false
ALLOW_STUDENT_REGISTRATION=true
REQUIRE_LOGIN_FOR_AI=true
COURSE_LOCK_ENABLED=true
LIVE_VIDEO_ENABLED=false
```

General knowledge can remain globally available while each lecturer chooses whether an individual course may use it.
