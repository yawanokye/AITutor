from __future__ import annotations

import base64
import io
import json
import html
import logging
import re
import secrets
import string
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from starlette.concurrency import run_in_threadpool

from app.accounts import AccountStore, AuthError, AuthManager
from app.config import settings
from app.knowledge import KnowledgeStore, extract_text, make_chunks
from app.course_content import CourseContentStore, DOCUMENT_TYPES
from app.prompts import (
    lesson_video_instructions,
    section_lesson_instructions,
    practice_generation_instructions,
    practice_marking_instructions,
    tutor_instructions,
    visual_plan_instructions,
    work_check_instructions,
)
from app.schemas import (
    AdminBootstrapRequest,
    AdminCreateLecturerRequest,
    AdminLecturerResponse,
    AdminUserStatusRequest,
    AuthResponse,
    ClassCreateRequest,
    ClassProfileUpdateRequest,
    ClassJoinRequest,
    ClassPublic,
    DashboardResponse,
    LessonVideoPlan,
    LessonVideoRequest,
    LessonVideoResponse,
    LiveVideoRequest,
    LiveVideoResponse,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetResponse,
    RegisterRequest,
    SectionLessonPlan,
    SectionTeachRequest,
    SectionTeachResponse,
    UserPublic,
    VisionAnalysis,
    ChatResponse,
    ConfigResponse,
    PracticeActivity,
    PracticeCheckResponse,
    PracticeEvaluation,
    PracticeQuestionResponse,
    PracticeRevealResponse,
    SpeechRequest,
    VisualPlan,
    WorkCheck,
    WorkCheckResponse,
)

from app.providers import AIProviderRouter, ProviderError
from app.tavus import TavusError, TavusService

logger = logging.getLogger("ai_tutor")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=settings.app_name, version="5.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def prevent_stale_portal_assets(request: Request, call_next):
    """Prevent old portal/API responses from surviving a deployment upgrade."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/api/") or path == "/health":
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif path.startswith("/static/") and path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return response

knowledge = KnowledgeStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
accounts = AccountStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
course_content = CourseContentStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
auth = AuthManager(secret=settings.auth_secret, access_token_minutes=settings.access_token_minutes)

# Optional first administrator provisioned entirely through Render Environment.
if settings.admin_email and settings.admin_password and not accounts.get_user_by_email(settings.admin_email):
    try:
        accounts.create_user(
            email=settings.admin_email,
            password_hash=auth.hash_password(settings.admin_password),
            display_name=settings.admin_display_name,
            role="admin",
            active=True,
            must_change_password=False,
        )
    except Exception:
        logger.exception("The configured administrator account could not be provisioned")
ai_router = AIProviderRouter(settings)
tavus = TavusService(settings)
client = ai_router.openai_client

# Session history is intentionally short and contains no passwords or API keys.
# For production at scale, replace this with Redis or a database-backed session store.
sessions: dict[str, deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=max(settings.history_turns * 2, 4))
)
rate_buckets: dict[str, deque[float]] = defaultdict(deque)
practice_sessions: dict[str, dict[str, Any]] = {}

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
SUPPORTED_AUDIO_MIME_TO_EXTENSION = {
    "audio/webm": ".webm",
    "video/webm": ".webm",  # Some browsers label audio-only WebM this way.
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/vnd.wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}
SUPPORTED_AUDIO_EXTENSIONS = {
    ".webm", ".wav", ".mp3", ".mp4", ".m4a", ".mpeg", ".mpga", ".ogg", ".aac", ".flac"
}
VOICE_OPTIONS = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"]
VISUAL_PREFERENCES = {"auto", "steps", "graph", "table", "diagram", "slides"}


def _check_rate_limit(request: Request) -> None:
    if settings.rate_limit_per_minute <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = rate_buckets[ip]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Too many requests. Please pause briefly and try again.")
    bucket.append(now)


def _require_openai():
    if settings.demo_mode:
        raise HTTPException(status_code=503, detail="This feature is disabled in demo mode.")
    if client is None:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY has not been configured on the server.")
    return client


def _require_text_ai() -> AIProviderRouter:
    if settings.demo_mode:
        raise HTTPException(status_code=503, detail="This feature is disabled in demo mode.")
    if not ai_router.text_enabled:
        raise HTTPException(status_code=503, detail="Configure DEEPSEEK_API_KEY or OPENAI_API_KEY for text tutoring.")
    return ai_router


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "").strip()
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def _optional_user(request: Request) -> dict[str, Any] | None:
    token = _bearer_token(request)
    if not token:
        return None
    try:
        payload = auth.decode_token(token)
    except AuthError:
        return None
    return accounts.get_user(str(payload.get("sub", "")))


def _required_user(request: Request) -> dict[str, Any]:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to use this feature.")
    try:
        payload = auth.decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = accounts.get_user(str(payload.get("sub", "")))
    if not user:
        raise HTTPException(status_code=401, detail="Account not found.")
    if not bool(user.get("active", True)):
        raise HTTPException(status_code=403, detail="This account has been deactivated. Contact the administrator.")
    return user


def _required_teacher(request: Request) -> dict[str, Any]:
    user = _required_user(request)
    if user.get("role") not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="A lecturer account is required.")
    return user


def _required_lecturer(request: Request) -> dict[str, Any]:
    user = _required_user(request)
    if user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="A lecturer account is required.")
    return user


def _required_admin(request: Request) -> dict[str, Any]:
    user = _required_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="An administrator account is required.")
    return user


def _ai_user(request: Request) -> dict[str, Any] | None:
    user = _optional_user(request)
    if settings.require_login_for_ai and not user:
        user = _required_user(request)
    if user and user.get("role") == "student" and settings.student_monthly_ai_budget_usd > 0:
        cost = accounts.monthly_usage_cost(str(user["id"]))
        if cost >= settings.student_monthly_ai_budget_usd:
            raise HTTPException(status_code=429, detail="Your monthly AI allowance has been reached. Ask your teacher or administrator to review the limit.")
    return user


def _record_usage(user: dict[str, Any] | None, result: Any, task: str) -> None:
    try:
        accounts.record_usage(
            user_id=str(user["id"]) if user else None,
            provider=str(getattr(result, "provider", "")),
            model=str(getattr(result, "model", "")),
            task=task,
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            estimated_cost_usd=float(getattr(result, "estimated_cost_usd", 0) or 0),
        )
    except Exception:
        logger.exception("Usage recording failed")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip()
    return cleaned[:180] or "material"


def _temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(max(12, length)))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value


def _base_media_type(content_type: str | None) -> str:
    """Return a lowercase MIME type without parameters such as codecs."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def _audio_upload_extension(filename: str | None, content_type: str | None) -> str | None:
    """Resolve a safe extension from a parameterised MIME type or file name."""
    base_type = _base_media_type(content_type)
    mime_extension = SUPPORTED_AUDIO_MIME_TO_EXTENSION.get(base_type)
    if mime_extension:
        return mime_extension

    filename_extension = Path(filename or "").suffix.lower()
    if filename_extension in SUPPORTED_AUDIO_EXTENSIONS:
        return filename_extension

    if base_type in {"", "application/octet-stream"} and filename_extension:
        return filename_extension if filename_extension in SUPPORTED_AUDIO_EXTENSIONS else None
    return None


def _image_detail() -> str:
    # The Responses API accepts low, high or auto. Keep backward compatibility with
    # the earlier IMAGE_DETAIL=original setting by mapping it to high.
    value = settings.image_detail.strip().lower()
    if value == "original":
        return "high"
    return value if value in {"low", "high", "auto"} else "auto"


def _course_context(
    query: str, *, class_id: str = "", knowledge_mode: str = "general"
) -> tuple[str, list[str]]:
    allowed_types = {"course"}
    if knowledge_mode in {"course_plus_approved", "general"}:
        allowed_types.add("approved_external")
    results = knowledge.retrieve(
        query,
        limit=6,
        class_id=class_id,
        allowed_types=allowed_types,
        include_global=False,
    )
    if not results:
        return "No approved course-material extract was retrieved for this question.", []

    sections = []
    sources: list[str] = []
    for index, result in enumerate(results, start=1):
        label = "COURSE" if result.material_type == "course" else "APPROVED EXTERNAL"
        sections.append(f"{label} EXTRACT {index} [Source: {result.source}]\n{result.content}")
        if result.source not in sources:
            sources.append(result.source)
    return "\n\n".join(sections), sources


def _learning_context(
    *, user: dict[str, Any] | None, class_id: str, course: str,
    learning_outcome: str, weekly_topic: str
) -> dict[str, Any]:
    classroom: dict[str, Any] | None = None
    if class_id:
        if not user:
            raise HTTPException(status_code=401, detail="Sign in to use a class-locked course.")
        classroom = accounts.class_for_user(
            class_id=class_id, user_id=str(user["id"]), role=str(user.get("role", "student"))
        )
        if not classroom:
            raise HTTPException(status_code=403, detail="You do not have access to this class.")
    knowledge_mode = str((classroom or {}).get("knowledge_mode") or ("course_only" if settings.course_lock_enabled and class_id else "general"))
    effective_course = str((classroom or {}).get("subject") or (classroom or {}).get("name") or course).strip()[:160]
    outcomes = [str(item) for item in (classroom or {}).get("learning_outcomes", [])]
    weeks = [str(item) for item in (classroom or {}).get("weekly_topics", [])]
    selected_outcome = learning_outcome.strip()[:300]
    selected_week = weekly_topic.strip()[:300]
    if outcomes and selected_outcome not in outcomes:
        selected_outcome = outcomes[0]
    if weeks and selected_week not in weeks:
        selected_week = weeks[0]
    return {
        "classroom": classroom,
        "class_id": class_id if classroom else "",
        "course": effective_course,
        "knowledge_mode": knowledge_mode,
        "learning_outcome": selected_outcome,
        "weekly_topic": selected_week,
        "tutor_instructions": str((classroom or {}).get("tutor_instructions") or ""),
    }


