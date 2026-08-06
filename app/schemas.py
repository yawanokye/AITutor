from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    voice: str = Field(default="nova", min_length=2, max_length=32)
    style: Literal["default", "guided_lecture"] = "default"
    speed: float = Field(default=1.0, ge=0.75, le=1.15)


class VisualStep(BaseModel):
    title: str = Field(default="", max_length=120)
    explanation: str = Field(default="", max_length=1800)
    equation: str = Field(default="", max_length=500)
    narration: str = Field(default="", max_length=2200)
    learner_prompt: str = Field(default="", max_length=500)


class VisualPoint(BaseModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    label: str = Field(default="", max_length=80)


class VisualSeries(BaseModel):
    name: str = Field(default="Series", max_length=100)
    points: list[VisualPoint] = Field(default_factory=list, max_length=40)


class VisualAnnotation(BaseModel):
    label: str = Field(default="", max_length=140)
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    width: float = Field(ge=1, le=1000)
    height: float = Field(ge=1, le=1000)
    severity: Literal["info", "success", "warning", "error"] = "info"


class DiagramNode(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    label: str = Field(default="", max_length=140)
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    shape: Literal["box", "circle", "pill"] = "box"


class DiagramEdge(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    label: str = Field(default="", max_length=100)


class VisualSlide(BaseModel):
    title: str = Field(default="", max_length=180)
    bullets: list[str] = Field(default_factory=list, max_length=9)
    equation: str = Field(default="", max_length=700)
    explanation: str = Field(default="", max_length=1800)
    worked_example: str = Field(default="", max_length=1400)
    key_terms: list[str] = Field(default_factory=list, max_length=10)
    check_question: str = Field(default="", max_length=700)
    speaker_note: str = Field(default="", max_length=2200)

    @field_validator("bullets", "key_terms", mode="after")
    @classmethod
    def trim_bullets(cls, values: list[str]) -> list[str]:
        return [str(value)[:500] for value in values]


class VisualPlan(BaseModel):
    kind: Literal[
        "none",
        "steps",
        "graph",
        "table",
        "diagram",
        "image_annotation",
        "slides",
    ] = "none"
    title: str = Field(default="", max_length=160)
    caption: str = Field(default="", max_length=700)
    steps: list[VisualStep] = Field(default_factory=list, max_length=14)
    equations: list[str] = Field(default_factory=list, max_length=8)
    x_label: str = Field(default="x", max_length=80)
    y_label: str = Field(default="y", max_length=80)
    series: list[VisualSeries] = Field(default_factory=list, max_length=5)
    table_headers: list[str] = Field(default_factory=list, max_length=8)
    table_rows: list[list[str]] = Field(default_factory=list, max_length=12)
    nodes: list[DiagramNode] = Field(default_factory=list, max_length=12)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=20)
    annotations: list[VisualAnnotation] = Field(default_factory=list, max_length=8)
    slides: list[VisualSlide] = Field(default_factory=list, max_length=20)

    @field_validator("equations", "table_headers", mode="after")
    @classmethod
    def trim_text_lists(cls, values: list[str]) -> list[str]:
        return [str(value)[:500] for value in values]

    @field_validator("table_rows", mode="after")
    @classmethod
    def trim_table_rows(cls, rows: list[list[str]]) -> list[list[str]]:
        return [[str(value)[:300] for value in row[:8]] for row in rows[:12]]


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    session_id: str
    demo: bool = False
    visual: VisualPlan | None = None


class StepAssessment(BaseModel):
    step_number: int = Field(default=1, ge=1, le=20)
    label: str = Field(default="", max_length=180)
    status: Literal["correct", "partly_correct", "incorrect", "unclear"] = "unclear"
    feedback: str = Field(default="", max_length=700)
    correction: str = Field(default="", max_length=700)
    x: float | None = Field(default=None, ge=0, le=1000)
    y: float | None = Field(default=None, ge=0, le=1000)
    width: float | None = Field(default=None, ge=1, le=1000)
    height: float | None = Field(default=None, ge=1, le=1000)


class WorkCheck(BaseModel):
    verdict: Literal["correct", "partly_correct", "needs_revision", "unclear"] = "unclear"
    score: int = Field(default=0, ge=0, le=100)
    summary: str = Field(default="", max_length=700)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    corrections: list[str] = Field(default_factory=list, max_length=6)
    next_step: str = Field(default="", max_length=500)
    first_error_step: int | None = Field(default=None, ge=1, le=20)
    step_results: list[StepAssessment] = Field(default_factory=list, max_length=20)
    annotations: list[VisualAnnotation] = Field(default_factory=list, max_length=12)


class WorkCheckResponse(WorkCheck):
    visual: VisualPlan | None = None


class PracticeQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=1200)
    expected_answer: str = Field(min_length=1, max_length=1000)
    accepted_variants: list[str] = Field(default_factory=list, max_length=8)
    marking_guide: str = Field(default="", max_length=1000)
    hint: str = Field(default="", max_length=600)
    explanation: str = Field(default="", max_length=1200)
    difficulty: Literal["foundation", "standard", "challenge"] = "standard"
    response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    visual: VisualPlan | None = None


class PracticeActivity(BaseModel):
    title: str = Field(default="Practice activity", max_length=160)
    topic: str = Field(default="", max_length=200)
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=6)


