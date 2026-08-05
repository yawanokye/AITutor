# v5.1.1 Course-Outline Table Fix

## Problem corrected

Some Word course outlines do not use Word Heading styles for weekly content. Instead, the semester plan is stored in a table with columns such as:

```text
Period | Topics | Student’s Preparation
```

The earlier parser recognised `Week` but not `Period`. It also normalised all whitespace inside a table cell, which destroyed the paragraph boundaries separating the main topic from its subtopics. The student therefore saw only generic entries such as **Complete document** and **4.0 Course Outline**.

## New parsing behaviour

The parser now:

- recognises Week, Period, Session and Teaching Week columns;
- recognises number words such as One, Two and Ten;
- preserves individual Word paragraphs inside topic cells;
- treats the first topic-cell paragraph as the weekly topic;
- creates every later paragraph as a selectable subtopic;
- displays Student’s Preparation as weekly activities;
- reads the course code and title from the course-information table;
- extracts both course objectives and course outcomes;
- ignores decorative logo tables;
- gives useful names to course-information and policy tables.

## Existing uploads

Raw Word files were not stored by earlier releases. Existing outlines cannot be accurately rebuilt from the collapsed database text. After deploying v5.1.1, the lecturer must re-upload each affected course outline once. The same filename replaces the previous structure and removes stale indexed extracts.

The lecturer portal now identifies older outlines and displays a re-upload warning. The student portal also displays a clear restructuring notice instead of silently presenting an incomplete outline.

## Validation

The parser was tested against a six-page Operations Management course outline containing ten periods, numerous subtopics and weekly preparation activities. It extracted:

- course title: `SBU301: Operations Management`;
- 10 weekly topics;
- 11 objectives and outcomes;
- 96 structured sections;
- 8 subtopics under Week 1;
- all Week 1 reading and preparation activities.

The release passes 38 automated tests, Python compilation and JavaScript syntax checks.