def _response_input(
    *,
    history: deque[dict[str, Any]],
    message: str,
    context: str,
    images: list[dict[str, str]],
    board_context: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for turn in history:
        items.append({"role": turn["role"], "content": turn["content"]})

    board_section = ""
    if board_context.strip():
        board_section = (
            "\n\nCURRENT WHITEBOARD CONTEXT\n"
            f"{board_context.strip()[:12000]}\n"
            "The context describes the visual already on screen. Learner ink may also appear in a supplied whiteboard image."
        )

    user_text = (
        f"APPROVED COURSE CONTEXT\n{context}\n\n"
        f"LEARNER QUESTION\n{message.strip()}"
        f"{board_section}"
    )

    if images:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": user_text}]
        for index, image in enumerate(images, start=1):
            content.append(
                {
                    "type": "input_text",
                    "text": f"IMAGE {index}: {image['label']}",
                }
            )
            content.append(
                {
                    "type": "input_image",
                    "image_url": image["data_url"],
                    "detail": _image_detail(),
                }
            )
        items.append({"role": "user", "content": content})
    else:
        items.append({"role": "user", "content": user_text})
    return items


def _extract_response_text(ai_response: Any) -> str:
    """Extract visible text safely from a Responses API object."""
    direct = getattr(ai_response, "output_text", "") or ""
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    for item in getattr(ai_response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            content_type = getattr(content, "type", None)
            if content_type == "output_text":
                text = getattr(content, "text", "") or ""
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            elif content_type == "refusal":
                refusal = getattr(content, "refusal", "") or ""
                if isinstance(refusal, str) and refusal.strip():
                    parts.append(refusal.strip())
    return "\n\n".join(parts).strip()


def _response_diagnostic(ai_response: Any) -> dict[str, Any]:
    incomplete = getattr(ai_response, "incomplete_details", None)
    return {
        "status": getattr(ai_response, "status", None),
        "incomplete_reason": getattr(incomplete, "reason", None) if incomplete else None,
        "output_types": [getattr(item, "type", None) for item in (getattr(ai_response, "output", []) or [])],
    }


def _demo_answer(message: str, has_image: bool, sources: list[str]) -> str:
    image_note = " I can see that you attached an image, but image analysis needs the API key to be enabled." if has_image else ""
    source_note = f" I found material from {', '.join(sources)}." if sources else " No course material has been uploaded yet."
    return (
        "This app is running in demonstration mode."
        f"{image_note}{source_note}\n\n"
        f"Your question was: **{message.strip()}**\n\n"
        "Add `OPENAI_API_KEY` in Render and set `DEMO_MODE=false` to receive full tutoring responses."
    )


def _demo_visual(message: str, has_image: bool) -> VisualPlan:
    title = "How the visual tutor will help"
    if has_image:
        return VisualPlan(
            kind="steps",
            title=title,
            caption="In live mode, the tutor analyses the uploaded image and can place precise labels over relevant regions.",
            steps=[
                {"title": "Inspect", "explanation": "Identify the visible task, values, labels and learner working.", "equation": ""},
                {"title": "Diagnose", "explanation": "Locate the first unclear or incorrect step and explain why it matters.", "equation": ""},
                {"title": "Guide", "explanation": "Show the corrected method and let the learner check the next step.", "equation": ""},
            ],
        )
    return VisualPlan(
        kind="steps",
        title=title,
        caption="The live system converts the answer into a visual sequence that can be presented and annotated.",
        steps=[
            {"title": "Understand", "explanation": f"Identify what the question is asking: {message[:120]}", "equation": ""},
            {"title": "Work", "explanation": "Display the method as clear steps, equations, a graph, table, diagram or slides.", "equation": ""},
            {"title": "Check", "explanation": "Verify the result and use the whiteboard for learner annotations.", "equation": ""},
        ],
    )


def _normalise_visual_plan(plan: VisualPlan | None, *, has_image: bool) -> VisualPlan | None:
    if plan is None:
        return None
    data = plan.model_dump()

    # Clamp and clean image boxes so they always remain on the normalised board.
    cleaned_annotations: list[dict[str, Any]] = []
    for annotation in data.get("annotations", [])[:8]:
        x = max(0.0, min(float(annotation["x"]), 999.0))
        y = max(0.0, min(float(annotation["y"]), 999.0))
        width = max(1.0, min(float(annotation["width"]), 1000.0 - x))
        height = max(1.0, min(float(annotation["height"]), 1000.0 - y))
        cleaned_annotations.append({**annotation, "x": x, "y": y, "width": width, "height": height})
    data["annotations"] = cleaned_annotations

    # Keep line charts predictable and remove edges that point to missing nodes.
    for series in data.get("series", []):
        series["points"] = sorted(series.get("points", [])[:30], key=lambda point: point.get("x", 0))
    node_ids = {node.get("id") for node in data.get("nodes", [])}
    data["edges"] = [
        edge for edge in data.get("edges", [])[:16]
        if edge.get("source") in node_ids and edge.get("target") in node_ids
    ]

    headers = data.get("table_headers", [])[:8]
    data["table_headers"] = headers
    if headers:
        width = len(headers)
        rows: list[list[str]] = []
        for row in data.get("table_rows", [])[:12]:
            fitted = list(row[:width])
            fitted.extend([""] * (width - len(fitted)))
            rows.append(fitted)
        data["table_rows"] = rows

    kind = data.get("kind", "none")
    valid = {
        "steps": bool(data.get("steps") or data.get("equations")),
        "graph": any(series.get("points") for series in data.get("series", [])),
        "table": bool(data.get("table_headers") and data.get("table_rows")),
        "diagram": bool(data.get("nodes")),
        "image_annotation": bool(has_image and data.get("annotations")),
        "slides": bool(data.get("slides")),
        "none": True,
    }
    if not valid.get(kind, False):
        data["kind"] = "none"
        data["caption"] = data.get("caption") or "No additional visual was needed for this answer."
    return VisualPlan.model_validate(data)


def _create_visual_plan(
    *,
    question: str,
    answer: str,
    level: str,
    course: str,
    preference: str,
    has_image: bool,
    vision_analysis: VisionAnalysis | None,
    user: dict[str, Any] | None,
) -> VisualPlan | None:
    vision_section = ""
    if vision_analysis is not None:
        vision_section = f"\n\nIMAGE ANALYSIS\n{ai_router.vision_context(vision_analysis)}"
    prompt_text = (
        f"LEARNER LEVEL\n{level[:80]}\n\n"
        f"COURSE\n{course[:160] or 'Not specified'}\n\n"
        f"LEARNER QUESTION\n{question[:8000]}\n\n"
        f"TUTOR ANSWER\n{answer[:16000]}"
        f"{vision_section}"
    )
    result = ai_router.generate_structured(
        schema=VisualPlan,
        instructions=visual_plan_instructions(has_image=has_image, preference=preference),
        prompt=prompt_text,
        task="visual_plan",
        max_tokens=settings.visual_max_output_tokens,
        prefer_deepseek=True,
    )
    _record_usage(user, result, "visual_plan")
    plan = result.value if isinstance(result.value, VisualPlan) else VisualPlan.model_validate(result.value)
    if vision_analysis is not None:
        plan = ai_router.inject_image_annotations(plan, vision_analysis.annotations, has_image)
    return _normalise_visual_plan(plan, has_image=has_image)


def _plain_text_for_speech(text: str) -> str:
    clean = re.sub(r"```.*?```", " Code example omitted from speech. ", text, flags=re.DOTALL)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[Source:[^\]]+\]", "", clean)
    clean = re.sub(r"[#>*_~]", "", clean)
    clean = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:4000]


async def _read_image(upload: UploadFile | None, *, label: str) -> dict[str, str] | None:
    if upload is None or not upload.filename:
        return None
    content_type = _base_media_type(upload.content_type)
    if content_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Use a JPG, PNG, WEBP or GIF image.")
    image_bytes = await upload.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="The attached image is empty.")
    if len(image_bytes) > settings.max_image_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Images must be no larger than {settings.max_image_mb} MB.")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {"label": label, "data_url": f"data:{content_type};base64,{encoded}"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled application error: %s", type(exc).__name__, exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"detail": f"The request could not be completed: {type(exc).__name__}"})


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": app.version,
        "text_ai_enabled": settings.text_ai_enabled,
        "deepseek_enabled": settings.deepseek_enabled,
        "openai_enabled": settings.openai_enabled,
        "text_provider": "deepseek" if settings.deepseek_enabled and settings.ai_provider == "deepseek" else "openai",
        "default_text_model": settings.deepseek_model if settings.deepseek_enabled and settings.ai_provider == "deepseek" else settings.ai_model,
        "vision_model": settings.vision_model,
        "knowledge_sources": len(knowledge.list_sources()),
        "visual_plan_enabled": settings.visual_plan_enabled,
        "image_detail": _image_detail(),
        "accounts_enabled": True,
        "live_video_enabled": False,
        "lesson_video_enabled": settings.lesson_video_enabled and settings.text_ai_enabled,
        "require_login_for_ai": settings.require_login_for_ai,
        "institutional_mode": settings.institutional_mode,
        "course_lock_enabled": settings.course_lock_enabled,
        "low_bandwidth_enabled": settings.low_bandwidth_enabled,
        "administrator_portal_enabled": True,
        "lecturer_managed_enrolment": True,
        "structured_course_content_enabled": True,
        "separate_practice_whiteboard_enabled": True,
        "detailed_slide_teaching_enabled": True,
        "student_focused_interface_enabled": True,
        "multimodal_practice_responses_enabled": True,
        "scrolling_fullscreen_whiteboards_enabled": True,
        "weekly_course_plan_enabled": True,
        "period_table_outline_parser_enabled": True,
        "cropped_practice_whiteboard_capture_enabled": True,
        "partial_practice_credit_enabled": True,
        "paced_section_teaching_enabled": True,
        "guided_lecture_notes_enabled": True,
        "synchronised_slide_popups_enabled": True,
        "natural_lecture_pacing_enabled": True,
    }


