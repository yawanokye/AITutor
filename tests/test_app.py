import os

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("ADMIN_KEY", "test-admin")
os.environ.setdefault("DATABASE_URL", "")

from fastapi.testclient import TestClient

from app.main import _audio_upload_extension, _base_media_type, _extract_response_text, app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["demo_mode"] is True


def test_demo_chat():
    response = client.post(
        "/api/chat",
        data={
            "message": "Explain photosynthesis.",
            "session_id": "test-session",
            "level": "Junior High School",
            "tutor_mode": "guided",
            "course": "Science",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["demo"] is True
    assert "demonstration mode" in data["answer"].lower()


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
