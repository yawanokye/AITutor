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
from app.prompts import tutor_instructions
from app.schemas import ChatResponse, ConfigResponse, SpeechRequest

logger = logging.getLogger("ai_tutor")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=settings.app_name, version="1.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

knowledge = KnowledgeStore(database_url=settings.database_url, storage_dir=settings.storage_dir)
client = OpenAI(api_key=settings.openai_api_key) if (settings.openai_api_key and OpenAI is not None) else None

# Session history is intentionally short and contains no passwords or API keys.
# For production at scale, replace this with Redis or a database-backed session store.
sessions: dict[str, deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=max(settings.history_turns * 2, 4))
)
rate_buckets: dict[str, deque[float]] = defaultdict(deque)

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
VOICE_OPTIONS = ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]


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

    # Browsers and proxies sometimes replace a valid audio MIME type with a
    # generic binary type. In that case, the recognised filename extension is
    # the only reliable signal available to the application.
    if base_type in {"", "application/octet-stream"} and filename_extension:
        return filename_extension if filename_extension in SUPPORTED_AUDIO_EXTENSIONS else None
    return None


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
    image_data_url: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for turn in history:
        items.append({"role": turn["role"], "content": turn["content"]})

    user_text = (
        f"APPROVED COURSE CONTEXT\n{context}\n\n"
        f"LEARNER QUESTION\n{message.strip()}"
    )
    if image_data_url:
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": user_text},
            {"type": "input_image", "image_url": image_data_url},
        ]
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


def _plain_text_for_speech(text: str) -> str:
    clean = re.sub(r"```.*?```", " Code example omitted from speech. ", text, flags=re.DOTALL)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[Source:[^\]]+\]", "", clean)
    clean = re.sub(r"[#>*_~]", "", clean)
    clean = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:4000]


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Avoid returning secrets, stack traces or provider payloads to the browser.
    return JSONResponse(status_code=500, content={"detail": f"The request could not be completed: {type(exc).__name__}"})


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "openai_enabled": settings.openai_enabled,
        "knowledge_sources": len(knowledge.list_sources()),
        "model": settings.ai_model,
        "reasoning_effort": settings.ai_reasoning_effort,
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
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(default=""),
    level: str = Form(default="University"),
    tutor_mode: str = Form(default="guided"),
    course: str = Form(default=""),
    image: UploadFile | None = File(default=None),
) -> ChatResponse:
    _check_rate_limit(request)
    message = message.strip()
    if not message and image is None:
        raise HTTPException(status_code=422, detail="Enter a question or attach an image.")
    if len(message) > 8000:
        raise HTTPException(status_code=413, detail="The question is too long. Keep it below 8,000 characters.")

    session_id = session_id.strip() or str(uuid.uuid4())
    history = sessions[session_id]

    image_data_url: str | None = None
    if image is not None and image.filename:
        if image.content_type not in SUPPORTED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Use a JPG, PNG, WEBP or GIF image.")
        image_bytes = await image.read()
        if len(image_bytes) > settings.max_image_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Images must be no larger than {settings.max_image_mb} MB.")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        image_data_url = f"data:{image.content_type};base64,{encoded}"

    retrieval_query = " ".join(part for part in [course, message] if part).strip()
    context, sources = await run_in_threadpool(_course_context, retrieval_query)

    if settings.demo_mode:
        answer = _demo_answer(message or "Please explain the attached image.", bool(image_data_url), sources)
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
            message=message or "Please analyse and explain the attached image.",
            context=context,
            image_data_url=image_data_url,
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

            # A reasoning model can consume the output budget before emitting a
            # visible message. Retry once with no reasoning and a larger budget.
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

    history.append({"role": "user", "content": message or "Please explain the attached image."})
    history.append({"role": "assistant", "content": answer})
    return ChatResponse(answer=answer, sources=sources, session_id=session_id, demo=settings.demo_mode)


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
    # Give the transcription service a filename that matches the actual MIME
    # container. This matters on browsers that record MP4/M4A rather than WebM.
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
        # Prompted voice instructions are supported by GPT-4o mini TTS.
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
