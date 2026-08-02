from __future__ import annotations

import base64
import io
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    from openai import OpenAI
except ImportError:  # Allows demo-mode tests before dependencies are installed.
    OpenAI = None  # type: ignore[assignment,misc]

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.knowledge import KnowledgeStore, extract_text, make_chunks
from app.prompts import (
    practice_generation_instructions,
    practice_marking_instructions,
    tutor_instructions,
    visual_plan_instructions,
    work_check_instructions,
)
from app.schemas import (
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

logger = logging.getLogger("ai_tutor")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=settings.app_name, version="2.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

knowledge = KnowledgeStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
client = OpenAI(api_key=settings.openai_api_key) if (settings.openai_api_key and OpenAI is not None) else None

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


def _course_context(query: str) -> tuple[str, list[str]]:
    results = knowledge.retrieve(query, limit=5)
    if not results:
        return "No approved course-material extract was retrieved for this question.", []

    sections = []
    sources: list[str] = []
    for index, result in enumerate(results, start=1):
        sections.append(f"COURSE EXTRACT {index} [Source: {result.source}]\n{result.content}")
        if result.source not in sources:
            sources.append(result.source)
    return "\n\n".join(sections), sources


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
    openai_client: Any,
    question: str,
    answer: str,
    level: str,
    course: str,
    preference: str,
    display_image_data_url: str | None,
) -> VisualPlan | None:
    has_image = bool(display_image_data_url)
    prompt_text = (
        f"LEARNER LEVEL\n{level[:80]}\n\n"
        f"COURSE\n{course[:160] or 'Not specified'}\n\n"
        f"LEARNER QUESTION\n{question[:8000]}\n\n"
        f"TUTOR ANSWER\n{answer[:16000]}"
    )
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt_text}]
    if display_image_data_url:
        content.append(
            {
                "type": "input_image",
                "image_url": display_image_data_url,
                "detail": _image_detail(),
            }
        )

    response = openai_client.responses.parse(
        model=settings.ai_model,
        instructions=visual_plan_instructions(has_image=has_image, preference=preference),
        input=[{"role": "user", "content": content}],
        text_format=VisualPlan,
        reasoning={"effort": "low"},
        max_output_tokens=settings.visual_max_output_tokens,
        store=False,
    )
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, VisualPlan):
        return _normalise_visual_plan(parsed, has_image=has_image)
    if isinstance(parsed, dict):
        return _normalise_visual_plan(VisualPlan.model_validate(parsed), has_image=has_image)
    return None


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
        "openai_enabled": settings.openai_enabled,
        "knowledge_sources": len(knowledge.list_sources()),
        "model": settings.ai_model,
        "reasoning_effort": settings.ai_reasoning_effort,
        "visual_plan_enabled": settings.visual_plan_enabled,
        "image_detail": _image_detail(),
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
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(default=""),
    level: str = Form(default="University"),
    tutor_mode: str = Form(default="guided"),
    course: str = Form(default=""),
    visual_requested: bool = Form(default=True),
    visual_preference: str = Form(default="auto"),
    board_context: str = Form(default=""),
    image: UploadFile | None = File(default=None),
    board_image: UploadFile | None = File(default=None),
) -> ChatResponse:
    _check_rate_limit(request)
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
    display_image_data_url = (
        learner_image["data_url"] if learner_image else whiteboard_image["data_url"] if whiteboard_image else None
    )

    effective_message = message or (
        "Please explain the part I marked on the whiteboard."
        if whiteboard_image
        else "Please analyse and explain the attached image."
    )
    retrieval_query = " ".join(part for part in [course, effective_message] if part).strip()
    context, sources = await run_in_threadpool(_course_context, retrieval_query)

    visual: VisualPlan | None = None
    if settings.demo_mode:
        answer = _demo_answer(effective_message, bool(images), sources)
        if settings.visual_plan_enabled and visual_requested:
            visual = _demo_visual(effective_message, bool(display_image_data_url))
    else:
        openai_client = _require_openai()
        instructions = tutor_instructions(
            app_name=settings.app_name,
            level=level[:80],
            tutor_mode=tutor_mode[:40],
            course=course[:160],
            allow_general_knowledge=settings.allow_general_knowledge,
        )
        input_items = _response_input(
            history=history,
            message=effective_message,
            context=context,
            images=images,
            board_context=board_context,
        )

        def create_response(*, effort: str, token_budget: int):
            return openai_client.responses.create(
                model=settings.ai_model,
                instructions=instructions,
                input=input_items,
                reasoning={"effort": effort},
                text={"verbosity": settings.ai_verbosity},
                max_output_tokens=token_budget,
                store=False,
            )

        try:
            ai_response = await run_in_threadpool(
                create_response,
                effort=settings.ai_reasoning_effort,
                token_budget=settings.max_output_tokens,
            )
            answer = _extract_response_text(ai_response)

            if not answer:
                diagnostic = _response_diagnostic(ai_response)
                logger.warning("Empty AI response on first attempt: %s", diagnostic)
                ai_response = await run_in_threadpool(
                    create_response,
                    effort="none",
                    token_budget=max(settings.max_output_tokens, 8000),
                )
                answer = _extract_response_text(ai_response)
        except Exception as exc:
            logger.exception("AI request failed")
            raise HTTPException(status_code=502, detail=f"AI service error: {type(exc).__name__}") from exc
        if not answer:
            diagnostic = _response_diagnostic(ai_response)
            logger.error("AI response remained empty after retry: %s", diagnostic)
            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI model used its response budget without producing visible text. "
                    "Please try again with a shorter request."
                ),
            )

        if settings.visual_plan_enabled and visual_requested:
            try:
                visual = await run_in_threadpool(
                    _create_visual_plan,
                    openai_client=openai_client,
                    question=effective_message,
                    answer=answer,
                    level=level,
                    course=course,
                    preference=visual_preference,
                    display_image_data_url=display_image_data_url,
                )
            except Exception:
                # The written answer remains useful when the optional visual planner fails.
                logger.exception("Visual plan generation failed")
                visual = None

    history.append({"role": "user", "content": effective_message})
    history.append({"role": "assistant", "content": answer})
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
    question_count: int = Form(default=4),
) -> PracticeQuestionResponse:
    _check_rate_limit(request)
    topic = topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="Enter a topic for guided practice.")
    count = max(2, min(int(question_count), 6))
    context, _ = await run_in_threadpool(_course_context, " ".join([course, topic]).strip())

    if settings.demo_mode:
        activity = _demo_practice(topic)
    else:
        openai_client = _require_openai()
        prompt = (
            f"APPROVED COURSE CONTEXT\n{context}\n\n"
            f"PRACTICE TOPIC\n{topic}\n\n"
            "Create the activity now."
        )

        def create_activity():
            return openai_client.responses.parse(
                model=settings.ai_model,
                instructions=practice_generation_instructions(level=level[:80], course=course[:160], count=count),
                input=[{"role": "user", "content": prompt}],
                text_format=PracticeActivity,
                reasoning={"effort": "low"},
                max_output_tokens=max(settings.visual_max_output_tokens, 5000),
                store=False,
            )

        try:
            response = await run_in_threadpool(create_activity)
            parsed = getattr(response, "output_parsed", None)
            if isinstance(parsed, PracticeActivity):
                activity = parsed
            elif isinstance(parsed, dict):
                activity = PracticeActivity.model_validate(parsed)
            else:
                raise ValueError("The model did not return a practice activity.")
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
    }
    return _practice_public_question(practice_id, practice_sessions[practice_id])


