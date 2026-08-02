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


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
    assert data["visual_plan_enabled"] is True


def test_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["demo_mode"] is True
    assert data["visual_plan_enabled"] is True
    assert data["image_detail"] in {"low", "high", "original", "auto"}


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
    # One-pixel transparent PNG.
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
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
        files={"board_image": ("whiteboard.png", png, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["visual"] is not None


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


def test_index_contains_live_whiteboard():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="drawingCanvas"' in html
    assert 'id="attachBoard"' in html
    assert 'id="visualPreference"' in html


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
