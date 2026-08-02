from __future__ import annotations

import base64
import io
import json
import html
import logging
import re
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
from app.prompts import (
    lesson_video_instructions,
    practice_generation_instructions,
    practice_marking_instructions,
    tutor_instructions,
    visual_plan_instructions,
    work_check_instructions,
)
from app.schemas import (
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
    RegisterRequest,
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

app = FastAPI(title=settings.app_name, version="4.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

knowledge = KnowledgeStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
accounts = AccountStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
auth = AuthManager(secret=settings.auth_secret, access_token_minutes=settings.access_token_minutes)
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
    return user


def _required_teacher(request: Request) -> dict[str, Any]:
    user = _required_user(request)
    if user.get("role") not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="A teacher account is required.")
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
        include_global=True,
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
        )
    question = activity.questions[index]
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
                instructions=practice_generation_instructions(level=level[:80], course=course[:160], count=count),
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
    practice_id = str(uuid.uuid4())
    practice_sessions[practice_id] = {
        "activity": activity,
        "index": 0,
        "attempts": {},
        "total_score": 0,
        "created_at": time.time(),
        "user_id": str(user["id"]) if user else "",
        "topic": topic,
        "course": course,
        "class_id": str(learning["class_id"]),
        "learning_outcome": str(learning["learning_outcome"]),
        "weekly_topic": str(learning["weekly_topic"]),
        "knowledge_mode": str(learning["knowledge_mode"]),
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


@app.post("/api/practice/check", response_model=PracticeCheckResponse)
async def check_practice_answer(
    request: Request,
    practice_id: str = Form(...),
    answer: str = Form(default=""),
    board_image: UploadFile | None = File(default=None),
) -> PracticeCheckResponse:
    _check_rate_limit(request)
    user = _ai_user(request)
    state = practice_sessions.get(practice_id)
    if state is None:
        raise HTTPException(status_code=404, detail="This practice session has expired. Start a new activity.")
    activity: PracticeActivity = state["activity"]
    index = int(state["index"])
    if index >= len(activity.questions):
        return PracticeCheckResponse(correct=True, score_awarded=0, total_score=int(state.get("total_score", 0)), feedback="Practice is already complete.", attempts=0, completed=True)
    question = activity.questions[index]
    answer = answer.strip()
    board = await _read_image(board_image, label="Learner's practice working on the whiteboard")
    if not answer and not board:
        raise HTTPException(status_code=422, detail="Enter an answer or attach your whiteboard working.")
    attempts = int(state["attempts"].get(question.id, 0)) + 1
    state["attempts"][question.id] = attempts
    marking_text = (
        f"QUESTION\n{question.prompt}\n\nEXPECTED ANSWER\n{question.expected_answer}\n\n"
        f"ACCEPTED VARIANTS\n{'; '.join(question.accepted_variants)}\n\n"
        f"MARKING GUIDE\n{question.marking_guide}\n\nLEARNER ANSWER\n{answer or '[supplied as whiteboard image]'}"
    )
    if settings.demo_mode:
        normalised_answer = re.sub(r"\s+", " ", answer.lower()).strip()
        terms = [t for t in re.findall(r"[a-zA-Z]{4,}", question.expected_answer.lower()) if t not in {"clear", "correct", "answer", "explanation"}]
        overlap = sum(term in normalised_answer for term in terms[:8])
        correct = bool(normalised_answer) and overlap >= max(1, min(2, len(terms)))
        evaluation = PracticeEvaluation(correct=correct, score=80 if correct else 35, feedback="Your answer captures the main idea." if correct else "Your answer needs a clearer link to the key idea.", next_hint="" if correct else question.hint)
    else:
        try:
            if board:
                result = await run_in_threadpool(ai_router.openai_parse_with_images, schema=PracticeEvaluation, instructions=practice_marking_instructions(level="learner"), text=marking_text, images=[board], max_tokens=1800)
            else:
                _require_text_ai()
                result = await run_in_threadpool(ai_router.generate_structured, schema=PracticeEvaluation, instructions=practice_marking_instructions(level="learner"), prompt=marking_text, task="practice_marking", max_tokens=1800, prefer_deepseek=True)
            evaluation = result.value if isinstance(result.value, PracticeEvaluation) else PracticeEvaluation.model_validate(result.value)
            _record_usage(user, result, "practice_marking")
        except Exception as exc:
            logger.exception("Practice marking failed")
            raise HTTPException(status_code=502, detail=f"Practice marking error: {type(exc).__name__}") from exc
    score_awarded = int(round(evaluation.score / len(activity.questions)))
    next_question = None
    completed = False
    if evaluation.correct:
        state["total_score"] = min(100, int(state.get("total_score", 0)) + score_awarded)
        state["index"] = index + 1
        completed = state["index"] >= len(activity.questions)
        if not completed:
            next_question = _practice_public_question(practice_id, state)
    if user:
        try:
            event_meta = {
                "correct": evaluation.correct, "attempts": attempts, "question_id": question.id,
                "used_whiteboard": bool(board), "misconception": evaluation.misconception,
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
    return PracticeCheckResponse(correct=evaluation.correct, score_awarded=score_awarded if evaluation.correct else 0, total_score=int(state.get("total_score", 0)), feedback=evaluation.feedback, hint=evaluation.next_hint or (question.hint if not evaluation.correct else ""), attempts=attempts, completed=completed, next_question=next_question)


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


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict[str, str]:
    _check_rate_limit(request)
    _ai_user(request)
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
    return {"text": text.strip()}


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
        }
        if settings.tts_model.startswith("gpt-4o-mini-tts"):
            kwargs["instructions"] = "Speak as a calm, warm and patient tutor at a moderate pace."
        result = openai_client.audio.speech.create(**kwargs)
        return result.read()

    try:
        audio_bytes = await run_in_threadpool(create_speech)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Speech service error: {type(exc).__name__}") from exc
    return Response(content=audio_bytes, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


# Account, class, dashboard and reusable lesson endpoints

@app.post("/api/auth/register", response_model=AuthResponse)
async def register_account(payload: RegisterRequest) -> AuthResponse:
    if payload.role == "student" and not settings.allow_student_registration:
        raise HTTPException(status_code=403, detail="Student registration is currently closed.")
    if payload.role == "teacher":
        valid_teacher_code = bool(settings.teacher_invite_code) and payload.teacher_invite_code == settings.teacher_invite_code
        valid_admin_code = bool(settings.admin_key) and payload.teacher_invite_code == settings.admin_key
        if not (valid_teacher_code or valid_admin_code):
            raise HTTPException(status_code=403, detail="A valid teacher invitation code is required.")
    try:
        password_hash = await run_in_threadpool(auth.hash_password, payload.password)
        user = await run_in_threadpool(
            accounts.create_user,
            email=payload.email,
            password_hash=password_hash,
            display_name=payload.display_name,
            role=payload.role,
        )
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthResponse(access_token=auth.issue_token(user), user=UserPublic(**accounts.public_user(user)))


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_account(payload: LoginRequest) -> AuthResponse:
    user = await run_in_threadpool(accounts.get_user_by_email, payload.email)
    if not user or not auth.verify_password(payload.password, str(user.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="Incorrect email address or password.")
    await run_in_threadpool(accounts.touch_login, str(user["id"]))
    return AuthResponse(access_token=auth.issue_token(user), user=UserPublic(**accounts.public_user(user)))


@app.get("/api/auth/me", response_model=UserPublic)
async def current_account(request: Request) -> UserPublic:
    return UserPublic(**accounts.public_user(_required_user(request)))


@app.get("/api/classes", response_model=list[ClassPublic])
async def list_classes(request: Request) -> list[ClassPublic]:
    user = _required_user(request)
    rows = await run_in_threadpool(accounts.classes_for_user, str(user["id"]), str(user["role"]))
    return [ClassPublic(**row) for row in rows]


@app.post("/api/classes", response_model=ClassPublic)
async def create_class(request: Request, payload: ClassCreateRequest) -> ClassPublic:
    user = _required_teacher(request)
    row = await run_in_threadpool(
        accounts.create_class,
        teacher_id=str(user["id"]),
        name=payload.name,
        subject=payload.subject,
        knowledge_mode=payload.knowledge_mode,
        learning_outcomes=payload.learning_outcomes,
        weekly_topics=payload.weekly_topics,
        tutor_instructions=payload.tutor_instructions,
    )
    return ClassPublic(**row)


@app.patch("/api/classes/{class_id}/profile", response_model=ClassPublic)
async def update_class_profile(request: Request, class_id: str, payload: ClassProfileUpdateRequest) -> ClassPublic:
    user = _required_teacher(request)
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
            tutor_instructions=payload.tutor_instructions,
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
    slides = visual.get("slides") or [{"title": job.get("title", "Lesson"), "bullets": [job.get("topic", "")], "equation": ""}]
    slides_json = json.dumps(slides, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html.escape(str(job.get("title", "Lesson")))
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{safe_title}</title><style>html,body{{margin:0;height:100%;font-family:Arial,sans-serif;background:#eef6f3;color:#123}}"
        "body{display:grid;place-items:center}.slide{width:88vw;height:76vh;background:white;border-radius:28px;padding:5vw;box-shadow:0 20px 60px #1233;display:flex;flex-direction:column;justify-content:center}"
        "h1{font-size:4.5vw;margin:0 0 2vw;color:#0b5d4b}li{font-size:2.25vw;margin:1vw 0;line-height:1.35}.eq{font-size:3vw;margin-top:2vw;text-align:center;background:#f4f0df;padding:1.5vw;border-radius:16px}.counter{position:fixed;right:4vw;bottom:3vw;font-size:1.3vw}</style></head>"
        "<body><main class='slide'><h1 id='title'></h1><ul id='bullets'></ul><div id='eq' class='eq'></div></main><div id='counter' class='counter'></div>"
        f"<script>const slides={slides_json};let i=0;function esc(x){{return String(x).replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}function show(){{const s=slides[i]||{{}};document.getElementById('title').textContent=s.title||'';document.getElementById('bullets').innerHTML=(s.bullets||[]).map(x=>'<li>'+esc(x)+'</li>').join('');const e=document.getElementById('eq');e.textContent=s.equation||'';e.style.display=s.equation?'block':'none';document.getElementById('counter').textContent=(i+1)+' / '+slides.length}}show();setInterval(()=>{{i=(i+1)%slides.length;show()}},9000);</script></body></html>"
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/api/materials")
async def list_materials(request: Request, class_id: str = "") -> dict[str, Any]:
    class_id = class_id.strip()
    if class_id:
        user = _required_user(request)
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
        )
        if not classroom:
            raise HTTPException(status_code=403, detail="You do not have access to this class.")
    materials = await run_in_threadpool(
        knowledge.list_sources, class_id=class_id if class_id else None, include_global=True
    )
    return {"materials": materials}


@app.post("/api/materials/upload")
async def upload_materials(
    request: Request,
    admin_key: str = Form(default=""),
    class_id: str = Form(default=""),
    material_type: str = Form(default="course"),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    _check_rate_limit(request)
    class_id = class_id.strip()
    material_type = material_type if material_type in {"course", "approved_external"} else "course"
    user = _optional_user(request)
    authorised = False
    if class_id and user:
        classroom = await run_in_threadpool(
            accounts.class_for_user, class_id=class_id, user_id=str(user["id"]), role=str(user["role"])
        )
        authorised = bool(classroom and user.get("role") in {"teacher", "admin"})
    elif not class_id:
        authorised = bool(settings.admin_key and admin_key == settings.admin_key)
    if not authorised:
        raise HTTPException(
            status_code=401,
            detail="A teacher account is required for class materials, or use the administrator key for global materials.",
        )
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one course-material file.")

    uploaded: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for file in files[:10]:
        filename = _safe_filename(file.filename or "material")
        internal_source = f"{class_id or 'global'}::{material_type}::{filename}"
        try:
            data = await file.read()
            if len(data) > settings.max_material_mb * 1024 * 1024:
                raise ValueError(f"File exceeds {settings.max_material_mb} MB")
            text = await run_in_threadpool(extract_text, filename, data)
            chunks = await run_in_threadpool(
                make_chunks, text, internal_source, class_id=class_id, material_type=material_type, display_source=filename
            )
            if not chunks:
                raise ValueError("No readable text was found. A scanned PDF may need OCR before upload.")
            count = await run_in_threadpool(knowledge.replace_source, internal_source, chunks)
            uploaded.append({
                "source": filename, "chunks": count, "class_id": class_id, "material_type": material_type
            })
        except Exception as exc:
            errors.append({"source": filename, "error": str(exc)})

    materials = await run_in_threadpool(
        knowledge.list_sources, class_id=class_id if class_id else None, include_global=True
    )
    return {"uploaded": uploaded, "errors": errors, "materials": materials}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str) -> dict[str, bool]:
    sessions.pop(session_id, None)
    return {"cleared": True}
