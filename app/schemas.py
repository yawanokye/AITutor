from __future__ import annotations

from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    voice: str = Field(default="nova", min_length=2, max_length=32)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    session_id: str
    demo: bool = False


class ConfigResponse(BaseModel):
    app_name: str
    openai_enabled: bool
    demo_mode: bool
    default_voice: str
    voices: list[str]
    max_image_mb: int
    max_audio_mb: int
    max_material_mb: int
