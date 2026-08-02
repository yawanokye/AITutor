import os

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("ADMIN_KEY", "test-admin")
os.environ.setdefault("DATABASE_URL", "")

from fastapi.testclient import TestClient

from app.main import app


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