@app.get("/api/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    return ConfigResponse(
        app_name=settings.app_name,
        openai_enabled=settings.openai_enabled,
        demo_mode=settings.demo_mode,
        default_voice=settings.default_voice,
        voices=VOICE_OPTIONS,
        max_image_mb=settings.max_image_mb,
        max_audio_mb=settings.max_audio_mb,
        max_material_mb=settings.max_material_mb,
        visual_plan_enabled=settings.visual_plan_enabled,
        image_detail=_image_detail(),
        interactive_practice_enabled=True,
        work_check_enabled=True,
        text_ai_enabled=settings.text_ai_enabled,
        deepseek_enabled=settings.deepseek_enabled,
        text_provider="deepseek" if settings.deepseek_enabled and settings.ai_provider == "deepseek" else "openai",
        default_text_model=settings.deepseek_model if settings.deepseek_enabled and settings.ai_provider == "deepseek" else settings.ai_model,
        accounts_enabled=True,
        live_video_enabled=False,
        lesson_video_enabled=settings.lesson_video_enabled and settings.text_ai_enabled,
        require_login_for_ai=settings.require_login_for_ai,
        institutional_mode=settings.institutional_mode,
        course_lock_enabled=settings.course_lock_enabled,
        low_bandwidth_enabled=settings.low_bandwidth_enabled,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(default=""),
    level: str = Form(default="University"),
    tutor_mode: str = Form(default="guided"),
    course: str = Form(default=""),
    class_id: str = Form(default=""),
    learning_outcome: str = Form(default=""),
    weekly_topic: str = Form(default=""),
    delivery_mode: str = Form(default="standard"),
    visual_requested: bool = Form(default=True),
    visual_preference: str = Form(default="auto"),
    board_context: str = Form(default=""),
    image: UploadFile | None = File(default=None),
    board_image: UploadFile | None = File(default=None),
) -> ChatResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    delivery_mode = delivery_mode if delivery_mode in {"standard", "low_data", "text_only"} else "standard"
    learning = _learning_context(
        user=user,
        class_id=class_id.strip(),
        course=course,
        learning_outcome=learning_outcome,
        weekly_topic=weekly_topic,
    )
    course = str(learning["course"])
    if delivery_mode == "text_only":
        visual_requested = False
    message = message.strip()
    if not message and image is None and board_image is None:
        raise HTTPException(status_code=422, detail="Enter a question, attach an image, or attach the whiteboard.")
    if len(message) > 8000:
        raise HTTPException(status_code=413, detail="The question is too long. Keep it below 8,000 characters.")
    if len(board_context) > 16000:
        raise HTTPException(status_code=413, detail="The whiteboard context is too large.")

    visual_preference = visual_preference if visual_preference in VISUAL_PREFERENCES else "auto"
    session_id = session_id.strip() or str(uuid.uuid4())
    history = sessions[session_id]

    learner_image = await _read_image(image, label="Learner-uploaded image or photograph")
    whiteboard_image = await _read_image(board_image, label="Current digital whiteboard snapshot with learner annotations")
    images = [item for item in (learner_image, whiteboard_image) if item]
    effective_message = message or (
        "Please explain the part I marked on the whiteboard."
        if whiteboard_image
        else "Please analyse and explain the attached image."
    )
    retrieval_query = " ".join(
        part for part in [course, str(learning["learning_outcome"]), str(learning["weekly_topic"]), effective_message] if part
    ).strip()
    context, sources = await run_in_threadpool(
        _course_context,
        retrieval_query,
        class_id=str(learning["class_id"]),
        knowledge_mode=str(learning["knowledge_mode"]),
    )
    insufficient_context = str(learning["knowledge_mode"]) != "general" and not sources

    visual: VisualPlan | None = None
    provider_name = "demo"
    model_name = ""
    vision_analysis: VisionAnalysis | None = None
    if settings.demo_mode:
        answer = _demo_answer(effective_message, bool(images), sources)
        if settings.visual_plan_enabled and visual_requested:
            visual = _demo_visual(effective_message, bool(images))
    else:
        _require_text_ai()
        if images:
            try:
                vision_result = await run_in_threadpool(
                    ai_router.analyse_images,
                    images=images,
                    question=effective_message,
                    level=level,
                    course=course,
                )
                vision_analysis = vision_result.value if isinstance(vision_result.value, VisionAnalysis) else VisionAnalysis.model_validate(vision_result.value)
                _record_usage(user, vision_result, "image_analysis")
            except ProviderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("Image analysis failed")
                raise HTTPException(status_code=502, detail=f"Image-analysis error: {type(exc).__name__}") from exc

        instructions = tutor_instructions(
            app_name=settings.app_name,
            level=level[:80],
            tutor_mode=tutor_mode[:40],
            course=course[:160],
            allow_general_knowledge=settings.allow_general_knowledge,
            knowledge_mode=str(learning["knowledge_mode"]),
            learning_outcome=str(learning["learning_outcome"]),
            weekly_topic=str(learning["weekly_topic"]),
            institutional_instructions=str(learning["tutor_instructions"]),
            delivery_mode=delivery_mode,
        )
        vision_section = ""
        if vision_analysis is not None:
            vision_section = f"\n\nVERIFIED IMAGE ANALYSIS\n{ai_router.vision_context(vision_analysis)}"
        board_section = f"\n\nCURRENT WHITEBOARD CONTEXT\n{board_context[:12000]}" if board_context.strip() else ""
        prompt = (
            f"APPROVED COURSE CONTEXT\n{context}\n\n"
            f"KNOWLEDGE MODE\n{learning['knowledge_mode']}\n\n"
            f"LEARNING OUTCOME\n{learning['learning_outcome'] or 'Not selected'}\n\n"
            f"WEEKLY TOPIC\n{learning['weekly_topic'] or 'Not selected'}\n\n"
            f"LEARNER QUESTION\n{effective_message}"
            f"{vision_section}{board_section}"
        )
        try:
            result = await run_in_threadpool(
                ai_router.generate_text,
                instructions=instructions,
                prompt=prompt,
                history=list(history),
                task="tutor",
                max_tokens=(
                    settings.text_only_max_tokens if delivery_mode == "text_only"
                    else settings.low_data_max_tokens if delivery_mode == "low_data"
                    else settings.max_output_tokens
                ),
            )
            answer = result.text
            provider_name = result.provider
            model_name = result.model
            _record_usage(user, result, "tutor_chat")
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=f"AI service error: {exc}") from exc
        except Exception as exc:
            logger.exception("AI request failed")
            raise HTTPException(status_code=502, detail=f"AI service error: {type(exc).__name__}") from exc

        if settings.visual_plan_enabled and visual_requested:
            if delivery_mode == "low_data" and visual_preference == "auto":
                visual_preference = "steps"
            try:
                visual = await run_in_threadpool(
                    _create_visual_plan,
                    question=effective_message,
                    answer=answer,
                    level=level,
                    course=course,
                    preference=visual_preference,
                    has_image=bool(images),
                    vision_analysis=vision_analysis,
                    user=user,
                )
            except Exception:
                logger.exception("Visual plan generation failed")
                visual = None

    history.append({"role": "user", "content": effective_message})
    history.append({"role": "assistant", "content": answer})

    if user:
        try:
            title = effective_message.replace("\n", " ").strip()[:120] or "Learning session"
            accounts.ensure_chat_session(
                session_id=session_id,
                user_id=str(user["id"]),
                title=title,
                course=course,
            )
            accounts.add_chat_message(session_id=session_id, role="user", content=effective_message)
            accounts.add_chat_message(
                session_id=session_id,
                role="assistant",
                content=answer,
                sources=sources,
                provider=provider_name,
                model=model_name,
            )
            accounts.record_learning_event(
                user_id=str(user["id"]),
                class_id=str(learning["class_id"]) or None,
                event_type="tutor_question",
                topic=str(learning["weekly_topic"] or course or effective_message[:200]),
                metadata={
                    "provider": provider_name,
                    "model": model_name,
                    "had_image": bool(images),
                    "question": effective_message[:500],
                    "sources_count": len(sources),
                    "insufficient_context": insufficient_context,
                    "knowledge_mode": str(learning["knowledge_mode"]),
                    "learning_outcome": str(learning["learning_outcome"]),
                    "weekly_topic": str(learning["weekly_topic"]),
                    "delivery_mode": delivery_mode,
                },
            )
        except Exception:
            logger.exception("Signed-in learning session could not be persisted")

    return ChatResponse(
        answer=answer,
        sources=sources,
        session_id=session_id,
        demo=settings.demo_mode,
        visual=visual,
    )


def _normalise_practice_activity(activity: PracticeActivity) -> PracticeActivity:
    data = activity.model_dump()
    questions = []
    used: set[str] = set()
    for index, question in enumerate(data.get("questions", [])[:6], start=1):
        question_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(question.get("id") or f"q{index}")).strip("-")[:40] or f"q{index}"
        if question_id in used:
            question_id = f"{question_id}-{index}"
        used.add(question_id)
        question["id"] = question_id
        visual = question.get("visual")
        if visual:
            try:
                question["visual"] = _normalise_visual_plan(VisualPlan.model_validate(visual), has_image=False).model_dump()
            except Exception:
                question["visual"] = None
        questions.append(question)
    data["questions"] = questions
    return PracticeActivity.model_validate(data)


def _practice_public_question(practice_id: str, state: dict[str, Any]) -> PracticeQuestionResponse:
    activity: PracticeActivity = state["activity"]
    index = int(state["index"])
    completed = index >= len(activity.questions)
    if completed:
        return PracticeQuestionResponse(
            practice_id=practice_id,
            title=activity.title,
            topic=activity.topic,
            question_id="complete",
            question_number=len(activity.questions),
            question_count=len(activity.questions),
            prompt="Practice complete.",
            difficulty="standard",
            visual=None,
            score=int(state.get("total_score", 0)),
            completed=True,
            response_mode=str(state.get("practice_response_mode", "student_choice")),
            allowed_response_modes=["typed", "voice", "whiteboard"],
        )
    question = activity.questions[index]
    response_mode = str(state.get("practice_response_mode") or question.response_mode or "student_choice")
    allowed_modes = ["typed", "voice", "whiteboard"] if response_mode == "student_choice" else [response_mode]
    return PracticeQuestionResponse(
        practice_id=practice_id,
        title=activity.title,
        topic=activity.topic,
        question_id=question.id,
        question_number=index + 1,
        question_count=len(activity.questions),
        prompt=question.prompt,
        difficulty=question.difficulty,
        visual=question.visual,
        hint=question.hint,
        score=int(state.get("total_score", 0)),
        completed=False,
        response_mode=response_mode,
        allowed_response_modes=allowed_modes,
    )


def _demo_practice(topic: str) -> PracticeActivity:
    topic = topic.strip() or "the current topic"
    return PracticeActivity(
        title=f"Guided practice: {topic}",
        topic=topic,
        questions=[
            {
                "id": "q1",
                "prompt": f"In one or two sentences, explain the main idea of {topic}.",
                "expected_answer": f"A clear explanation of the central meaning or purpose of {topic}.",
                "accepted_variants": [],
                "marking_guide": "Award full credit for an accurate central idea stated in the learner's own words.",
                "hint": "State what it is and why it matters.",
                "explanation": "A strong answer defines the idea and connects it to its purpose or use.",
                "difficulty": "foundation",
                "visual": None,
            },
            {
                "id": "q2",
                "prompt": f"Give one suitable example or application of {topic} and explain the connection.",
                "expected_answer": f"A relevant example with a correct explanation of how it demonstrates {topic}.",
                "accepted_variants": [],
                "marking_guide": "The example must be relevant and the connection must be explained.",
                "hint": "Choose a familiar situation and name the exact feature that matches the topic.",
                "explanation": "Examples are useful only when the link to the concept is made explicit.",
                "difficulty": "standard",
                "visual": None,
            },
        ],
    )


@app.post("/api/practice/start", response_model=PracticeQuestionResponse)
async def start_practice(
    request: Request,
    topic: str = Form(...),
    level: str = Form(default="University"),
    course: str = Form(default=""),
    class_id: str = Form(default=""),
    learning_outcome: str = Form(default=""),
    weekly_topic: str = Form(default=""),
    question_count: int = Form(default=4),
) -> PracticeQuestionResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    learning = _learning_context(
        user=user, class_id=class_id.strip(), course=course,
        learning_outcome=learning_outcome, weekly_topic=weekly_topic
    )
    course = str(learning["course"])
    classroom = learning.get("classroom") or {}
    practice_response_mode = str(classroom.get("practice_response_mode") or ("whiteboard" if classroom.get("practice_whiteboard_required") else "student_choice"))
    if practice_response_mode not in {"student_choice", "typed", "voice", "whiteboard"}:
        practice_response_mode = "student_choice"
    topic = topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="Enter a topic for guided practice.")
    count = max(2, min(int(question_count), 6))
    context, _ = await run_in_threadpool(
        _course_context,
        " ".join([course, str(learning["learning_outcome"]), str(learning["weekly_topic"]), topic]).strip(),
        class_id=str(learning["class_id"]),
        knowledge_mode=str(learning["knowledge_mode"]),
    )

    if settings.demo_mode:
        activity = _demo_practice(topic)
    else:
        _require_text_ai()
        prompt = (
            f"APPROVED COURSE CONTEXT\n{context}\n\n"
            f"KNOWLEDGE MODE\n{learning['knowledge_mode']}\n\n"
            f"LEARNING OUTCOME\n{learning['learning_outcome'] or 'Not selected'}\n\n"
            f"WEEKLY TOPIC\n{learning['weekly_topic'] or 'Not selected'}\n\n"
            f"LECTURER INSTRUCTIONS\n{learning['tutor_instructions'] or 'None supplied'}\n\n"
            f"PRACTICE TOPIC\n{topic}\n\n"
            "Create an activity that directly assesses the selected outcome and weekly topic."
        )
        try:
            result = await run_in_threadpool(
                ai_router.generate_structured,
                schema=PracticeActivity,
                instructions=practice_generation_instructions(level=level[:80], course=course[:160], count=count, response_mode=practice_response_mode),
                prompt=prompt,
                task="practice_generation",
                max_tokens=max(settings.visual_max_output_tokens, 5000),
                prefer_deepseek=True,
            )
            activity = result.value if isinstance(result.value, PracticeActivity) else PracticeActivity.model_validate(result.value)
            _record_usage(user, result, "practice_generation")
        except Exception as exc:
            logger.exception("Practice generation failed")
            raise HTTPException(status_code=502, detail=f"Practice generation error: {type(exc).__name__}") from exc

    activity = _normalise_practice_activity(activity)
    for generated_question in activity.questions:
        generated_question.response_mode = practice_response_mode
    practice_id = str(uuid.uuid4())
    practice_sessions[practice_id] = {
        "activity": activity,
        "index": 0,
        "attempts": {},
        "best_scores": {},
        "total_score": 0,
        "created_at": time.time(),
        "user_id": str(user["id"]) if user else "",
        "topic": topic,
        "course": course,
        "class_id": str(learning["class_id"]),
        "learning_outcome": str(learning["learning_outcome"]),
        "weekly_topic": str(learning["weekly_topic"]),
        "knowledge_mode": str(learning["knowledge_mode"]),
        "practice_whiteboard_required": practice_response_mode == "whiteboard",
        "practice_response_mode": practice_response_mode,
        "level": level,
    }
    if user:
        try:
            accounts.record_learning_event(
                user_id=str(user["id"]),
                class_id=str(learning["class_id"]) or None,
                event_type="practice_started",
                topic=topic,
                metadata={
                    "question_count": len(activity.questions), "course": course,
                    "learning_outcome": str(learning["learning_outcome"]),
                    "weekly_topic": str(learning["weekly_topic"]),
                },
            )
        except Exception:
            logger.exception("Practice start could not be recorded")
    return _practice_public_question(practice_id, practice_sessions[practice_id])