@app.post("/api/practice/check", response_model=PracticeCheckResponse)
async def check_practice_answer(
    request: Request,
    practice_id: str = Form(...),
    answer: str = Form(default=""),
    board_image: UploadFile | None = File(default=None),
) -> PracticeCheckResponse:
    _check_rate_limit(request)
    state = practice_sessions.get(practice_id)
    if state is None:
        raise HTTPException(status_code=404, detail="This practice session has expired. Start a new activity.")
    activity: PracticeActivity = state["activity"]
    index = int(state["index"])
    if index >= len(activity.questions):
        return PracticeCheckResponse(
            correct=True,
            score_awarded=0,
            total_score=int(state.get("total_score", 0)),
            feedback="Practice is already complete.",
            attempts=0,
            completed=True,
        )
    question = activity.questions[index]
    answer = answer.strip()
    board = await _read_image(board_image, label="Learner's practice working on the whiteboard")
    if not answer and not board:
        raise HTTPException(status_code=422, detail="Enter an answer or attach your whiteboard working.")

    attempts = int(state["attempts"].get(question.id, 0)) + 1
    state["attempts"][question.id] = attempts

    if settings.demo_mode:
        normalised_answer = re.sub(r"\s+", " ", answer.lower()).strip()
        expected_terms = [term for term in re.findall(r"[a-zA-Z]{4,}", question.expected_answer.lower()) if term not in {"clear", "correct", "answer", "explanation"}]
        overlap = sum(term in normalised_answer for term in expected_terms[:8])
        correct = bool(normalised_answer) and (overlap >= max(1, min(2, len(expected_terms))))
        evaluation = PracticeEvaluation(
            correct=correct,
            score=80 if correct else 35,
            feedback="Your answer captures the main idea." if correct else "Your answer needs a clearer link to the key idea.",
            misconception="" if correct else "The response is too general.",
            next_hint="" if correct else question.hint,
        )
    else:
        openai_client = _require_openai()
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": (
                f"QUESTION\n{question.prompt}\n\n"
                f"EXPECTED ANSWER\n{question.expected_answer}\n\n"
                f"ACCEPTED VARIANTS\n{'; '.join(question.accepted_variants)}\n\n"
                f"MARKING GUIDE\n{question.marking_guide}\n\n"
                f"LEARNER ANSWER\n{answer or '[supplied as whiteboard image]'}"
            ),
        }]
        if board:
            content.append({"type": "input_image", "image_url": board["data_url"], "detail": _image_detail()})

        def create_evaluation():
            return openai_client.responses.parse(
                model=settings.ai_model,
                instructions=practice_marking_instructions(level="learner"),
                input=[{"role": "user", "content": content}],
                text_format=PracticeEvaluation,
                reasoning={"effort": "low"},
                max_output_tokens=1800,
                store=False,
            )

        try:
            response = await run_in_threadpool(create_evaluation)
            parsed = getattr(response, "output_parsed", None)
            evaluation = parsed if isinstance(parsed, PracticeEvaluation) else PracticeEvaluation.model_validate(parsed)
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

    return PracticeCheckResponse(
        correct=evaluation.correct,
        score_awarded=score_awarded if evaluation.correct else 0,
        total_score=int(state.get("total_score", 0)),
        feedback=evaluation.feedback,
        hint=evaluation.next_hint or (question.hint if not evaluation.correct and attempts >= 1 else ""),
        attempts=attempts,
        completed=completed,
        next_question=next_question,
    )