class PracticeEvaluation(BaseModel):
    correct: bool = False
    score: int = Field(default=0, ge=0, le=100)
    feedback: str = Field(default="", max_length=800)
    misconception: str = Field(default="", max_length=500)
    next_hint: str = Field(default="", max_length=500)


class PracticeQuestionResponse(BaseModel):
    practice_id: str
    title: str
    topic: str
    question_id: str
    question_number: int
    question_count: int
    prompt: str
    difficulty: str
    visual: VisualPlan | None = None
    hint: str = ""
    score: int = 0
    completed: bool = False
    response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    allowed_response_modes: list[Literal["typed", "voice", "whiteboard"]] = Field(default_factory=lambda: ["typed", "voice", "whiteboard"])


class PracticeCheckResponse(BaseModel):
    correct: bool
    score_awarded: int
    total_score: int
    question_score: int = Field(default=0, ge=0, le=100)
    response_received: bool = True
    feedback: str
    hint: str = ""
    attempts: int
    completed: bool = False
    next_question: PracticeQuestionResponse | None = None


class PracticeRevealResponse(BaseModel):
    explanation: str
    expected_answer: str
    completed: bool = False
    next_question: PracticeQuestionResponse | None = None


class ConfigResponse(BaseModel):
    app_name: str
    openai_enabled: bool
    demo_mode: bool
    default_voice: str
    voices: list[str]
    max_image_mb: int
    max_audio_mb: int
    max_material_mb: int
    visual_plan_enabled: bool
    image_detail: str
    interactive_practice_enabled: bool = True
    work_check_enabled: bool = True
    text_ai_enabled: bool = False
    deepseek_enabled: bool = False
    text_provider: str = "openai"
    default_text_model: str = ""
    accounts_enabled: bool = True
    live_video_enabled: bool = False
    lesson_video_enabled: bool = False
    require_login_for_ai: bool = False
    institutional_mode: bool = True
    low_bandwidth_enabled: bool = True
    course_lock_enabled: bool = True


# v2.2 accounts and dashboards
class RegisterRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["student", "teacher"] = "student"
    teacher_invite_code: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        clean = value.strip().lower()
        if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return clean


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal["student", "teacher", "admin"]
    active: bool = True
    must_change_password: bool = False
    created_at: str = ""


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class ClassCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    subject: str = Field(default="", max_length=160)
    knowledge_mode: Literal["course_only", "course_plus_approved", "general"] = "course_only"
    learning_outcomes: list[str] = Field(default_factory=list, max_length=30)
    weekly_topics: list[str] = Field(default_factory=list, max_length=40)
    recommended_readings: list[str] = Field(default_factory=list, max_length=60)
    tutor_instructions: str = Field(default="", max_length=5000)
    practice_whiteboard_required: bool = False
    practice_response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    diagnostics_required: bool = True
    spaced_revision_enabled: bool = True
    mastery_pass_mark: int = Field(default=70, ge=40, le=95)
    direct_answers_allowed: bool = True
    hints_allowed: bool = True
    assignment_help_mode: Literal["teach_only", "guided", "allowed"] = "guided"
    integrity_mode: Literal["learning", "hint_only", "assessment_restricted"] = "learning"


