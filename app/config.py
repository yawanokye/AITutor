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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Anovlad AI Tutor")
    public_app_url: str = os.getenv("PUBLIC_APP_URL", "").rstrip("/")

    # Cost-aware text AI routing. DeepSeek V4 Flash is the default text tutor.
    ai_provider: str = os.getenv("AI_PROVIDER", "deepseek").strip().lower()
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_advanced_model: str = os.getenv("DEEPSEEK_ADVANCED_MODEL", "deepseek-v4-pro")
    deepseek_thinking: bool = _bool_env("DEEPSEEK_THINKING", False)
    deepseek_advanced_thinking: bool = _bool_env("DEEPSEEK_ADVANCED_THINKING", False)
    advanced_routing_enabled: bool = _bool_env("ADVANCED_ROUTING_ENABLED", True)
    advanced_routing_min_score: int = _int_env("ADVANCED_ROUTING_MIN_SCORE", 4)
    deepseek_max_tokens: int = _int_env("DEEPSEEK_MAX_TOKENS", 6000)

    # OpenAI is retained for image understanding, handwriting, STT, TTS and fallback.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "gpt-5.6-luna")
    vision_model: str = os.getenv("VISION_MODEL", os.getenv("AI_MODEL", "gpt-5.6-luna"))
    ai_reasoning_effort: str = os.getenv("AI_REASONING_EFFORT", "low")
    ai_verbosity: str = os.getenv("AI_VERBOSITY", "medium")
    max_output_tokens: int = _int_env("MAX_OUTPUT_TOKENS", 6000)
    visual_max_output_tokens: int = _int_env("VISUAL_MAX_OUTPUT_TOKENS", 3500)
    transcribe_model: str = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    tts_model: str = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
    default_voice: str = os.getenv("DEFAULT_VOICE", "nova")
    image_detail: str = os.getenv("IMAGE_DETAIL", "high").strip().lower()
    visual_plan_enabled: bool = _bool_env("VISUAL_PLAN_ENABLED", True)

    # Accounts and dashboard.
    auth_secret: str = os.getenv("AUTH_SECRET", os.getenv("ADMIN_KEY", "change-this-auth-secret"))
    access_token_minutes: int = _int_env("ACCESS_TOKEN_MINUTES", 1440)
    # Lecturer accounts are created by administrators in v5.0. The invitation code remains
    # only for backward compatibility and is not used by public registration.
    teacher_invite_code: str = os.getenv("TEACHER_INVITE_CODE", "")
    allow_public_teacher_registration: bool = _bool_env("ALLOW_PUBLIC_TEACHER_REGISTRATION", False)
    allow_student_registration: bool = _bool_env("ALLOW_STUDENT_REGISTRATION", True)
    admin_email: str = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    admin_display_name: str = os.getenv("ADMIN_DISPLAY_NAME", "System Administrator")
    require_login_for_ai: bool = _bool_env("REQUIRE_LOGIN_FOR_AI", False)
    student_monthly_ai_budget_usd: float = _float_env("STUDENT_MONTHLY_AI_BUDGET_USD", 1.0)
    admin_key: str = os.getenv("ADMIN_KEY", "change-this-admin-key")
    database_url: str = os.getenv("DATABASE_URL", "")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "data"))

    # Reusable lesson packages and optional generated MP4 videos. One-to-one live avatar video is retired.
    tavus_api_key: str = os.getenv("TAVUS_API_KEY", "")
    tavus_base_url: str = os.getenv("TAVUS_BASE_URL", "https://tavusapi.com").rstrip("/")
    tavus_video_replica_id: str = os.getenv("TAVUS_VIDEO_REPLICA_ID", "")
    tavus_video_fast: bool = _bool_env("TAVUS_VIDEO_FAST", False)
    lesson_video_enabled: bool = _bool_env("LESSON_VIDEO_ENABLED", True)
    max_video_script_chars: int = _int_env("MAX_VIDEO_SCRIPT_CHARS", 5000)
    student_video_monthly_limit: int = 0
    teacher_video_monthly_limit: int = _int_env("TEACHER_VIDEO_MONTHLY_LIMIT", 20)

    # Institutional teaching and low-bandwidth behaviour.
    institutional_mode: bool = _bool_env("INSTITUTIONAL_MODE", True)
    course_lock_enabled: bool = _bool_env("COURSE_LOCK_ENABLED", True)
    low_bandwidth_enabled: bool = _bool_env("LOW_BANDWIDTH_ENABLED", True)
    low_data_max_tokens: int = _int_env("LOW_DATA_MAX_TOKENS", 1800)
    text_only_max_tokens: int = _int_env("TEXT_ONLY_MAX_TOKENS", 1200)

    # App behaviour.
    demo_mode: bool = _bool_env("DEMO_MODE", False)
    allow_general_knowledge: bool = _bool_env("ALLOW_GENERAL_KNOWLEDGE", False)
    max_image_mb: int = _int_env("MAX_IMAGE_MB", 12)
    max_audio_mb: int = _int_env("MAX_AUDIO_MB", 20)
    max_material_mb: int = _int_env("MAX_MATERIAL_MB", 30)
    history_turns: int = _int_env("HISTORY_TURNS", 8)
    rate_limit_per_minute: int = _int_env("RATE_LIMIT_PER_MINUTE", 30)

    # Published DeepSeek prices are configurable so future price changes do not require code changes.
    deepseek_flash_input_per_million: float = _float_env("DEEPSEEK_FLASH_INPUT_PER_MILLION", 0.14)
    deepseek_flash_output_per_million: float = _float_env("DEEPSEEK_FLASH_OUTPUT_PER_MILLION", 0.28)
    deepseek_pro_input_per_million: float = _float_env("DEEPSEEK_PRO_INPUT_PER_MILLION", 0.435)
    deepseek_pro_output_per_million: float = _float_env("DEEPSEEK_PRO_OUTPUT_PER_MILLION", 0.87)

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key) and not self.demo_mode

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key) and not self.demo_mode

    @property
    def text_ai_enabled(self) -> bool:
        return self.deepseek_enabled or self.openai_enabled

    @property
    def tavus_video_ready(self) -> bool:
        return bool(self.tavus_api_key and self.tavus_video_replica_id and self.lesson_video_enabled) and not self.demo_mode


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
