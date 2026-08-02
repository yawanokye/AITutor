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
    assert data["version"] == "2.1.0"
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


def test_index_contains_v21_interactive_controls():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="drawingCanvas"' in html
    assert 'id="attachBoard"' in html
    assert 'id="visualPreference"' in html
    assert 'id="startPractice"' in html
    assert 'id="checkWork"' in html
    assert 'id="teachVisual"' in html
    assert '/static/v2_1.js?v=2.1.0' in html


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