class ClassProfileUpdateRequest(BaseModel):
    name: str = Field(default="", max_length=140)
    subject: str = Field(default="", max_length=160)
    knowledge_mode: Literal["course_only", "course_plus_approved", "general"] = "course_only"
    learning_outcomes: list[str] = Field(default_factory=list, max_length=30)
    weekly_topics: list[str] = Field(default_factory=list, max_length=40)
    recommended_readings: list[str] = Field(default_factory=list, max_length=60)
    tutor_instructions: str = Field(default="", max_length=5000)
    practice_whiteboard_required: bool = False
    practice_response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    diagnostics_required: bool = True
    spaced_revision_enabled: bool = True
    mastery_pass_mark: int = Field(default=70, ge=40, le=95)
    direct_answers_allowed: bool = True
    hints_allowed: bool = True
    assignment_help_mode: Literal["teach_only", "guided", "allowed"] = "guided"
    integrity_mode: Literal["learning", "hint_only", "assessment_restricted"] = "learning"


class ClassJoinRequest(BaseModel):
    join_code: str = Field(min_length=4, max_length=16)


class ClassPublic(BaseModel):
    id: str
    name: str
    subject: str = ""
    join_code: str = ""
    student_count: int = 0
    teacher_name: str = ""
    teacher_id: str = ""
    knowledge_mode: Literal["course_only", "course_plus_approved", "general"] = "course_only"
    learning_outcomes: list[str] = Field(default_factory=list)
    weekly_topics: list[str] = Field(default_factory=list)
    recommended_readings: list[str] = Field(default_factory=list)
    tutor_instructions: str = ""
    practice_whiteboard_required: bool = False
    practice_response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    diagnostics_required: bool = True
    spaced_revision_enabled: bool = True
    mastery_pass_mark: int = 70
    direct_answers_allowed: bool = True
    hints_allowed: bool = True
    assignment_help_mode: Literal["teach_only", "guided", "allowed"] = "guided"
    integrity_mode: Literal["learning", "hint_only", "assessment_restricted"] = "learning"
    created_at: str = ""


class DashboardResponse(BaseModel):
    role: str
    summary: dict = Field(default_factory=dict)
    classes: list[dict] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    weak_topics: list[dict] = Field(default_factory=list)
    students: list[dict] = Field(default_factory=list)
    lecturers: list[dict] = Field(default_factory=list)
    videos: list[dict] = Field(default_factory=list)
    usage: list[dict] = Field(default_factory=list)
    outcome_mastery: list[dict] = Field(default_factory=list)
    common_misconceptions: list[dict] = Field(default_factory=list)
    unanswered_questions: list[dict] = Field(default_factory=list)
    interventions: list[dict] = Field(default_factory=list)
    popular_questions: list[dict] = Field(default_factory=list)
    learning_paths: list[dict] = Field(default_factory=list)
    reviews_due: list[dict] = Field(default_factory=list)
    assessments: list[dict] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)
    milestones: dict = Field(default_factory=dict)
    next_recommended_action: dict = Field(default_factory=dict)
    mastery_records: list[dict] = Field(default_factory=list)
    revision_backlog: int = 0


class AssessmentQuestion(BaseModel):
    id: str = Field(default="", max_length=64)
    question_type: Literal["multiple_choice", "short_answer", "essay", "calculation", "case_study", "oral", "whiteboard", "upload"] = "short_answer"
    prompt: str = Field(min_length=2, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=12)
    expected_answer: str = Field(default="", max_length=5000)
    marking_guide: str = Field(default="", max_length=5000)
    hint: str = Field(default="", max_length=1600)
    explanation: str = Field(default="", max_length=3000)
    difficulty: Literal["foundation", "standard", "challenge"] = "standard"
    points: float = Field(default=1, ge=0.1, le=100)
    response_mode: Literal["typed", "voice", "whiteboard", "upload", "student_choice"] = "typed"
    learning_outcome: str = Field(default="", max_length=500)
    topic: str = Field(default="", max_length=300)


