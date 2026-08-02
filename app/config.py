from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Anovlad AI Tutor")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "gpt-5.6-luna")
    transcribe_model: str = os.getenv("TRANSCRIBE_MODEL", "gpt-transcribe")
    tts_model: str = os.getenv("TTS_MODEL", "tts-1")
    default_voice: str = os.getenv("DEFAULT_VOICE", "nova")
    admin_key: str = os.getenv("ADMIN_KEY", "change-this-admin-key")
    database_url: str = os.getenv("DATABASE_URL", "")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "data"))
    demo_mode: bool = _bool_env("DEMO_MODE", False)
    allow_general_knowledge: bool = _bool_env("ALLOW_GENERAL_KNOWLEDGE", True)
    max_image_mb: int = int(os.getenv("MAX_IMAGE_MB", "8"))
    max_audio_mb: int = int(os.getenv("MAX_AUDIO_MB", "20"))
    max_material_mb: int = int(os.getenv("MAX_MATERIAL_MB", "15"))
    history_turns: int = int(os.getenv("HISTORY_TURNS", "8"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key) and not self.demo_mode


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