def _normalise_practice_evaluation(evaluation: PracticeEvaluation) -> PracticeEvaluation:
    """Make mastery depend on the awarded score, not an inconsistent model boolean."""
    score = max(0, min(100, int(evaluation.score or 0)))
    correct = score >= 70
    feedback = (evaluation.feedback or "").strip()
    if not feedback:
        feedback = "Your response has been assessed. Review the hint and improve the next step." if not correct else "Your response demonstrates the required understanding."
    return evaluation.model_copy(update={"score": score, "correct": correct, "feedback": feedback})


def _practice_total_score(state: dict[str, Any], question_count: int) -> int:
    best_scores = state.setdefault("best_scores", {})
    if question_count <= 0:
        return 0
    return max(0, min(100, int(round(sum(int(value or 0) for value in best_scores.values()) / question_count))))


def _looks_like_unreadable_feedback(evaluation: PracticeEvaluation) -> bool:
    text = f"{evaluation.feedback} {evaluation.misconception} {evaluation.next_hint}".lower()
    phrases = (
        "no markable response", "no response received", "blank image", "nothing visible",
        "no visible response", "cannot see any", "could not identify any writing",
    )
    return evaluation.score <= 5 and any(phrase in text for phrase in phrases)


@app.post("/api/practice/check", response_model=PracticeCheckResponse)
async def check_practice_answer(
    request: Request,
    practice_id: str = Form(...),
    answer: str = Form(default=""),
    board_stroke_count: int = Form(default=0),
    board_capture_width: int = Form(default=0),
    board_capture_height: int = Form(default=0),
    board_ink_coverage: float = Form(default=0.0),
    board_image: UploadFile | None = File(default=None),
    audio_response: UploadFile | None = File(default=None),
) -> PracticeCheckResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    state = practice_sessions.get(practice_id)
    if state is None:
        raise HTTPException(status_code=404, detail="This practice session has expired. Start a new activity.")
    activity: PracticeActivity = state["activity"]
    index = int(state["index"])
    if index >= len(activity.questions):
        return PracticeCheckResponse(
            correct=True, score_awarded=0, total_score=int(state.get("total_score", 0)), question_score=100,
            feedback="Practice is already complete.", attempts=0, completed=True
        )
    question = activity.questions[index]
    answer = answer.strip()
    board = await _read_image(board_image, label="Learner's cropped handwritten practice response")
    board_stroke_count = max(0, min(int(board_stroke_count or 0), 10000))
    board_capture_width = max(0, min(int(board_capture_width or 0), 5000))
    board_capture_height = max(0, min(int(board_capture_height or 0), 5000))
    board_ink_coverage = max(0.0, min(float(board_ink_coverage or 0.0), 1.0))
    voice_transcript = ""
    if audio_response is not None:
        voice_transcript = await _transcribe_audio_upload(audio_response)
    response_mode = str(state.get("practice_response_mode", "student_choice"))
    if response_mode == "typed" and not answer:
        raise HTTPException(status_code=422, detail="Your lecturer requires a typed response for this practice question.")
    if response_mode == "voice" and not voice_transcript:
        raise HTTPException(status_code=422, detail="Your lecturer requires a recorded voice response for this practice question.")
    if response_mode == "whiteboard" and not board:
        raise HTTPException(status_code=422, detail="Your lecturer requires a handwritten whiteboard response for this practice question.")
    if not answer and not board and not voice_transcript:
        raise HTTPException(status_code=422, detail="Type, record, or write a response before checking your answer.")
    combined_answer = answer
    if voice_transcript:
        combined_answer = f"{answer}\n\nVOICE RESPONSE TRANSCRIPT\n{voice_transcript}".strip()
    attempts = int(state["attempts"].get(question.id, 0)) + 1
    state["attempts"][question.id] = attempts
    board_capture_note = (
        f"The browser confirmed {board_stroke_count} handwritten pen strokes in a cropped {board_capture_width} by {board_capture_height} pixel image "
        f"with estimated ink coverage {board_ink_coverage:.5f}. Assess all visible partial working and do not treat an incomplete answer as an absent answer."
        if board else "No whiteboard image was supplied."
    )
    marking_text = (
        f"QUESTION\n{question.prompt}\n\nEXPECTED ANSWER\n{question.expected_answer}\n\n"
        f"ACCEPTED VARIANTS\n{'; '.join(question.accepted_variants)}\n\n"
        f"MARKING GUIDE\n{question.marking_guide}\n\nREQUIRED RESPONSE MODE\n{response_mode}\n\n"
        f"WHITEBOARD CAPTURE INFORMATION\n{board_capture_note}\n\n"
        f"LEARNER ANSWER\n{combined_answer or '[supplied as cropped whiteboard image]'}"
    )
    if settings.demo_mode:
        normalised_answer = re.sub(r"\s+", " ", combined_answer.lower()).strip()
        terms = [t for t in re.findall(r"[a-zA-Z]{4,}", question.expected_answer.lower()) if t not in {"clear", "correct", "answer", "explanation"}]
        overlap = sum(term in normalised_answer for term in terms[:8])
        if board and not normalised_answer:
            evaluation = PracticeEvaluation(
                correct=False, score=45,
                feedback="Your handwritten response was captured. In live mode, the tutor will award marks for each visible correct step.",
                next_hint=question.hint,
            )
        else:
            correct = bool(normalised_answer) and overlap >= max(1, min(2, len(terms)))
            evaluation = PracticeEvaluation(
                correct=correct, score=80 if correct else 35,
                feedback="Your answer captures the main idea." if correct else "Your response shows some progress but needs a clearer link to the key idea.",
                next_hint="" if correct else question.hint,
            )
    else:
        try:
            if board:
                result = await run_in_threadpool(
                    ai_router.openai_parse_with_images,
                    schema=PracticeEvaluation,
                    instructions=practice_marking_instructions(level="learner"),
                    text=marking_text,
                    images=[board],
                    max_tokens=1800,
                )
            else:
                _require_text_ai()
                result = await run_in_threadpool(
                    ai_router.generate_structured,
                    schema=PracticeEvaluation,
                    instructions=practice_marking_instructions(level="learner"),
                    prompt=marking_text,
                    task="practice_marking",
                    max_tokens=1800,
                    prefer_deepseek=True,
                )
            evaluation = result.value if isinstance(result.value, PracticeEvaluation) else PracticeEvaluation.model_validate(result.value)
            _record_usage(user, result, "practice_marking")
            evaluation = _normalise_practice_evaluation(evaluation)
            if board and board_stroke_count > 0 and _looks_like_unreadable_feedback(evaluation):
                retry_text = marking_text + (
                    "\n\nSECOND INSPECTION REQUIRED\nThe client has verified that the cropped image contains handwriting. "
                    "Zoom in, inspect every visible line, and award partial credit for any readable correct setup, definition, formula, substitution or reasoning. "
                    "Do not mark the response complete unless the score reaches the mastery threshold."
                )
                retry = await run_in_threadpool(
                    ai_router.openai_parse_with_images,
                    schema=PracticeEvaluation,
                    instructions=practice_marking_instructions(level="learner"),
                    text=retry_text,
                    images=[board],
                    max_tokens=1800,
                )
                _record_usage(user, retry, "practice_marking_retry")
                evaluation = retry.value if isinstance(retry.value, PracticeEvaluation) else PracticeEvaluation.model_validate(retry.value)
                evaluation = _normalise_practice_evaluation(evaluation)
                if _looks_like_unreadable_feedback(evaluation):
                    evaluation = evaluation.model_copy(update={
                        "correct": False,
                        "score": 0,
                        "feedback": "Your handwriting was captured, but the tutor could not read enough of it reliably. Keep this attempt open, use a dark pen, write larger, and submit again.",
                        "next_hint": "Write one complete step per line and leave space between symbols or words.",
                    })
        except Exception as exc:
            logger.exception("Practice marking failed")
            raise HTTPException(status_code=502, detail=f"Practice marking error: {type(exc).__name__}") from exc

    evaluation = _normalise_practice_evaluation(evaluation)
    best_scores = state.setdefault("best_scores", {})
    previous_best = int(best_scores.get(question.id, 0) or 0)
    best_scores[question.id] = max(previous_best, int(evaluation.score))
    state["total_score"] = _practice_total_score(state, len(activity.questions))
    score_awarded = max(0, int(evaluation.score) - previous_best)
    next_question = None
    completed = False
    if evaluation.correct:
        state["index"] = index + 1
        completed = state["index"] >= len(activity.questions)
        if not completed:
            next_question = _practice_public_question(practice_id, state)
    if user:
        try:
            event_meta = {
                "correct": evaluation.correct, "attempts": attempts, "question_id": question.id,
                "used_whiteboard": bool(board), "used_voice": bool(voice_transcript), "response_mode": response_mode,
                "misconception": evaluation.misconception, "question_score": int(evaluation.score),
                "board_stroke_count": board_stroke_count, "board_capture_width": board_capture_width,
                "board_capture_height": board_capture_height, "board_ink_coverage": board_ink_coverage,
                "learning_outcome": state.get("learning_outcome", ""),
                "weekly_topic": state.get("weekly_topic", ""),
            }
            accounts.record_learning_event(
                user_id=str(user["id"]), class_id=state.get("class_id") or None,
                event_type="practice_attempt", topic=str(state.get("topic") or activity.topic),
                score=float(evaluation.score), metadata=event_meta
            )
            if completed:
                accounts.record_learning_event(
                    user_id=str(user["id"]), class_id=state.get("class_id") or None,
                    event_type="practice_completed", topic=str(state.get("topic") or activity.topic),
                    score=float(state.get("total_score", 0)),
                    metadata={
                        "questions": len(activity.questions), "course": state.get("course", ""),
                        "learning_outcome": state.get("learning_outcome", ""),
                        "weekly_topic": state.get("weekly_topic", ""),
                    }
                )
        except Exception:
            logger.exception("Practice progress could not be recorded")
    return PracticeCheckResponse(
        correct=evaluation.correct,
        score_awarded=score_awarded,
        total_score=int(state.get("total_score", 0)),
        question_score=int(evaluation.score),
        response_received=bool(answer or board or voice_transcript),
        feedback=evaluation.feedback,
        hint=evaluation.next_hint or (question.hint if not evaluation.correct else ""),
        attempts=attempts,
        completed=completed,
        next_question=next_question,
    )


