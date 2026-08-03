import base64
import os
import tempfile
import uuid
from io import BytesIO

os.environ["DEMO_MODE"] = "true"
os.environ["ADMIN_KEY"] = "test-admin-bootstrap"
os.environ["AUTH_SECRET"] = "test-auth-secret-long-enough"
os.environ["DATABASE_URL"] = ""
os.environ["VISUAL_PLAN_ENABLED"] = "true"
os.environ["REQUIRE_LOGIN_FOR_AI"] = "false"
os.environ["RATE_LIMIT_PER_MINUTE"] = "500"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="ai-tutor-v5-tests-")
os.environ["ALLOW_PUBLIC_TEACHER_REGISTRATION"] = "false"

from docx import Document
from fastapi.testclient import TestClient

from app.main import (
    _audio_upload_extension,
    _base_media_type,
    _extract_response_text,
    _normalise_visual_plan,
    app,
)
from app.schemas import VisualPlan


client = TestClient(app)
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_ADMIN = None


def headers(auth):
    return {"Authorization": f"Bearer {auth['access_token']}"}


def unique_email(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def admin_account():
    global _ADMIN
    if _ADMIN:
        return _ADMIN
    response = client.post(
        "/api/admin/bootstrap",
        json={
            "admin_key": "test-admin-bootstrap",
            "display_name": "Test Administrator",
            "email": unique_email("admin"),
            "password": "AdminStrong123!",
        },
    )
    assert response.status_code == 200, response.text
    _ADMIN = response.json()
    return _ADMIN


def lecturer_account(name="Test Lecturer"):
    admin = admin_account()
    email = unique_email("lecturer")
    temporary = "LecturerTemp123!"
    created = client.post(
        "/api/admin/lecturers",
        headers=headers(admin),
        json={"display_name": name, "email": email, "temporary_password": temporary},
    )
    assert created.status_code == 200, created.text
    login = client.post("/api/auth/login", json={"email": email, "password": temporary})
    assert login.status_code == 200, login.text
    return login.json(), created.json()


def student_account(name="Test Student"):
    response = client.post(
        "/api/auth/register",
        json={
            "display_name": name,
            "email": unique_email("student"),
            "password": "StudentStrong123!",
            "role": "student",
            "teacher_invite_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_course(lecturer, *, name="Statistics 101", required=False):
    response = client.post(
        "/api/classes",
        headers=headers(lecturer),
        json={
            "name": name,
            "subject": "STA 101",
            "knowledge_mode": "course_only",
            "learning_outcomes": [],
            "weekly_topics": [],
            "recommended_readings": [],
            "tutor_instructions": "Use the uploaded lecturer notes as the main authority.",
            "practice_whiteboard_required": required,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def outline_docx_bytes():
    output = BytesIO()
    document = Document()
    document.add_heading("STA 101 Detailed Course Outline", 0)
    document.add_heading("Course Objectives", 1)
    document.add_paragraph("1. Explain descriptive statistics")
    document.add_paragraph("2. Distinguish qualitative and quantitative data")
    document.add_heading("Recommended Reading", 1)
    document.add_paragraph("1. Author, A. Introductory Statistics")
    document.add_heading("1. Introduction to Statistics", 1)
    document.add_paragraph("Statistics concerns the collection, organisation, analysis and interpretation of data.")
    document.add_heading("1.1 Types of Data", 2)
    document.add_paragraph("Qualitative data describe categories. Quantitative data are numerical.")
    document.save(output)
    return output.getvalue()


def upload_outline(lecturer, classroom):
    response = client.post(
        "/api/materials/upload",
        headers=headers(lecturer),
        data={"class_id": classroom["id"], "document_type": "course_outline"},
        files=[(
            "files",
            ("statistics-outline.docx", outline_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )],
    )
    assert response.status_code == 200, response.text
    return response.json()


def enrol(student, classroom):
    response = client.post(
        "/api/classes/join",
        headers=headers(student),
        json={"join_code": classroom["join_code"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_reports_v5_portal_build():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "5.0.0"
    assert data["live_video_enabled"] is False
    assert data["institutional_mode"] is True
    assert data["course_lock_enabled"] is True
    assert data["visual_plan_enabled"] is True


def test_config_exposes_interactive_features():
    data = client.get("/api/config").json()
    assert data["demo_mode"] is True
    assert data["visual_plan_enabled"] is True
    assert data["interactive_practice_enabled"] is True
    assert data["work_check_enabled"] is True
    assert data["institutional_mode"] is True
    assert data["live_video_enabled"] is False


def test_index_contains_v5_role_portals_and_two_whiteboards():
    html = client.get("/").text
    for identifier in (
        'id="drawingCanvas"', 'id="practiceDrawingCanvas"', 'id="courseNavigatorPanel"',
        'id="courseStructureList"', 'id="documentType"', 'id="showAdminSetup"',
        'id="openDashboard"', 'id="classSelect"', 'id="outcomeSelect"', 'id="weekSelect"',
    ):
        assert identifier in html
    assert '/static/portal.js?v=5.0.0' in html
    assert '/static/practice_board.js?v=5.0.0' in html
    assert 'Teacher invitation code' not in html
    assert 'openLiveVideo' not in html


def test_first_administrator_bootstrap_and_admin_dashboard():
    admin = admin_account()
    me = client.get("/api/auth/me", headers=headers(admin))
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    dashboard = client.get("/api/dashboard", headers=headers(admin))
    assert dashboard.status_code == 200
    assert dashboard.json()["role"] == "admin"
    assert "lecturers" in dashboard.json()


def test_second_administrator_bootstrap_is_blocked():
    admin_account()
    response = client.post(
        "/api/admin/bootstrap",
        json={
            "admin_key": "test-admin-bootstrap",
            "display_name": "Another Administrator",
            "email": unique_email("admin2"),
            "password": "AdminStrong123!",
        },
    )
    assert response.status_code == 409


def test_public_lecturer_registration_is_blocked():
    response = client.post(
        "/api/auth/register",
        json={
            "display_name": "Public Lecturer",
            "email": unique_email("public-lecturer"),
            "password": "StrongPass123!",
            "role": "teacher",
            "teacher_invite_code": "any-code",
        },
    )
    assert response.status_code == 403
    assert "administrator" in response.json()["detail"].lower()


def test_administrator_creates_lecturer_with_temporary_password():
    lecturer, created = lecturer_account("Dr Created Lecturer")
    assert lecturer["user"]["role"] == "teacher"
    assert created["temporary_password"]
    assert created["user"]["must_change_password"] is True
    listing = client.get("/api/admin/lecturers", headers=headers(admin_account()))
    assert listing.status_code == 200
    assert any(item["id"] == created["user"]["id"] for item in listing.json())


def test_lecturer_changes_temporary_password():
    lecturer, _ = lecturer_account()
    response = client.post(
        "/api/auth/change-password",
        headers=headers(lecturer),
        json={"current_password": "LecturerTemp123!", "new_password": "NewLecturerStrong123!"},
    )
    assert response.status_code == 200
    me = client.get("/api/auth/me", headers=headers(lecturer)).json()
    assert me["must_change_password"] is False


def test_lecturer_creates_course_and_regenerates_enrolment_code():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer)
    assert len(classroom["join_code"]) == 7
    changed = client.post(f"/api/classes/{classroom['id']}/regenerate-code", headers=headers(lecturer))
    assert changed.status_code == 200
    assert changed.json()["join_code"] != classroom["join_code"]


def test_student_registers_and_enrols_with_lecturer_code():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Course for enrolment")
    student = student_account()
    joined = enrol(student, classroom)
    assert joined["id"] == classroom["id"]
    classes = client.get("/api/classes", headers=headers(student)).json()
    assert any(item["id"] == classroom["id"] for item in classes)


def test_course_outline_extracts_objectives_readings_and_subsections():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Structured Course")
    uploaded = upload_outline(lecturer, classroom)
    item = uploaded["uploaded"][0]
    assert item["document_type"] == "course_outline"
    assert item["sections"] >= 4
    assert item["objectives_found"] == 2
    assert item["readings_found"] == 1
    refreshed = client.get("/api/classes", headers=headers(lecturer)).json()
    course = next(row for row in refreshed if row["id"] == classroom["id"])
    assert "Explain descriptive statistics" in course["learning_outcomes"]
    assert any("Introductory Statistics" in item for item in course["recommended_readings"])


def test_student_opens_course_structure_and_generates_grounded_section_lesson():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Section Lesson Course")
    upload_outline(lecturer, classroom)
    student = student_account()
    enrol(student, classroom)
    structure = client.get(f"/api/classes/{classroom['id']}/course-structure", headers=headers(student))
    assert structure.status_code == 200
    documents = structure.json()["documents"]
    sections = [section for document in documents for section in document["sections"]]
    target = next(section for section in sections if "Types of Data" in section["title"])
    lesson = client.post(
        f"/api/course/sections/{target['id']}/teach",
        headers=headers(student),
        json={"level": "University", "detail": "detailed", "include_worked_examples": True, "include_self_check": True},
    )
    assert lesson.status_code == 200, lesson.text
    data = lesson.json()
    assert "Types of Data" in data["section_title"]
    assert data["sources"]
    assert data["visual"]["kind"] == "slides"
    assert data["visual"]["slides"]
    first_slide = data["visual"]["slides"][0]
    assert "explanation" in first_slide
    assert "speaker_note" in first_slide


def test_documents_are_isolated_by_course():
    lecturer, _ = lecturer_account()
    first = create_course(lecturer, name="Class Alpha")
    second = create_course(lecturer, name="Class Beta")
    upload_outline(lecturer, first)
    first_docs = client.get(f"/api/classes/{first['id']}/course-structure", headers=headers(lecturer)).json()["documents"]
    second_docs = client.get(f"/api/classes/{second['id']}/course-structure", headers=headers(lecturer)).json()["documents"]
    assert first_docs
    assert second_docs == []


def test_lecturer_can_upload_teaching_notes_and_recommended_reading():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Multiple Documents")
    for document_type, filename, text in (
        ("teaching_notes", "notes.txt", b"# Unit 1\nDetailed lecturer teaching notes for this unit."),
        ("recommended_reading", "reading.txt", b"# Chapter 2\nApproved recommended reading extract."),
    ):
        response = client.post(
            "/api/materials/upload",
            headers=headers(lecturer),
            data={"class_id": classroom["id"], "document_type": document_type},
            files=[("files", (filename, text, "text/plain"))],
        )
        assert response.status_code == 200, response.text
    structure = client.get(f"/api/classes/{classroom['id']}/course-structure", headers=headers(lecturer)).json()
    types = {item["document_type"] for item in structure["documents"]}
    assert {"teaching_notes", "recommended_reading"}.issubset(types)


def test_required_practice_whiteboard_rejects_typed_only_answer():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Handwritten Practice", required=True)
    student = student_account()
    enrol(student, classroom)
    start = client.post(
        "/api/practice/start",
        headers=headers(student),
        data={"topic": "Mean", "level": "University", "course": "STA 101", "class_id": classroom["id"], "question_count": "2"},
    )
    assert start.status_code == 200
    response = client.post(
        "/api/practice/check",
        headers=headers(student),
        data={"practice_id": start.json()["practice_id"], "answer": "Typed answer only"},
    )
    assert response.status_code == 422
    assert "handwritten" in response.json()["detail"].lower()


def test_required_practice_whiteboard_accepts_image_response():
    lecturer, _ = lecturer_account()
    classroom = create_course(lecturer, name="Handwritten Practice Image", required=True)
    student = student_account()
    enrol(student, classroom)
    start = client.post(
        "/api/practice/start",
        headers=headers(student),
        data={"topic": "Fractions", "level": "Junior High School", "course": "Mathematics", "class_id": classroom["id"], "question_count": "2"},
    ).json()
    response = client.post(
        "/api/practice/check",
        headers=headers(student),
        data={"practice_id": start["practice_id"], "answer": ""},
        files={"board_image": ("practice.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert response.status_code == 200


def test_demo_chat_returns_visual_plan():
    response = client.post(
        "/api/chat",
        data={
            "message": "Explain photosynthesis.", "session_id": "test-session", "level": "Junior High School",
            "tutor_mode": "guided", "course": "Science", "visual_requested": "true", "visual_preference": "steps",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["demo"] is True
    assert data["visual"]["kind"] == "steps"


def test_demo_work_check_returns_step_level_feedback():
    response = client.post(
        "/api/work/check",
        data={"problem_context": "Solve 2x + 4 = 10", "board_context": '{"ink_strokes":3}', "level": "Junior High School", "course": "Mathematics"},
        files={"board_image": ("working.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert 0 <= data["score"] <= 100
    assert "step_results" in data
    assert "first_error_step" in data


def test_visual_slide_schema_keeps_detailed_teaching_fields():
    plan = VisualPlan(
        kind="slides",
        slides=[{
            "title": "Mean", "bullets": ["Definition"], "explanation": "A detailed explanation.",
            "worked_example": "Add the values and divide by their number.", "key_terms": ["sum", "count"],
            "check_question": "What is the mean of 2 and 4?", "speaker_note": "Explain each stage slowly.",
        }],
    )
    slide = plan.slides[0]
    assert slide.explanation
    assert slide.worked_example
    assert slide.check_question


def test_visual_normalisation_clamps_image_boxes():
    plan = VisualPlan(kind="image_annotation", title="Check", annotations=[{"label":"Area","x":990,"y":995,"width":200,"height":100}])
    box = _normalise_visual_plan(plan, has_image=True).annotations[0]
    assert box.x + box.width <= 1000
    assert box.y + box.height <= 1000


def test_image_annotation_becomes_none_without_image():
    plan = VisualPlan(kind="image_annotation", annotations=[{"label":"Area","x":10,"y":10,"width":100,"height":100}])
    assert _normalise_visual_plan(plan, has_image=False).kind == "none"


def test_material_upload_without_course_still_requires_admin_key():
    response = client.post(
        "/api/materials/upload",
        data={"admin_key": "wrong"},
        files={"files": ("notes.txt", b"A simple course note.", "text/plain")},
    )
    assert response.status_code == 401


def test_extract_response_text_from_message_items():
    class Part:
        type = "output_text"
        text = "Visible answer"
    class Item:
        type = "message"
        content = [Part()]
    class FakeResponse:
        output_text = ""
        output = [Item()]
    assert _extract_response_text(FakeResponse()) == "Visible answer"


def test_audio_mime_variants_are_accepted():
    assert _base_media_type("audio/webm;codecs=opus") == "audio/webm"
    assert _audio_upload_extension("question.webm", "audio/webm;codecs=opus") == ".webm"
    assert _audio_upload_extension("question.bin", "audio/mp4;codecs=mp4a.40.2") == ".m4a"
    assert _audio_upload_extension("question.webm", "application/octet-stream") == ".webm"


def test_service_worker_and_manifest_are_v5():
    manifest = client.get("/static/manifest.webmanifest")
    worker = client.get("/static/service-worker.js")
    assert manifest.status_code == 200
    assert worker.status_code == 200
    assert "Anovlad Institutional AI Tutor" in manifest.text
    assert "anovlad-ai-tutor-v5-shell" in worker.text


def test_cost_aware_router_prefers_flash_for_normal_and_pro_for_advanced():
    from app.main import ai_router
    normal_model, _ = ai_router.choose_deepseek_model("Explain photosynthesis simply.")
    advanced_model, _ = ai_router.choose_deepseek_model("Derive an advanced stochastic differential equation and prove the theorem using eigenvalues.")
    assert normal_model == "deepseek-v4-flash"
    assert advanced_model == "deepseek-v4-pro"