class AssessmentSettings(BaseModel):
    attempts_allowed: int = Field(default=1, ge=1, le=10)
    hints_allowed: bool = True
    reveal_answers: bool = True
    pass_mark: int = Field(default=70, ge=0, le=100)
    contributes_to_mastery: bool = True
    integrity_mode: Literal["learning", "hint_only", "graded", "exam"] = "learning"
    deadline_enforced: bool = False


class AssessmentCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    assessment_type: Literal["diagnostic", "practice", "quiz", "assignment", "mastery_check"] = "practice"
    topic: str = Field(default="", max_length=220)
    learning_outcome: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)
    questions: list[AssessmentQuestion] = Field(default_factory=list, max_length=40)
    settings: AssessmentSettings = Field(default_factory=AssessmentSettings)
    status: Literal["draft", "published", "closed"] = "draft"
    due_at: str = Field(default="", max_length=80)


class AssessmentDraftRequest(BaseModel):
    assessment_type: Literal["diagnostic", "practice", "quiz", "assignment", "mastery_check"] = "practice"
    topic: str = Field(default="", max_length=220)
    learning_outcome: str = Field(default="", max_length=500)
    question_count: int = Field(default=5, ge=2, le=20)
    difficulty: Literal["mixed", "foundation", "standard", "challenge"] = "mixed"


class AssessmentPublic(BaseModel):
    id: str
    class_id: str
    teacher_id: str = ""
    title: str
    assessment_type: str
    topic: str = ""
    learning_outcome: str = ""
    instructions: str = ""
    questions: list[dict] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    status: str = "draft"
    due_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class AssessmentStartResponse(BaseModel):
    attempt_id: str
    assessment: AssessmentPublic
    attempt_number: int = 1
    attempts_allowed: int = 1


class AssessmentSubmissionRequest(BaseModel):
    responses: list[dict] = Field(default_factory=list, max_length=40)
    hints_used: int = Field(default=0, ge=0, le=100)


class AssessmentQuestionFeedback(BaseModel):
    question_id: str = ""
    score: float = Field(default=0, ge=0, le=100)
    feedback: str = Field(default="", max_length=1600)
    misconception: str = Field(default="", max_length=1000)
    next_step: str = Field(default="", max_length=1000)


class AssessmentMarkingResult(BaseModel):
    overall_score: float = Field(default=0, ge=0, le=100)
    summary: str = Field(default="", max_length=2500)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    misconceptions: list[str] = Field(default_factory=list, max_length=10)
    question_feedback: list[AssessmentQuestionFeedback] = Field(default_factory=list, max_length=40)
    recommended_remediation: str = Field(default="", max_length=1800)


class AssessmentSubmissionResponse(BaseModel):
    attempt_id: str
    score: float
    passed: bool
    feedback: dict = Field(default_factory=dict)
    mastery: dict = Field(default_factory=dict)
    next_action: dict = Field(default_factory=dict)


class StudentNoteRequest(BaseModel):
    class_id: str = Field(default="", max_length=64)
    section_id: str = Field(default="", max_length=80)
    note_type: Literal["note", "bookmark", "worked_example", "revision_flag"] = "note"
    title: str = Field(default="", max_length=220)
    content: str = Field(default="", max_length=12000)
    metadata: dict = Field(default_factory=dict)


class RemediationRequest(BaseModel):
    class_id: str = Field(min_length=1, max_length=64)
    topic: str = Field(default="", max_length=300)
    learning_outcome: str = Field(default="", max_length=500)
    misconception: str = Field(min_length=2, max_length=1600)
    previous_answer: str = Field(default="", max_length=5000)


class RemediationResponse(BaseModel):
    title: str
    diagnosis: str
    prerequisite: str = ""
    explanation: str
    worked_example: str = ""
    retry_question: str
    sources: list[str] = Field(default_factory=list)
    visual: VisualPlan | None = None


class LiveVideoRequest(BaseModel):
    topic: str = Field(default="", max_length=300)
    course: str = Field(default="", max_length=160)
    level: str = Field(default="University", max_length=80)
    audio_only: bool = False