@app.post("/api/practice/reveal", response_model=PracticeRevealResponse)
async def reveal_practice_solution(request: Request, practice_id: str = Form(...)) -> PracticeRevealResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    state = practice_sessions.get(practice_id)
    if state is None:
        raise HTTPException(status_code=404, detail="This practice session has expired.")
    activity: PracticeActivity = state["activity"]
    index = int(state["index"])
    if index >= len(activity.questions):
        return PracticeRevealResponse(explanation="Practice is complete.", expected_answer="", completed=True)
    question = activity.questions[index]
    state["index"] = index + 1
    completed = state["index"] >= len(activity.questions)
    next_question = None if completed else _practice_public_question(practice_id, state)
    if user:
        try:
            accounts.record_learning_event(
                user_id=str(user["id"]), class_id=state.get("class_id") or None,
                event_type="practice_solution_revealed", topic=str(state.get("topic") or activity.topic), score=0,
                metadata={
                    "question_id": question.id, "learning_outcome": state.get("learning_outcome", ""),
                    "weekly_topic": state.get("weekly_topic", ""),
                }
            )
            if completed:
                accounts.record_learning_event(
                    user_id=str(user["id"]), class_id=state.get("class_id") or None,
                    event_type="practice_completed", topic=str(state.get("topic") or activity.topic),
                    score=float(state.get("total_score", 0)),
                    metadata={
                        "questions": len(activity.questions), "solutions_revealed": True,
                        "learning_outcome": state.get("learning_outcome", ""),
                        "weekly_topic": state.get("weekly_topic", ""),
                    }
                )
        except Exception:
            logger.exception("Practice reveal could not be recorded")
    return PracticeRevealResponse(explanation=question.explanation, expected_answer=question.expected_answer, completed=completed, next_question=next_question)


@app.post("/api/work/check", response_model=WorkCheckResponse)
async def check_whiteboard_work(
    request: Request,
    problem_context: str = Form(default=""),
    board_context: str = Form(default=""),
    level: str = Form(default="University"),
    course: str = Form(default=""),
    class_id: str = Form(default=""),
    learning_outcome: str = Form(default=""),
    weekly_topic: str = Form(default=""),
    board_image: UploadFile = File(...),
) -> WorkCheckResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    learning = _learning_context(
        user=user, class_id=class_id.strip(), course=course,
        learning_outcome=learning_outcome, weekly_topic=weekly_topic
    )
    course = str(learning["course"])
    board = await _read_image(board_image, label="Learner's current whiteboard working")
    if board is None:
        raise HTTPException(status_code=422, detail="Attach the whiteboard before checking the work.")
    problem_context = problem_context.strip()[:8000]
    board_context = board_context.strip()[:12000]
    if settings.demo_mode:
        result = WorkCheck(
            verdict="partly_correct", score=60,
            summary="The board was received. Live mode will inspect each visible step and identify the first point needing correction.",
            strengths=["The learner has shown working rather than only a final answer."],
            corrections=["Enable the OpenAI vision key for detailed handwriting analysis."],
            next_step="State the problem above the working, then use Check my work again.",
            first_error_step=2,
            step_results=[
                {"step_number": 1, "label": "Visible setup", "status": "correct", "feedback": "Working is shown clearly."},
                {"step_number": 2, "label": "Detailed calculation", "status": "unclear", "feedback": "Vision analysis is required to verify this step."},
            ],
            annotations=[]
        )
    else:
        try:
            provider_result = await run_in_threadpool(ai_router.openai_parse_with_images, schema=WorkCheck, instructions=work_check_instructions(
                    level=level[:80], course=course[:160], learning_outcome=str(learning["learning_outcome"])
                ), text=f"PROBLEM OR QUESTION CONTEXT\n{problem_context or 'Not supplied'}\n\nWHITEBOARD STRUCTURE\n{board_context or 'Not supplied'}\n\nInspect the image and return the work check.", images=[board], max_tokens=2600)
            result = provider_result.value if isinstance(provider_result.value, WorkCheck) else WorkCheck.model_validate(provider_result.value)
            _record_usage(user, provider_result, "whiteboard_check")
        except Exception as exc:
            logger.exception("Whiteboard work check failed")
            raise HTTPException(status_code=502, detail=f"Work-check error: {type(exc).__name__}") from exc
    step_visuals = [
        {
            "title": f"Step {step.step_number}: {step.label or step.status.replace('_', ' ').title()}",
            "explanation": step.feedback + ((" Correction: " + step.correction) if step.correction else ""),
            "equation": "",
            "narration": step.feedback,
        }
        for step in result.step_results[:12]
    ]
    if not step_visuals:
        step_visuals = (
            [{"title": "What is working", "explanation": item, "equation": "", "narration": item} for item in result.strengths[:3]]
            + [{"title": "Correction", "explanation": item, "equation": "", "narration": item} for item in result.corrections[:4]]
        )
    if result.next_step:
        step_visuals.append({"title": "Next step", "explanation": result.next_step, "equation": "", "narration": result.next_step})
    visual = VisualPlan(
        kind="image_annotation" if result.annotations else "steps",
        title="Step-level check of your working", caption=result.summary,
        steps=step_visuals, annotations=result.annotations
    )
    visual = _normalise_visual_plan(visual, has_image=True)
    if user:
        try:
            accounts.record_learning_event(
                user_id=str(user["id"]), class_id=str(learning["class_id"]) or None,
                event_type="whiteboard_check",
                topic=str(learning["weekly_topic"] or course or problem_context[:200] or "Whiteboard work"),
                score=float(result.score),
                metadata={
                    "verdict": result.verdict,
                    "first_error_step": result.first_error_step,
                    "corrections": result.corrections,
                    "learning_outcome": str(learning["learning_outcome"]),
                    "weekly_topic": str(learning["weekly_topic"]),
                    "step_results": [item.model_dump() for item in result.step_results],
                }
            )
        except Exception:
            logger.exception("Whiteboard progress could not be recorded")
    return WorkCheckResponse(**result.model_dump(), visual=visual)


async def _transcribe_audio_upload(audio: UploadFile) -> str:
    openai_client = _require_openai()
    extension = _audio_upload_extension(audio.filename, audio.content_type)
    if extension is None:
        logger.warning(
            "Rejected audio upload: filename=%r content_type=%r",
            audio.filename,
            audio.content_type,
        )
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio format. Use WebM, WAV, MP3, MP4, M4A, OGG, AAC or FLAC.",
        )
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="The recording is empty.")
    if len(data) > settings.max_audio_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Audio must be no larger than {settings.max_audio_mb} MB.")

    buffer = io.BytesIO(data)
    safe_stem = Path(_safe_filename(audio.filename or "recording")).stem or "recording"
    buffer.name = f"{safe_stem}{extension}"

    def create_transcription():
        return openai_client.audio.transcriptions.create(
            model=settings.transcribe_model,
            file=buffer,
        )

    try:
        result = await run_in_threadpool(create_transcription)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transcription service error: {type(exc).__name__}") from exc
    text = getattr(result, "text", "") or ""
    return text.strip()


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict[str, str]:
    _check_rate_limit(request)
    _ai_user(request)
    return {"text": await _transcribe_audio_upload(audio)}


@app.post("/api/speech")
async def speech(request: Request, payload: SpeechRequest) -> Response:
    _check_rate_limit(request)
    _ai_user(request)
    openai_client = _require_openai()
    voice = payload.voice if payload.voice in VOICE_OPTIONS else settings.default_voice
    speech_text = _plain_text_for_speech(payload.text)
    if not speech_text:
        raise HTTPException(status_code=422, detail="There is no readable text to speak.")

    def create_speech() -> bytes:
        kwargs: dict[str, Any] = {
            "model": settings.tts_model,
            "voice": voice,
            "input": speech_text,
            "response_format": "mp3",
            "speed": payload.speed,
        }
        if settings.tts_model.startswith("gpt-4o-mini-tts"):
            if payload.style == "guided_lecture":
                kwargs["instructions"] = (
                    "Speak like an experienced university lecturer teaching a real class. "
                    "Use a warm, conversational British-English delivery with natural variation in pace and emphasis. "
                    "Do not sound like you are reading bullet points. Connect ideas smoothly. "
                    "Pause briefly after an important definition, before a worked example, and before a check question. "
                    "Slow down slightly for equations, technical terms and multi-step reasoning. "
                    "Use gentle transitions such as 'now', 'for example' and 'notice that' only where they fit naturally. "
                    "Avoid exaggerated enthusiasm, robotic rhythm, or equal pauses after every sentence."
                )
            else:
                kwargs["instructions"] = "Speak as a calm, warm and patient tutor at a moderate pace."
        result = openai_client.audio.speech.create(**kwargs)
        return result.read()

    try:
        audio_bytes = await run_in_threadpool(create_speech)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Speech service error: {type(exc).__name__}") from exc
    return Response(content=audio_bytes, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


def _section_plan_answer(plan: SectionLessonPlan) -> str:
    parts: list[str] = [f"# {plan.title}"]
    if plan.learning_objectives:
        parts.append("## Learning objectives\n" + "\n".join(
            f"{index}. {item}" for index, item in enumerate(plan.learning_objectives, 1)
        ))
    if plan.introduction:
        parts.append("## Introduction\n" + plan.introduction)
    for block in plan.detailed_notes:
        heading = block.heading or "Detailed explanation"
        text = f"## {heading}\n{block.explanation}".strip()
        if block.example:
            text += f"\n\n**Worked example or illustration:** {block.example}"
        if block.key_point:
            text += f"\n\n**Key point:** {block.key_point}"
        parts.append(text)
    if plan.key_terms:
        parts.append("## Key terms\n" + "\n".join(f"- {item}" for item in plan.key_terms))
    if plan.summary:
        parts.append("## Summary\n" + plan.summary)
    if plan.self_check_questions:
        parts.append("## Check your understanding\n" + "\n".join(
            f"{index}. {item}" for index, item in enumerate(plan.self_check_questions, 1)
        ))
    return "\n\n".join(part for part in parts if part.strip())


def _demo_section_plan(title: str, content: str) -> SectionLessonPlan:
    excerpt = re.sub(r"\s+", " ", content).strip()[:900] or "The lecturer's selected subsection will be explained here."
    return SectionLessonPlan(
        title=title,
        learning_objectives=[f"Explain the main ideas in {title}", "Apply the ideas to a simple example"],
        introduction=f"This demonstration lesson is grounded in the selected subsection, {title}.",
        detailed_notes=[
            {
                "heading": "Core explanation",
                "explanation": excerpt,
                "example": "Connect the central idea to a familiar course example.",
                "key_point": "Use the uploaded lecturer material as the main authority.",
            },
            {
                "heading": "How to study this subsection",
                "explanation": "Read the explanation, inspect the slide sequence, then answer the self-check questions or use the practice whiteboard.",
                "example": "Write the method or concept in your own words.",
                "key_point": "Active practice is more useful than passive reading.",
            },
        ],
        key_terms=[title],
        summary=f"The subsection introduces the main concepts and applications of {title}.",
        self_check_questions=[f"What is the central idea of {title}?", "How would you apply it in one example?"],
        slides=[
            {
                "title": title,
                "bullets": ["Purpose of the subsection", "Main idea", "Expected learning"],
                "explanation": excerpt[:600],
                "speaker_note": "Introduce the learning purpose and relate it to the course objectives.",
            },
            {
                "title": "Detailed explanation",
                "bullets": ["Define the idea", "Show the relationship", "Address a likely misconception"],
                "explanation": excerpt,
                "worked_example": "Use a simple course-relevant example.",
                "speaker_note": "Explain each point carefully and pause for the learner to reflect.",
            },
            {
                "title": "Worked application",
                "bullets": ["Identify what is given", "Apply the course method", "Interpret the result"],
                "explanation": "Work through a course-relevant illustration one stage at a time and connect each stage to the lecturer's explanation.",
                "worked_example": "Use the selected subsection to create a simple example, explain the method, and state what the result means.",
                "key_terms": ["method", "application", "interpretation"],
                "speaker_note": "Do not rush to the answer. Explain why each operation or conceptual link is appropriate.",
            },
            {
                "title": "Common difficulty and correction",
                "bullets": ["Recognise a likely misconception", "Contrast it with the correct idea", "Use an evidence-based correction"],
                "explanation": "Clarify a misunderstanding that learners commonly develop when reading this subsection and show how the approved material resolves it.",
                "check_question": "Which part of the explanation is easiest to misunderstand, and how would you correct it?",
                "speaker_note": "Invite the learner to compare the incorrect and correct interpretations before continuing.",
            },
            {
                "title": "Check your understanding",
                "bullets": ["State the idea in your own words", "Give one application"],
                "check_question": f"How would you explain {title} to another learner?",
                "speaker_note": "Ask the learner to respond before displaying further practice.",
            },
        ],
    )


# Account, class, dashboard and reusable lesson endpoints

@app.post("/api/admin/bootstrap", response_model=AuthResponse)
async def bootstrap_administrator(payload: AdminBootstrapRequest) -> AuthResponse:
    if not settings.admin_key or payload.admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="The administrator bootstrap key is incorrect.")
    existing_admins = await run_in_threadpool(accounts.list_users, role="admin", limit=2)
    if existing_admins:
        raise HTTPException(status_code=409, detail="An administrator account already exists. Sign in through the administrator portal.")
    try:
        user = await run_in_threadpool(
            accounts.create_user,
            email=payload.email,
            password_hash=auth.hash_password(payload.password),
            display_name=payload.display_name,
            role="admin",
            active=True,
            must_change_password=False,
        )
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthResponse(access_token=auth.issue_token(user), user=UserPublic(**accounts.public_user(user)))