@app.post("/api/practice/reveal", response_model=PracticeRevealResponse)
async def reveal_practice_solution(
    request: Request,
    practice_id: str = Form(...),
) -> PracticeRevealResponse:
    _check_rate_limit(request)
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
    return PracticeRevealResponse(
        explanation=question.explanation,
        expected_answer=question.expected_answer,
        completed=completed,
        next_question=next_question,
    )


@app.post("/api/work/check", response_model=WorkCheckResponse)
async def check_whiteboard_work(
    request: Request,
    problem_context: str = Form(default=""),
    board_context: str = Form(default=""),
    level: str = Form(default="University"),
    course: str = Form(default=""),
    board_image: UploadFile = File(...),
) -> WorkCheckResponse:
    _check_rate_limit(request)
    board = await _read_image(board_image, label="Learner's current whiteboard working")
    if board is None:
        raise HTTPException(status_code=422, detail="Attach the whiteboard before checking the work.")
    problem_context = problem_context.strip()[:8000]
    board_context = board_context.strip()[:12000]

    if settings.demo_mode:
        result = WorkCheck(
            verdict="partly_correct",
            score=60,
            summary="The board was received. Live mode will inspect each visible step and mark exact regions.",
            strengths=["The learner has shown working rather than only a final answer."],
            corrections=["Enable the API key for detailed mathematical and handwriting analysis."],
            next_step="State the problem above the working, then use Check my work again.",
            annotations=[],
        )
    else:
        openai_client = _require_openai()
        content = [
            {
                "type": "input_text",
                "text": (
                    f"PROBLEM OR QUESTION CONTEXT\n{problem_context or 'Not supplied'}\n\n"
                    f"WHITEBOARD STRUCTURE\n{board_context or 'Not supplied'}\n\n"
                    "Inspect the image and return the work check."
                ),
            },
            {"type": "input_image", "image_url": board["data_url"], "detail": _image_detail()},
        ]

        def create_work_check():
            return openai_client.responses.parse(
                model=settings.ai_model,
                instructions=work_check_instructions(level=level[:80], course=course[:160]),
                input=[{"role": "user", "content": content}],
                text_format=WorkCheck,
                reasoning={"effort": "low"},
                max_output_tokens=2600,
                store=False,
            )

        try:
            response = await run_in_threadpool(create_work_check)
            parsed = getattr(response, "output_parsed", None)
            result = parsed if isinstance(parsed, WorkCheck) else WorkCheck.model_validate(parsed)
        except Exception as exc:
            logger.exception("Whiteboard work check failed")
            raise HTTPException(status_code=502, detail=f"Work-check error: {type(exc).__name__}") from exc

    visual = VisualPlan(
        kind="image_annotation" if result.annotations else "steps",
        title="Tutor check of your working",
        caption=result.summary,
        steps=[
            {"title": "What is working", "explanation": item, "equation": "", "narration": item}
            for item in result.strengths[:3]
        ] + [
            {"title": "Correction", "explanation": item, "equation": "", "narration": item}
            for item in result.corrections[:4]
        ] + ([{"title": "Next step", "explanation": result.next_step, "equation": "", "narration": result.next_step}] if result.next_step else []),
        annotations=result.annotations,
    )
    visual = _normalise_visual_plan(visual, has_image=True)
    return WorkCheckResponse(**result.model_dump(), visual=visual)


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict[str, str]:
    _check_rate_limit(request)
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