class LiveVideoResponse(BaseModel):
    conversation_id: str
    conversation_url: str
    status: str
    test_mode: bool = False


class LessonVideoRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    course: str = Field(default="", max_length=160)
    level: str = Field(default="University", max_length=80)
    length: Literal["short", "standard", "extended"] = "short"
    class_id: str = Field(default="", max_length=64)
    use_current_answer: bool = False
    current_answer: str = Field(default="", max_length=16000)


class LessonVideoPlan(BaseModel):
    title: str = Field(default="Lesson video", max_length=180)
    learning_objectives: list[str] = Field(default_factory=list, max_length=5)
    script: str = Field(min_length=20, max_length=7000)
    slides: list[VisualSlide] = Field(default_factory=list, max_length=20)
    estimated_minutes: float = Field(default=2.0, ge=0.5, le=12)


class LessonVideoResponse(BaseModel):
    id: str
    title: str
    status: str
    video_id: str = ""
    hosted_url: str = ""
    download_url: str = ""
    stream_url: str = ""
    script: str = ""
    estimated_minutes: float = 0
    provider: str = "lesson_package"


class VisionAnalysis(BaseModel):
    summary: str = Field(default="", max_length=1800)
    visible_text: list[str] = Field(default_factory=list, max_length=20)
    observations: list[str] = Field(default_factory=list, max_length=12)
    possible_errors: list[str] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=8)
    annotations: list[VisualAnnotation] = Field(default_factory=list, max_length=8)


# v5.0 administrator, course hierarchy and detailed section teaching
class AdminBootstrapRequest(BaseModel):
    admin_key: str = Field(min_length=4, max_length=256)
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_admin_email(cls, value: str) -> str:
        clean = value.strip().lower()
        if "@" not in clean:
            raise ValueError("Enter a valid email address.")
        return clean


class AdminCreateLecturerRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    temporary_password: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_lecturer_email(cls, value: str) -> str:
        clean = value.strip().lower()
        if "@" not in clean:
            raise ValueError("Enter a valid email address.")
        return clean


class AdminLecturerResponse(BaseModel):
    user: UserPublic
    temporary_password: str = ""


class AdminUserStatusRequest(BaseModel):
    active: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordResetResponse(BaseModel):
    temporary_password: str


class CourseDocumentPublic(BaseModel):
    id: str
    class_id: str
    title: str
    filename: str
    document_type: Literal["teaching_notes", "course_outline", "recommended_reading"]
    objectives: list[str] = Field(default_factory=list)
    recommended_readings: list[str] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    created_at: str = ""


class SectionTeachRequest(BaseModel):
    level: str = Field(default="University", max_length=80)
    detail: Literal["standard", "detailed", "extended"] = "detailed"
    include_worked_examples: bool = True
    include_self_check: bool = True


class LessonNoteBlock(BaseModel):
    heading: str = Field(default="", max_length=180)
    explanation: str = Field(default="", max_length=3000)
    example: str = Field(default="", max_length=1800)
    key_point: str = Field(default="", max_length=900)


class SectionLessonPlan(BaseModel):
    title: str = Field(default="Course section lesson", max_length=200)
    learning_objectives: list[str] = Field(default_factory=list, max_length=8)
    introduction: str = Field(default="", max_length=1800)
    detailed_notes: list[LessonNoteBlock] = Field(default_factory=list, max_length=20)
    key_terms: list[str] = Field(default_factory=list, max_length=16)
    summary: str = Field(default="", max_length=1800)
    self_check_questions: list[str] = Field(default_factory=list, max_length=8)
    slides: list[VisualSlide] = Field(default_factory=list, max_length=20)


class SectionTeachResponse(BaseModel):
    section_id: str
    section_title: str
    answer: str
    sources: list[str] = Field(default_factory=list)
    visual: VisualPlan | None = None
    practice_whiteboard_required: bool = False
    practice_response_mode: Literal["student_choice", "typed", "voice", "whiteboard"] = "student_choice"
    section_path: str = ""
    generated_from_outcomes: bool = False