@app.post("/api/auth/register", response_model=AuthResponse)
async def register_account(payload: RegisterRequest) -> AuthResponse:
    if payload.role != "student":
        if not settings.allow_public_teacher_registration:
            raise HTTPException(status_code=403, detail="Lecturer accounts are created by an administrator.")
        valid_teacher_code = bool(settings.teacher_invite_code) and payload.teacher_invite_code == settings.teacher_invite_code
        if not valid_teacher_code:
            raise HTTPException(status_code=403, detail="A valid lecturer invitation code is required.")
    if payload.role == "student" and not settings.allow_student_registration:
        raise HTTPException(status_code=403, detail="Student registration is currently closed.")
    try:
        password_hash = await run_in_threadpool(auth.hash_password, payload.password)
        user = await run_in_threadpool(
            accounts.create_user,
            email=payload.email,
            password_hash=password_hash,
            display_name=payload.display_name,
            role=payload.role,
            active=True,
            must_change_password=False,
        )
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthResponse(access_token=auth.issue_token(user), user=UserPublic(**accounts.public_user(user)))


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_account(payload: LoginRequest) -> AuthResponse:
    user = await run_in_threadpool(accounts.get_user_by_email, payload.email)
    if not user or not auth.verify_password(payload.password, str(user.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="Incorrect email address or password.")
    if not bool(user.get("active", True)):
        raise HTTPException(status_code=403, detail="This account has been deactivated. Contact the administrator.")
    await run_in_threadpool(accounts.touch_login, str(user["id"]))
    return AuthResponse(access_token=auth.issue_token(user), user=UserPublic(**accounts.public_user(user)))


@app.get("/api/auth/me", response_model=UserPublic)
async def current_account(request: Request) -> UserPublic:
    return UserPublic(**accounts.public_user(_required_user(request)))


@app.post("/api/auth/change-password")
async def change_password(request: Request, payload: PasswordChangeRequest) -> dict[str, str]:
    user = _required_user(request)
    if not auth.verify_password(payload.current_password, str(user.get("password_hash", ""))):
        raise HTTPException(status_code=400, detail="The current password is incorrect.")
    password_hash = await run_in_threadpool(auth.hash_password, payload.new_password)
    await run_in_threadpool(accounts.update_password, user_id=str(user["id"]), password_hash=password_hash, must_change_password=False)
    return {"status": "password_changed"}


@app.get("/api/admin/lecturers", response_model=list[UserPublic])
async def list_lecturers(request: Request) -> list[UserPublic]:
    _required_admin(request)
    rows = await run_in_threadpool(accounts.list_users, role="teacher", limit=2000)
    return [UserPublic(**row) for row in rows]


@app.post("/api/admin/lecturers", response_model=AdminLecturerResponse)
async def create_lecturer(request: Request, payload: AdminCreateLecturerRequest) -> AdminLecturerResponse:
    _required_admin(request)
    temporary_password = payload.temporary_password.strip() or _temporary_password()
    try:
        password_hash = await run_in_threadpool(auth.hash_password, temporary_password)
        user = await run_in_threadpool(
            accounts.create_user,
            email=payload.email,
            password_hash=password_hash,
            display_name=payload.display_name,
            role="teacher",
            active=True,
            must_change_password=True,
        )
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdminLecturerResponse(user=UserPublic(**accounts.public_user(user)), temporary_password=temporary_password)


@app.patch("/api/admin/users/{user_id}/status", response_model=UserPublic)
async def update_user_status(request: Request, user_id: str, payload: AdminUserStatusRequest) -> UserPublic:
    admin = _required_admin(request)
    if user_id == str(admin["id"]) and not payload.active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own administrator account.")
    try:
        user = await run_in_threadpool(accounts.set_user_active, user_id=user_id, active=payload.active)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UserPublic(**accounts.public_user(user))


@app.post("/api/admin/users/{user_id}/reset-password", response_model=PasswordResetResponse)
async def reset_user_password(request: Request, user_id: str) -> PasswordResetResponse:
    _required_admin(request)
    user = await run_in_threadpool(accounts.get_user, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    temporary_password = _temporary_password()
    password_hash = await run_in_threadpool(auth.hash_password, temporary_password)
    await run_in_threadpool(accounts.update_password, user_id=user_id, password_hash=password_hash, must_change_password=True)
    return PasswordResetResponse(temporary_password=temporary_password)


@app.get("/api/classes", response_model=list[ClassPublic])
async def list_classes(request: Request) -> list[ClassPublic]:
    user = _required_user(request)
    rows = await run_in_threadpool(accounts.classes_for_user, str(user["id"]), str(user["role"]))
    return [ClassPublic(**row) for row in rows]


@app.post("/api/classes", response_model=ClassPublic)
async def create_class(request: Request, payload: ClassCreateRequest) -> ClassPublic:
    user = _required_lecturer(request)
    row = await run_in_threadpool(
        accounts.create_class,
        teacher_id=str(user["id"]),
        name=payload.name,
        subject=payload.subject,
        knowledge_mode=payload.knowledge_mode,
        learning_outcomes=payload.learning_outcomes,
        weekly_topics=payload.weekly_topics,
        recommended_readings=payload.recommended_readings,
        tutor_instructions=payload.tutor_instructions,
        practice_whiteboard_required=payload.practice_whiteboard_required,
        practice_response_mode=payload.practice_response_mode,
    )
    return ClassPublic(**row)


@app.patch("/api/classes/{class_id}/profile", response_model=ClassPublic)
async def update_class_profile(request: Request, class_id: str, payload: ClassProfileUpdateRequest) -> ClassPublic:
    user = _required_lecturer(request)
    try:
        row = await run_in_threadpool(
            accounts.update_class_profile,
            class_id=class_id,
            teacher_id=str(user["id"]),
            name=payload.name,
            subject=payload.subject,
            knowledge_mode=payload.knowledge_mode,
            learning_outcomes=payload.learning_outcomes,
            weekly_topics=payload.weekly_topics,
            recommended_readings=payload.recommended_readings,
            tutor_instructions=payload.tutor_instructions,
            practice_whiteboard_required=payload.practice_whiteboard_required,
            practice_response_mode=payload.practice_response_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ClassPublic(**row)


@app.post("/api/classes/{class_id}/regenerate-code", response_model=ClassPublic)
async def regenerate_class_code(request: Request, class_id: str) -> ClassPublic:
    user = _required_lecturer(request)
    try:
        row = await run_in_threadpool(
            accounts.regenerate_join_code,
            class_id=class_id,
            teacher_id=str(user["id"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ClassPublic(**row)


@app.post("/api/classes/join", response_model=ClassPublic)
async def join_class(request: Request, payload: ClassJoinRequest) -> ClassPublic:
    user = _required_user(request)
    if user.get("role") != "student":
        raise HTTPException(status_code=403, detail="Only student accounts can join a class.")
    try:
        row = await run_in_threadpool(
            accounts.join_class,
            student_id=str(user["id"]),
            join_code=payload.join_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ClassPublic(**row)


@app.get("/api/dashboard", response_model=DashboardResponse)
async def dashboard(request: Request) -> DashboardResponse:
    user = _required_user(request)
    data = await run_in_threadpool(accounts.dashboard, str(user["id"]), str(user["role"]))
    return DashboardResponse(**data)


@app.post("/api/video/conversation", response_model=LiveVideoResponse)
async def create_live_video_conversation(request: Request, payload: LiveVideoRequest) -> LiveVideoResponse:
    _required_user(request)
    raise HTTPException(
        status_code=410,
        detail=(
            "Live avatar video has been retired for the institutional service because it creates high per-student cost and bandwidth demand. "
            "Use text, audio, image analysis, the interactive whiteboard, or reusable class lesson videos."
        ),
    )


def _video_response(job: dict[str, Any]) -> LessonVideoResponse:
    return LessonVideoResponse(
        id=str(job.get("id", "")),
        title=str(job.get("title", "Lesson video")),
        status=str(job.get("status", "script_ready")),
        video_id=str(job.get("video_id", "")),
        hosted_url=str(job.get("hosted_url", "")),
        download_url=str(job.get("download_url", "")),
        stream_url=str(job.get("stream_url", "")),
        script=str(job.get("script", "")),
        estimated_minutes=float(job.get("estimated_minutes", 0) or 0),
        provider="tavus" if job.get("video_id") else "lesson_package",
    )


@app.post("/api/video/generate", response_model=LessonVideoResponse)
async def generate_lesson_video(request: Request, payload: LessonVideoRequest) -> LessonVideoResponse:
    _check_rate_limit(request)
    user = _required_teacher(request)
    if not payload.class_id:
        raise HTTPException(status_code=422, detail="Select a class so the reusable lesson can be shared with enrolled students.")
    classroom = await run_in_threadpool(
        accounts.class_for_user, class_id=payload.class_id, user_id=str(user["id"]), role=str(user["role"])
    )
    if not classroom:
        raise HTTPException(status_code=403, detail="You do not manage the selected class.")
    limit = settings.teacher_video_monthly_limit
    if limit > 0 and accounts.monthly_video_count(str(user["id"])) >= limit:
        raise HTTPException(status_code=429, detail=f"The monthly lesson-video limit of {limit} has been reached.")
    _require_text_ai()
    course_name = str(classroom.get("subject") or classroom.get("name") or payload.course)
    context, _ = await run_in_threadpool(
        _course_context,
        " ".join([course_name, payload.topic]).strip(),
        class_id=payload.class_id,
        knowledge_mode=str(classroom.get("knowledge_mode") or "course_only"),
    )
    prompt = (
        f"APPROVED COURSE CONTEXT\n{context}\n\nTOPIC\n{payload.topic}\n\n"
        f"CURRENT TUTOR ANSWER\n{payload.current_answer if payload.use_current_answer else 'Not supplied'}\n\n"
        "Create the lesson-video plan."
    )
    try:
        ai_result = await run_in_threadpool(
            ai_router.generate_structured,
            schema=LessonVideoPlan,
            instructions=lesson_video_instructions(level=payload.level, course=course_name, length=payload.length),
            prompt=prompt,
            task="lesson_video_script",
            max_tokens=6500,
            prefer_deepseek=True,
        )
        plan = ai_result.value if isinstance(ai_result.value, LessonVideoPlan) else LessonVideoPlan.model_validate(ai_result.value)
        _record_usage(user, ai_result, "lesson_video_script")
    except Exception as exc:
        logger.exception("Lesson video script generation failed")
        raise HTTPException(status_code=502, detail=f"Lesson-video planning error: {type(exc).__name__}") from exc
    visual = {
        "kind": "slides",
        "title": plan.title,
        "caption": "AI-generated lesson slides",
        "slides": [slide.model_dump() for slide in plan.slides],
    }
    job = await run_in_threadpool(
        accounts.create_video_job,
        user_id=str(user["id"]),
        title=plan.title,
        topic=payload.topic,
        script=plan.script,
        visual=visual,
        estimated_minutes=plan.estimated_minutes,
        class_id=payload.class_id or None,
    )
    if settings.tavus_video_ready:
        base = settings.public_app_url.rstrip("/")
        background_url = f"{base}/lesson-background/{job['id']}?token={job['public_token']}" if base else ""
        try:
            remote = await tavus.create_video(title=plan.title, script=plan.script, background_url=background_url)
            video_id = str(remote.get("video_id") or remote.get("id") or "")
            status = str(remote.get("status") or "queued")
            await run_in_threadpool(
                accounts.update_video_job,
                str(job["id"]),
                provider_job_id=video_id,
                status=status,
                hosted_url=str(remote.get("hosted_url") or ""),
            )
            job = await run_in_threadpool(accounts.get_video_job, str(job["id"]), user_id=str(user["id"])) or job
        except TavusError as exc:
            logger.warning("Tavus video submission failed: %s", exc)
            await run_in_threadpool(accounts.update_video_job, str(job["id"]), status="script_ready")
    await run_in_threadpool(
        accounts.record_learning_event,
        user_id=str(user["id"]),
        class_id=payload.class_id,
        event_type="lesson_video_created",
        topic=payload.topic,
        metadata={"video_job_id": job["id"], "status": job.get("status", "script_ready")},
    )
    return _video_response(job)


@app.get("/api/videos", response_model=list[LessonVideoResponse])
async def list_lesson_videos(request: Request) -> list[LessonVideoResponse]:
    user = _required_user(request)
    rows = await run_in_threadpool(accounts.list_available_videos, str(user["id"]), str(user["role"]))
    return [_video_response(row) for row in rows]


@app.get("/api/video/{job_id}", response_model=LessonVideoResponse)
async def get_lesson_video(request: Request, job_id: str) -> LessonVideoResponse:
    user = _required_user(request)
    job = await run_in_threadpool(accounts.get_available_video, job_id, str(user["id"]), str(user["role"]))
    if not job:
        raise HTTPException(status_code=404, detail="Lesson video not found.")
    finished = {"ready", "completed", "failed", "error"}
    if job.get("video_id") and settings.tavus_api_key and str(job.get("status", "")).lower() not in finished:
        try:
            remote = await tavus.get_video(str(job["video_id"]))
            await run_in_threadpool(
                accounts.update_video_job,
                job_id,
                status=str(remote.get("status") or job.get("status") or "processing"),
                hosted_url=str(remote.get("hosted_url") or remote.get("video_url") or job.get("hosted_url") or ""),
                download_url=str(remote.get("download_url") or job.get("download_url") or ""),
                stream_url=str(remote.get("stream_url") or remote.get("hls_url") or job.get("stream_url") or ""),
            )
            job = await run_in_threadpool(accounts.get_available_video, job_id, str(user["id"]), str(user["role"])) or job
        except TavusError as exc:
            logger.warning("Could not refresh Tavus job %s: %s", job_id, exc)
    return _video_response(job)


@app.get("/lesson-background/{job_id}", response_class=HTMLResponse, include_in_schema=False)
async def lesson_background(job_id: str, token: str = "") -> HTMLResponse:
    job = await run_in_threadpool(accounts.get_video_job, job_id, public_token=token)
    if not job:
        raise HTTPException(status_code=404, detail="Lesson background not found.")
    visual = job.get("visual") or {}
    slides = visual.get("slides") or [{
        "title": job.get("title", "Lesson"), "bullets": [job.get("topic", "")],
        "equation": "", "explanation": "", "worked_example": "", "key_terms": [],
        "check_question": "", "speaker_note": ""
    }]
    slides_json = json.dumps(slides, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html.escape(str(job.get("title", "Lesson")))
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{safe_title}</title><style>
html,body{{margin:0;min-height:100%;font-family:Arial,sans-serif;background:#eef6f3;color:#123}}
body{{display:grid;place-items:center;padding:2vh 2vw;box-sizing:border-box}}
.slide{{width:min(1180px,92vw);min-height:82vh;background:white;border-radius:28px;padding:3.5vw;box-shadow:0 20px 60px #1233;display:flex;flex-direction:column;overflow:auto;box-sizing:border-box}}
h1{{font-size:clamp(30px,4vw,58px);margin:0 0 1.4rem;color:#0b5d4b}}
li,p{{font-size:clamp(18px,1.7vw,28px);line-height:1.45}}li{{margin:.45rem 0}}
.eq{{font-size:clamp(22px,2.4vw,38px);margin:1rem 0;text-align:center;background:#f4f0df;padding:1rem;border-radius:16px}}
.block{{padding:1rem 1.2rem;margin:.6rem 0;border-radius:14px;background:#eff8f5;border-left:5px solid #0b5d4b}}
.example{{background:#f4f0ff;border-left-color:#6848a8}}.check{{background:#fff7e6;border-left-color:#b27610}}
.terms span{{display:inline-block;background:#e8f0ff;padding:.35rem .65rem;border-radius:999px;margin:.2rem}}
.note{{font-size:clamp(15px,1.25vw,21px);color:#52635d;border-top:1px solid #dce8e3;padding-top:1rem}}
.counter{{position:fixed;right:4vw;bottom:2vw;font-size:1rem;background:#fff;padding:.45rem .75rem;border-radius:999px}}
</style></head><body><main class='slide'><h1 id='title'></h1><ul id='bullets'></ul><div id='eq' class='eq'></div><div id='explanation' class='block'></div><div id='example' class='block example'></div><div id='terms' class='terms'></div><div id='check' class='block check'></div><p id='note' class='note'></p></main><div id='counter' class='counter'></div>
<script>const slides={slides_json};let i=0;function esc(x){{return String(x??'').replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}function fill(id,text){{const e=document.getElementById(id);e.textContent=text||'';e.style.display=text?'block':'none'}}function show(){{const s=slides[i]||{{}};document.getElementById('title').textContent=s.title||'';document.getElementById('bullets').innerHTML=(s.bullets||[]).map(x=>'<li>'+esc(x)+'</li>').join('');fill('eq',s.equation);fill('explanation',s.explanation);fill('example',s.worked_example);const terms=document.getElementById('terms');terms.innerHTML=(s.key_terms||[]).map(x=>'<span>'+esc(x)+'</span>').join('');terms.style.display=(s.key_terms||[]).length?'block':'none';fill('check',s.check_question);fill('note',s.speaker_note);document.getElementById('counter').textContent=(i+1)+' / '+slides.length}}show();setInterval(()=>{{i=(i+1)%slides.length;show()}},14000);</script></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/api/classes/{class_id}/course-structure")
async def course_structure(request: Request, class_id: str) -> dict[str, Any]:
    user = _required_user(request)
    classroom = await run_in_threadpool(
        accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
    )
    if not classroom:
        raise HTTPException(status_code=403, detail="You do not have access to this course.")
    documents = await run_in_threadpool(course_content.list_structure, class_id)
    weekly_plan = await run_in_threadpool(
        course_content.weekly_plan, class_id,
        list(classroom.get("weekly_topics", [])), list(classroom.get("learning_outcomes", []))
    )
    return {"classroom": classroom, "documents": documents, "weekly_plan": weekly_plan}


@app.post("/api/course/sections/{section_id}/teach", response_model=SectionTeachResponse)
async def teach_course_section(request: Request, section_id: str, payload: SectionTeachRequest) -> SectionTeachResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to open a course subsection.")

    section = await run_in_threadpool(course_content.get_section, section_id)
    classroom: dict[str, Any] | None = None
    generated_from_outcomes = False
    if section:
        class_id = str(section.get("class_id", ""))
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
        )
    elif section_id.startswith("virtual:"):
        parts = section_id.split(":", 2)
        if len(parts) != 3:
            raise HTTPException(status_code=404, detail="The selected course topic was not found.")
        class_id = parts[1]
        try:
            topic_index = int(parts[2])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="The selected course topic was not found.") from exc
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
        )
        if classroom:
            topics = [str(item) for item in classroom.get("weekly_topics", []) if str(item).strip()]
            if not topics:
                topics = [str(item) for item in classroom.get("learning_outcomes", []) if str(item).strip()]
            if topic_index < 0 or topic_index >= len(topics):
                raise HTTPException(status_code=404, detail="The selected course topic was not found.")
            topic_title = topics[topic_index]
            section = {
                "id": section_id, "class_id": class_id, "title": topic_title,
                "section_path": topic_title, "content": "",
                "document_title": "Course profile and expected outcomes",
                "filename": "Lecturer course outline and objectives",
                "document_type": "course_outline",
                "objectives": list(classroom.get("learning_outcomes", [])),
                "recommended_readings": list(classroom.get("recommended_readings", [])),
            }
            generated_from_outcomes = True
    else:
        raise HTTPException(status_code=404, detail="The selected course subsection was not found.")

    if not classroom or not section:
        raise HTTPException(status_code=403, detail="You do not have access to this course subsection.")

    class_id = str(section.get("class_id", ""))
    selected_text = str(section.get("content", "")).strip()
    section_path = str(section.get("section_path") or section.get("title") or "Course topic")
    course_name = str(classroom.get("subject") or classroom.get("name") or "Course")
    objectives = [str(item) for item in classroom.get("learning_outcomes", []) if str(item).strip()]
    expected_topics = [str(item) for item in classroom.get("weekly_topics", []) if str(item).strip()]
    listed_readings = [str(item) for item in classroom.get("recommended_readings", []) if str(item).strip()]

    related_context, related_sources = await run_in_threadpool(
        _course_context,
        " ".join([course_name, section_path, *objectives[:8]]),
        class_id=class_id,
        knowledge_mode=str(classroom.get("knowledge_mode") or "course_only"),
    )
    reading_context, reading_sources = await run_in_threadpool(course_content.recommended_context, class_id)
    if not selected_text and not related_context:
        generated_from_outcomes = True

    sources: list[str] = []
    if selected_text and section.get("filename"):
        sources.append(str(section.get("filename")))
    sources.extend(str(item) for item in related_sources if item)
    sources.extend(str(item) for item in reading_sources if item)
    if not sources:
        sources.append("Lecturer course objectives, expected outcomes and weekly plan")
    sources = list(dict.fromkeys(sources))

    objectives_text = "\n".join(f"- {item}" for item in objectives)
    weekly_text = "\n".join(f"- {item}" for item in expected_topics)
    reading_list_text = "\n".join(f"- {item}" for item in listed_readings)
    prompt = (
        f"COURSE\n{course_name}\n\n"
        f"SELECTED TOPIC OR SUBSECTION\n{section_path}\n\n"
        f"COURSE LEARNING OBJECTIVES AND EXPECTED OUTCOMES\n{objectives_text or 'No objectives were listed.'}\n\n"
        f"WEEK-BY-WEEK COURSE PLAN\n{weekly_text or 'No weekly plan was listed.'}\n\n"
        f"LECTURER TEACHING TEXT FOR THE SELECTED SECTION\n{selected_text[:50000] or 'No lecturer teaching note was uploaded for this section.'}\n\n"
        f"RELATED APPROVED COURSE EXTRACTS\n{related_context[:26000] or 'No additional approved teaching extract was found.'}\n\n"
        f"RECOMMENDED READING LIST\n{reading_list_text or 'No reading list was uploaded.'}\n\n"
        f"APPROVED READING EXTRACTS\n{reading_context[:20000] or 'No recommended reading extract was uploaded.'}\n\n"
        f"LECTURER INSTRUCTIONS\n{classroom.get('tutor_instructions') or 'No additional instructions.'}\n\n"
        "AUTHORISATION FOR INSTRUCTIONAL EXPANSION\n"
        "When teaching notes or readings are absent or too brief, construct complete teaching notes from the listed topic, objectives and expected outcomes. "
        "Develop any additional subtopics needed for full understanding, while avoiding invented quotations, sources or claims attributed to the lecturer."
    )

    if settings.demo_mode:
        seed = selected_text or related_context or "\n".join([section_path, *objectives])
        plan = _demo_section_plan(str(section.get("title", "Course subsection")), seed)
    else:
        _require_text_ai()
        try:
            result = await run_in_threadpool(
                ai_router.generate_structured,
                schema=SectionLessonPlan,
                instructions=section_lesson_instructions(
                    level=payload.level, course=course_name, detail=payload.detail
                ),
                prompt=prompt,
                task="course_section_lesson",
                max_tokens=max(settings.deepseek_max_tokens, 10000),
                prefer_deepseek=True,
            )
            plan = result.value if isinstance(result.value, SectionLessonPlan) else SectionLessonPlan.model_validate(result.value)
            _record_usage(user, result, "course_section_lesson")
        except Exception as exc:
            logger.exception("Course subsection lesson generation failed")
            raise HTTPException(
                status_code=502, detail=f"Course subsection lesson error: {type(exc).__name__}"
            ) from exc

    if not payload.include_worked_examples:
        for block in plan.detailed_notes:
            block.example = ""
        for slide in plan.slides:
            slide.worked_example = ""
    if not payload.include_self_check:
        plan.self_check_questions = []
        for slide in plan.slides:
            slide.check_question = ""

    answer = _section_plan_answer(plan)
    visual = VisualPlan(
        kind="slides",
        title=plan.title,
        caption=(
            "Complete teaching slides aligned with the detailed notes. Each slide includes the explanation and narration needed to learn directly from the whiteboard."
        ),
        slides=plan.slides,
    )
    try:
        await run_in_threadpool(
            accounts.record_learning_event,
            user_id=str(user["id"]),
            class_id=class_id,
            event_type="course_section_opened",
            topic=section_path,
            metadata={
                "section_id": section_id,
                "document": section.get("filename", ""),
                "detail": payload.detail,
                "generated_from_outcomes": generated_from_outcomes,
            },
        )
    except Exception:
        logger.exception("Course subsection activity could not be recorded")

    response_mode = str(classroom.get("practice_response_mode") or ("whiteboard" if classroom.get("practice_whiteboard_required") else "student_choice"))
    return SectionTeachResponse(
        section_id=section_id,
        section_title=str(section.get("title", "Course subsection")),
        section_path=section_path,
        answer=answer,
        sources=sources,
        visual=visual,
        practice_whiteboard_required=response_mode == "whiteboard",
        practice_response_mode=response_mode,
        generated_from_outcomes=generated_from_outcomes,
    )


@app.get("/api/materials")
async def list_materials(request: Request, class_id: str = "") -> dict[str, Any]:
    class_id = class_id.strip()
    user = _optional_user(request)
    if class_id:
        if not user:
            raise HTTPException(status_code=401, detail="Sign in to view course materials.")
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
        )
        if not classroom:
            raise HTTPException(status_code=403, detail="You do not have access to this class.")
        materials = await run_in_threadpool(
            knowledge.list_sources, class_id=class_id, include_global=False
        )
        documents = await run_in_threadpool(course_content.list_structure, class_id)
        return {"materials": materials, "documents": documents}

    # Institution-wide administrator uploads are private to administrators. They are
    # never mixed into a lecturer's course or a student's enrolled-course library.
    if user and str(user.get("role")) == "admin":
        materials = await run_in_threadpool(
            knowledge.list_sources, class_id="", include_global=False
        )
        return {"materials": materials, "documents": []}
    return {"materials": [], "documents": []}


@app.get("/api/admin/materials")
async def list_admin_materials(request: Request) -> dict[str, Any]:
    _required_admin(request)
    materials = await run_in_threadpool(knowledge.list_sources, class_id="", include_global=False)
    return {"materials": materials}


@app.delete("/api/admin/materials")
async def delete_admin_material(request: Request, source_id: str) -> dict[str, Any]:
    _required_admin(request)
    source_id = source_id.strip()
    if not source_id:
        raise HTTPException(status_code=422, detail="Select an administrator document to delete.")
    metadata = await run_in_threadpool(knowledge.source_metadata, source_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Administrator document not found. Refresh the repository and try again.")
    if metadata.get("class_id") or metadata.get("repository_scope") != "admin_private":
        raise HTTPException(status_code=403, detail="This document does not belong to the private administrator repository.")
    deleted_chunks = await run_in_threadpool(knowledge.delete_admin_source, source_id)
    if deleted_chunks < 1:
        raise HTTPException(status_code=409, detail="The document could not be removed. Refresh and try again.")
    return {"status": "deleted", "source_id": source_id, "deleted_chunks": deleted_chunks}


@app.post("/api/materials/upload")
async def upload_materials(
    request: Request,
    admin_key: str = Form(default=""),
    class_id: str = Form(default=""),
    material_type: str = Form(default="course"),
    document_type: str = Form(default="teaching_notes"),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    _check_rate_limit(request)
    class_id = class_id.strip()
    document_type = document_type if document_type in DOCUMENT_TYPES else "teaching_notes"
    material_type = "approved_external" if document_type == "recommended_reading" else "course"
    user = _optional_user(request)
    classroom = None
    authorised = False
    if class_id and user and user.get("role") == "teacher":
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role="teacher"
        )
        authorised = bool(classroom)
    elif not class_id:
        authorised = bool(
            (user and str(user.get("role")) == "admin")
            or (settings.admin_key and admin_key == settings.admin_key)
        )
    if not authorised:
        raise HTTPException(
            status_code=401,
            detail="Lecturers can upload documents only to courses they manage. Use the administrator key only for institution-wide material.",
        )
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one course-material file.")

    uploaded: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for file in files[:12]:
        filename = _safe_filename(file.filename or "material")
        try:
            data = await file.read()
            if len(data) > settings.max_material_mb * 1024 * 1024:
                raise ValueError(f"File exceeds {settings.max_material_mb} MB")
            if class_id:
                # Replacing a file with the same name and category must also remove
                # the previous document's indexed chunks. Otherwise stale text can
                # continue to influence the tutor after the visible document is gone.
                existing_documents = await run_in_threadpool(course_content.list_structure, class_id)
                for existing in existing_documents:
                    if str(existing.get("filename")) == filename and str(existing.get("document_type")) == document_type:
                        old_source = f"{class_id}::{document_type}::{existing.get('id', '')}"
                        await run_in_threadpool(knowledge.delete_source, old_source)
                document = await run_in_threadpool(
                    course_content.ingest_document,
                    class_id=class_id,
                    uploader_id=str(user["id"]),
                    filename=filename,
                    document_type=document_type,
                    data=data,
                )
                internal_source = f"{class_id}::{document_type}::{document['id']}"
                all_chunks = []
                chunk_index = 0
                for section_meta in document.get("sections", []):
                    section = await run_in_threadpool(course_content.get_section, section_meta["id"])
                    if not section or not str(section.get("content", "")).strip():
                        continue
                    section_chunks = await run_in_threadpool(
                        make_chunks,
                        str(section["content"]),
                        internal_source,
                        class_id=class_id,
                        material_type=material_type,
                        display_source=f"{filename} • {section.get('section_path') or section.get('title')}",
                        repository_scope="course",
                    )
                    for chunk in section_chunks:
                        chunk.chunk_index = chunk_index
                        chunk_index += 1
                        all_chunks.append(chunk)
                if not all_chunks and document_type == "course_outline":
                    outline_seed = "\n".join([
                        *[str(item.get("title", "")) for item in document.get("sections", [])],
                        *[str(item) for item in document.get("objectives", [])],
                        *[str(item) for item in document.get("weekly_topics", [])],
                        *[str(item) for item in document.get("recommended_readings", [])],
                    ]).strip()
                    if outline_seed:
                        all_chunks = await run_in_threadpool(
                            make_chunks, outline_seed, internal_source, class_id=class_id,
                            material_type=material_type, display_source=filename, repository_scope="course"
                        )
                if not all_chunks:
                    raise ValueError("No readable text was found. A scanned PDF may need OCR before upload.")
                count = await run_in_threadpool(knowledge.replace_source, internal_source, all_chunks)
                if document_type == "course_outline":
                    classroom = await run_in_threadpool(
                        accounts.merge_course_outline,
                        class_id=class_id,
                        teacher_id=str(user["id"]),
                        objectives=document.get("objectives", []),
                        recommended_readings=document.get("recommended_readings", []),
                        weekly_topics=document.get("weekly_topics", []),
                    )
                uploaded.append({
                    "source": filename,
                    "chunks": count,
                    "class_id": class_id,
                    "material_type": material_type,
                    "document_type": document_type,
                    "document_id": document.get("id", ""),
                    "sections": len(document.get("sections", [])),
                    "objectives_found": len(document.get("objectives", [])),
                    "readings_found": len(document.get("recommended_readings", [])),
                    "weekly_topics_found": len(document.get("weekly_topics", [])),
                })
            else:
                text = await run_in_threadpool(extract_text, filename, data)
                internal_source = f"global::{material_type}::{filename}"
                chunks = await run_in_threadpool(
                    make_chunks, text, internal_source, class_id="", material_type=material_type, display_source=filename,
                    repository_scope="admin_private"
                )
                if not chunks:
                    raise ValueError("No readable text was found. A scanned PDF may need OCR before upload.")
                count = await run_in_threadpool(knowledge.replace_source, internal_source, chunks)
                uploaded.append({"source": filename, "chunks": count, "class_id": "", "material_type": material_type})
        except Exception as exc:
            logger.exception("Course document upload failed for %s", filename)
            errors.append({"source": filename, "error": str(exc)})

    materials = await run_in_threadpool(
        knowledge.list_sources, class_id=class_id if class_id else "", include_global=False
    )
    documents = await run_in_threadpool(course_content.list_structure, class_id) if class_id else []
    return {"uploaded": uploaded, "errors": errors, "materials": materials, "documents": documents, "classroom": classroom}


@app.delete("/api/classes/{class_id}/documents/{document_id}")
async def delete_course_document(request: Request, class_id: str, document_id: str) -> dict[str, Any]:
    user = _required_lecturer(request)
    classroom = await run_in_threadpool(
        accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role="teacher"
    )
    if not classroom:
        raise HTTPException(status_code=403, detail="You do not manage this course.")
    document = await run_in_threadpool(course_content.get_document, document_id)
    if not document or str(document.get("class_id")) != class_id:
        raise HTTPException(status_code=404, detail="Course document not found.")
    deleted_chunks = await run_in_threadpool(
        knowledge.delete_course_document_sources,
        class_id=class_id,
        document_id=document_id,
        filename=str(document.get("filename", "")),
        document_type=str(document.get("document_type", "teaching_notes")),
    )
    deleted = await run_in_threadpool(course_content.delete_document, document_id, class_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Course document not found.")
    return {"status": "deleted", "document_id": document_id, "deleted_chunks": deleted_chunks}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str) -> dict[str, bool]:
    sessions.pop(session_id, None)
    return {"cleared": True}
