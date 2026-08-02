import base64
import os

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("ADMIN_KEY", "test-admin")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("VISUAL_PLAN_ENABLED", "true")

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


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "4.0.0"
    assert data["live_video_enabled"] is False
    assert data["institutional_mode"] is True
    assert data["course_lock_enabled"] is True
    assert data["low_bandwidth_enabled"] is True
    assert data["visual_plan_enabled"] is True


def test_config_exposes_interactive_features():
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["demo_mode"] is True
    assert data["visual_plan_enabled"] is True
    assert data["interactive_practice_enabled"] is True
    assert data["work_check_enabled"] is True
    assert data["image_detail"] in {"low", "high", "auto"}
    assert data["institutional_mode"] is True
    assert data["course_lock_enabled"] is True
    assert data["low_bandwidth_enabled"] is True
    assert data["live_video_enabled"] is False


def test_demo_chat_returns_visual_plan():
    response = client.post(
        "/api/chat",
        data={
            "message": "Explain photosynthesis.",
            "session_id": "test-session",
            "level": "Junior High School",
            "tutor_mode": "guided",
            "course": "Science",
            "visual_requested": "true",
            "visual_preference": "steps",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["demo"] is True
    assert "demonstration mode" in data["answer"].lower()
    assert data["visual"]["kind"] == "steps"
    assert len(data["visual"]["steps"]) >= 1


def test_demo_chat_can_accept_whiteboard_snapshot():
    response = client.post(
        "/api/chat",
        data={
            "message": "Explain the part I marked.",
            "session_id": "board-session",
            "level": "University",
            "tutor_mode": "guided",
            "course": "Mathematics",
            "board_context": '{"visible_page": 1, "learner_ink_strokes": 2}',
            "visual_requested": "true",
        },
        files={"board_image": ("whiteboard.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["visual"] is not None


def test_demo_practice_flow():
    start = client.post(
        "/api/practice/start",
        data={
            "topic": "One-way ANOVA",
            "level": "University",
            "course": "Statistics",
            "question_count": "3",
        },
    )
    assert start.status_code == 200
    question = start.json()
    assert question["practice_id"]
    assert question["question_number"] == 1
    assert question["hint"]

    check = client.post(
        "/api/practice/check",
        data={
            "practice_id": question["practice_id"],
            "answer": "It explains the main purpose and central idea of one-way ANOVA.",
        },
    )
    assert check.status_code == 200
    result = check.json()
    assert "correct" in result
    assert "feedback" in result
    assert result["attempts"] == 1


def test_demo_practice_reveal_advances():
    start = client.post(
        "/api/practice/start",
        data={"topic": "Fractions", "level": "Junior High School", "question_count": "2"},
    ).json()
    response = client.post(
        "/api/practice/reveal",
        data={"practice_id": start["practice_id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["expected_answer"]
    assert data["explanation"]


def test_demo_work_check_returns_score_and_visual():
    response = client.post(
        "/api/work/check",
        data={
            "problem_context": "Solve 2x + 4 = 10",
            "board_context": '{"ink_strokes": 3}',
            "level": "Junior High School",
            "course": "Mathematics",
        },
        files={"board_image": ("working.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert 0 <= data["score"] <= 100
    assert data["visual"] is not None
    assert data["next_step"]
    assert "step_results" in data
    assert "first_error_step" in data


def test_visual_normalisation_clamps_image_boxes():
    plan = VisualPlan(
        kind="image_annotation",
        title="Check this line",
        annotations=[
            {"label": "Marked area", "x": 990, "y": 995, "width": 200, "height": 100}
        ],
    )
    normalised = _normalise_visual_plan(plan, has_image=True)
    assert normalised is not None
    box = normalised.annotations[0]
    assert box.x + box.width <= 1000
    assert box.y + box.height <= 1000


def test_image_annotation_becomes_none_without_image():
    plan = VisualPlan(
        kind="image_annotation",
        annotations=[{"label": "Area", "x": 10, "y": 10, "width": 100, "height": 100}],
    )
    normalised = _normalise_visual_plan(plan, has_image=False)
    assert normalised is not None
    assert normalised.kind == "none"


def test_index_contains_v40_institutional_controls():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="drawingCanvas"' in html
    assert 'id="attachBoard"' in html
    assert 'id="visualPreference"' in html
    assert 'id="startPractice"' in html
    assert 'id="checkWork"' in html
    assert 'id="teachVisual"' in html
    assert '/static/v2_1.js?v=4.0.0' in html
    assert '/static/portal.js?v=4.0.0' in html
    assert 'id="openDashboard"' in html
    assert 'id="openLiveVideo"' not in html
    assert 'id="openLessonVideo"' in html
    assert 'id="classSelect"' in html
    assert 'id="outcomeSelect"' in html
    assert 'id="weekSelect"' in html
    assert 'id="deliveryMode"' in html
    assert 'id="downloadLessonPack"' in html
    assert '/static/manifest.webmanifest' in html


def test_material_upload_requires_admin_key():
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


def test_parameterised_webm_mime_is_accepted():
    assert _base_media_type("audio/webm;codecs=opus") == "audio/webm"
    assert _audio_upload_extension("question.webm", "audio/webm;codecs=opus") == ".webm"


def test_mp4_recorder_gets_matching_extension():
    assert _audio_upload_extension("question.bin", "audio/mp4;codecs=mp4a.40.2") == ".m4a"


def test_generic_mime_uses_known_filename_extension():
    assert _audio_upload_extension("question.webm", "application/octet-stream") == ".webm"



def _register(role="student"):
    import uuid
    email = f"{role}-{uuid.uuid4().hex[:10]}@example.com"
    payload = {
        "display_name": f"Test {role.title()}",
        "email": email,
        "password": "StrongPass123!",
        "role": role,
        "teacher_invite_code": "test-admin" if role == "teacher" else "",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_student_account_login_and_dashboard():
    registration = _register("student")
    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "student"
    dashboard = client.get("/api/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["role"] == "student"


def test_teacher_creates_class_and_student_joins():
    teacher = _register("teacher")
    student = _register("student")
    teacher_headers = {"Authorization": f"Bearer {teacher['access_token']}"}
    student_headers = {"Authorization": f"Bearer {student['access_token']}"}
    created = client.post("/api/classes", headers=teacher_headers, json={"name": "Statistics 101", "subject": "Statistics"})
    assert created.status_code == 200, created.text
    join_code = created.json()["join_code"]
    joined = client.post("/api/classes/join", headers=student_headers, json={"join_code": join_code})
    assert joined.status_code == 200, joined.text
    assert joined.json()["name"] == "Statistics 101"
    teacher_dashboard = client.get("/api/dashboard", headers=teacher_headers)
    assert teacher_dashboard.status_code == 200
    assert teacher_dashboard.json()["summary"]["students"] >= 1


def test_video_endpoints_require_sign_in():
    response = client.post("/api/video/conversation", json={"topic": "Fractions"})
    assert response.status_code == 401
    response = client.post("/api/video/generate", json={"topic": "Fractions"})
    assert response.status_code == 401


def test_live_avatar_video_is_retired_for_signed_in_users():
    student = _register("student")
    headers = {"Authorization": f"Bearer {student['access_token']}"}
    response = client.post("/api/video/conversation", headers=headers, json={"topic": "Fractions"})
    assert response.status_code == 410
    assert "retired" in response.json()["detail"].lower()



def test_teacher_can_define_course_lock_outcomes_and_weekly_topics():
    teacher = _register("teacher")
    headers = {"Authorization": f"Bearer {teacher['access_token']}"}
    created = client.post(
        "/api/classes",
        headers=headers,
        json={
            "name": "Research Methods A",
            "subject": "Research Methods",
            "knowledge_mode": "course_only",
            "learning_outcomes": ["Explain sampling", "Select an appropriate design"],
            "weekly_topics": ["Week 1: Research foundations", "Week 2: Sampling"],
            "tutor_instructions": "Use examples from the approved module and do not complete graded assignments.",
        },
    )
    assert created.status_code == 200, created.text
    classroom = created.json()
    assert classroom["knowledge_mode"] == "course_only"
    assert len(classroom["learning_outcomes"]) == 2

    updated = client.patch(
        f"/api/classes/{classroom['id']}/profile",
        headers=headers,
        json={
            "name": "Research Methods A",
            "subject": "Research Methods",
            "knowledge_mode": "course_plus_approved",
            "learning_outcomes": ["Explain sampling", "Evaluate research designs"],
            "weekly_topics": ["Week 1: Foundations", "Week 2: Sampling"],
            "tutor_instructions": "Use the approved course module first and identify the learning outcome addressed.",
        },
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["knowledge_mode"] == "course_plus_approved"
    assert "Evaluate research designs" in data["learning_outcomes"]


def test_teacher_materials_are_scoped_to_the_selected_class():
    teacher = _register("teacher")
    headers = {"Authorization": f"Bearer {teacher['access_token']}"}
    first = client.post("/api/classes", headers=headers, json={"name": "Class Alpha", "subject": "Mathematics"}).json()
    second = client.post("/api/classes", headers=headers, json={"name": "Class Beta", "subject": "Science"}).json()

    upload_a = client.post(
        "/api/materials/upload",
        headers=headers,
        data={"class_id": first["id"], "material_type": "course"},
        files=[("files", ("alpha-notes.txt", b"Alpha-specific quadratic equation guidance and examples.", "text/plain"))],
    )
    assert upload_a.status_code == 200, upload_a.text
    upload_b = client.post(
        "/api/materials/upload",
        headers=headers,
        data={"class_id": second["id"], "material_type": "approved_external"},
        files=[("files", ("beta-reading.txt", b"Beta-specific laboratory safety guidance.", "text/plain"))],
    )
    assert upload_b.status_code == 200, upload_b.text

    alpha_list = client.get(f"/api/materials?class_id={first['id']}", headers=headers)
    assert alpha_list.status_code == 200
    alpha_names = {item["source"] for item in alpha_list.json()["materials"]}
    assert "alpha-notes.txt" in alpha_names
    assert "beta-reading.txt" not in alpha_names


def test_student_dashboard_exposes_institutional_intelligence_fields():
    registration = _register("student")
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    for key in (
        "outcome_mastery", "common_misconceptions", "unanswered_questions",
        "interventions", "popular_questions"
    ):
        assert key in data


def test_service_worker_and_manifest_are_available():
    manifest = client.get("/static/manifest.webmanifest")
    worker = client.get("/static/service-worker.js")
    assert manifest.status_code == 200
    assert worker.status_code == 200
    assert "Anovlad Institutional AI Tutor" in manifest.text
    assert "anovlad-ai-tutor-v4-shell" in worker.text

def test_cost_aware_router_prefers_flash_for_normal_and_pro_for_advanced():
    from app.main import ai_router
    normal_model, _ = ai_router.choose_deepseek_model("Explain photosynthesis simply.")
    advanced_model, _ = ai_router.choose_deepseek_model("Derive an advanced stochastic differential equation and prove the theorem using eigenvalues.")
    assert normal_model == "deepseek-v4-flash"
    assert advanced_model == "deepseek-v4-pro"