@app.get("/api/materials")
async def list_materials() -> dict[str, Any]:
    return {"materials": await run_in_threadpool(knowledge.list_sources)}


@app.post("/api/materials/upload")
async def upload_materials(
    request: Request,
    admin_key: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    _check_rate_limit(request)
    if not settings.admin_key or admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="Invalid administrator key.")
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one course-material file.")

    uploaded: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for file in files[:10]:
        filename = _safe_filename(file.filename or "material")
        try:
            data = await file.read()
            if len(data) > settings.max_material_mb * 1024 * 1024:
                raise ValueError(f"File exceeds {settings.max_material_mb} MB")
            text = await run_in_threadpool(extract_text, filename, data)
            chunks = await run_in_threadpool(make_chunks, text, filename)
            if not chunks:
                raise ValueError("No readable text was found. A scanned PDF may need OCR before upload.")
            count = await run_in_threadpool(knowledge.replace_source, filename, chunks)
            uploaded.append({"source": filename, "chunks": count})
        except Exception as exc:
            errors.append({"source": filename, "error": str(exc)})

    return {"uploaded": uploaded, "errors": errors, "materials": await run_in_threadpool(knowledge.list_sources)}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str) -> dict[str, bool]:
    sessions.pop(session_id, None)
    return {"cleared": True}
