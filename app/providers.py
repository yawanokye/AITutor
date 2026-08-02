from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]

from app.config import Settings
from app.schemas import VisionAnalysis, VisualAnnotation, VisualPlan

logger = logging.getLogger("ai_tutor.providers")
T = TypeVar("T", bound=BaseModel)


@dataclass
class AIResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class StructuredResult:
    value: BaseModel
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class ProviderError(RuntimeError):
    pass


class AIProviderRouter:
    ADVANCED_PATTERNS = [
        r"\bprove\b", r"\bderive\b", r"\btheorem\b", r"\beigen", r"\blagrang",
        r"\bdifferential equation", r"\bpartial differential", r"\badvanced calculus",
        r"\bstructural equation", r"\bsem\b", r"\bpls-sem", r"\beconometric",
        r"\bbayesian", r"\bmarkov", r"\bstochastic", r"\bportfolio optimisation",
        r"\bmultilevel", r"\bcausal inference", r"\binstrumental variable",
        r"\bdebug\b", r"\bcomplex code", r"\bproof by induction", r"\btensor",
    ]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.openai_client = (
            OpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key and OpenAI is not None
            else None
        )
        self.deepseek_client = (
            OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
            if settings.deepseek_api_key and OpenAI is not None
            else None
        )

    @property
    def text_enabled(self) -> bool:
        return self.settings.text_ai_enabled

    def _usage(self, response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        input_tokens = (
            getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", None)
            or 0
        )
        output_tokens = (
            getattr(usage, "completion_tokens", None)
            or getattr(usage, "output_tokens", None)
            or 0
        )
        return int(input_tokens or 0), int(output_tokens or 0)

    def _deepseek_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if "pro" in model.lower():
            input_price = self.settings.deepseek_pro_input_per_million
            output_price = self.settings.deepseek_pro_output_per_million
        else:
            input_price = self.settings.deepseek_flash_input_per_million
            output_price = self.settings.deepseek_flash_output_per_million
        return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)

    def complexity_score(self, text: str, *, task: str = "tutor") -> int:
        clean = text.lower()
        score = 0
        if len(text) > 2500:
            score += 1
        if len(text) > 6000:
            score += 1
        score += min(4, sum(bool(re.search(pattern, clean)) for pattern in self.ADVANCED_PATTERNS))
        if task in {"advanced_reasoning", "research_methods", "complex_code"}:
            score += 2
        if clean.count("equation") + clean.count("formula") + clean.count("model") >= 4:
            score += 1
        return score

    def choose_deepseek_model(self, text: str, *, task: str = "tutor") -> tuple[str, bool]:
        advanced = (
            self.settings.advanced_routing_enabled
            and self.complexity_score(text, task=task) >= self.settings.advanced_routing_min_score
        )
        model = self.settings.deepseek_advanced_model if advanced else self.settings.deepseek_model
        thinking = self.settings.deepseek_advanced_thinking if advanced else self.settings.deepseek_thinking
        return model, thinking

    @staticmethod
    def _deepseek_messages(instructions: str, history: list[dict[str, str]], prompt: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": instructions}]
        for item in history[-16:]:
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content[:16000]})
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate_text(
        self,
        *,
        instructions: str,
        prompt: str,
        history: list[dict[str, str]] | None = None,
        task: str = "tutor",
        max_tokens: int | None = None,
    ) -> AIResult:
        history = history or []
        errors: list[str] = []

        if self.settings.ai_provider == "deepseek" and self.deepseek_client is not None:
            model, thinking = self.choose_deepseek_model(prompt, task=task)
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": self._deepseek_messages(instructions, history, prompt),
                    "max_tokens": max_tokens or self.settings.deepseek_max_tokens,
                    "extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}},
                }
                response = self.deepseek_client.chat.completions.create(**kwargs)
                text = (response.choices[0].message.content or "").strip()
                if not text:
                    # DeepSeek documentation notes occasional empty JSON/text output. Retry without thinking.
                    kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    response = self.deepseek_client.chat.completions.create(**kwargs)
                    text = (response.choices[0].message.content or "").strip()
                if text:
                    input_tokens, output_tokens = self._usage(response)
                    return AIResult(
                        text=text,
                        provider="deepseek",
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        estimated_cost_usd=self._deepseek_cost(model, input_tokens, output_tokens),
                    )
                errors.append("DeepSeek returned empty content")
            except Exception as exc:
                logger.exception("DeepSeek text generation failed")
                errors.append(f"DeepSeek: {type(exc).__name__}")

        if self.openai_client is not None:
            try:
                input_items: list[dict[str, Any]] = []
                for item in history[-16:]:
                    role = item.get("role", "user")
                    if role in {"user", "assistant"} and item.get("content"):
                        input_items.append({"role": role, "content": str(item["content"])[:16000]})
                input_items.append({"role": "user", "content": prompt})
                response = self.openai_client.responses.create(
                    model=self.settings.ai_model,
                    instructions=instructions,
                    input=input_items,
                    reasoning={"effort": self.settings.ai_reasoning_effort},
                    text={"verbosity": self.settings.ai_verbosity},
                    max_output_tokens=max_tokens or self.settings.max_output_tokens,
                    store=False,
                )
                text = self._extract_openai_text(response)
                if not text:
                    response = self.openai_client.responses.create(
                        model=self.settings.ai_model,
                        instructions=instructions,
                        input=input_items,
                        reasoning={"effort": "none"},
                        max_output_tokens=max(max_tokens or 0, self.settings.max_output_tokens, 8000),
                        store=False,
                    )
                    text = self._extract_openai_text(response)
                if not text:
                    raise ProviderError("OpenAI returned empty content")
                input_tokens, output_tokens = self._usage(response)
                return AIResult(text=text, provider="openai", model=self.settings.ai_model, input_tokens=input_tokens, output_tokens=output_tokens)
            except Exception as exc:
                logger.exception("OpenAI text fallback failed")
                errors.append(f"OpenAI: {type(exc).__name__}")

        raise ProviderError("; ".join(errors) or "No text AI provider is configured")

    def generate_structured(
        self,
        *,
        schema: type[T],
        instructions: str,
        prompt: str,
        task: str,
        max_tokens: int,
        prefer_deepseek: bool = True,
    ) -> StructuredResult:
        errors: list[str] = []
        if prefer_deepseek and self.deepseek_client is not None:
            model, thinking = self.choose_deepseek_model(prompt, task=task)
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            system = (
                f"{instructions}\n\nReturn one valid JSON object only. The JSON must satisfy this schema:\n{schema_json}\n"
                "Do not wrap the JSON in markdown. Use empty arrays or empty strings for fields that do not apply."
            )
            messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            for attempt in range(2):
                try:
                    response = self.deepseek_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        max_tokens=max_tokens,
                        extra_body={"thinking": {"type": "disabled" if attempt or not thinking else "enabled"}},
                    )
                    raw = (response.choices[0].message.content or "").strip()
                    if not raw:
                        continue
                    value = schema.model_validate(json.loads(raw))
                    input_tokens, output_tokens = self._usage(response)
                    return StructuredResult(
                        value=value,
                        provider="deepseek",
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        estimated_cost_usd=self._deepseek_cost(model, input_tokens, output_tokens),
                    )
                except (json.JSONDecodeError, ValidationError) as exc:
                    errors.append(f"DeepSeek JSON attempt {attempt + 1}: {type(exc).__name__}")
                    messages[-1]["content"] = prompt + "\n\nCorrect the JSON and include every required field."
                except Exception as exc:
                    logger.exception("DeepSeek structured generation failed")
                    errors.append(f"DeepSeek: {type(exc).__name__}")
                    break

        if self.openai_client is not None:
            try:
                response = self.openai_client.responses.parse(
                    model=self.settings.ai_model,
                    instructions=instructions,
                    input=[{"role": "user", "content": prompt}],
                    text_format=schema,
                    reasoning={"effort": "low"},
                    max_output_tokens=max_tokens,
                    store=False,
                )
                parsed = getattr(response, "output_parsed", None)
                value = parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
                input_tokens, output_tokens = self._usage(response)
                return StructuredResult(value=value, provider="openai", model=self.settings.ai_model, input_tokens=input_tokens, output_tokens=output_tokens)
            except Exception as exc:
                logger.exception("OpenAI structured fallback failed")
                errors.append(f"OpenAI: {type(exc).__name__}")
        raise ProviderError("; ".join(errors) or "No structured-output provider is configured")

    def analyse_images(
        self,
        *,
        images: list[dict[str, str]],
        question: str,
        level: str,
        course: str,
    ) -> StructuredResult:
        if self.openai_client is None:
            raise ProviderError("OPENAI_API_KEY is required for image and handwriting analysis")
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": (
                f"LEARNER LEVEL\n{level[:80]}\n\nCOURSE\n{course[:160] or 'Not specified'}\n\n"
                f"LEARNER QUESTION\n{question[:8000]}\n\n"
                "Inspect every supplied image. Extract only relevant visible information. Identify likely mistakes and uncertainty. "
                "When a precise region is useful, add a normalised 1000 by 1000 annotation box."
            ),
        }]
        for index, image in enumerate(images, start=1):
            content.append({"type": "input_text", "text": f"IMAGE {index}: {image['label']}"})
            content.append({"type": "input_image", "image_url": image["data_url"], "detail": self._image_detail()})
        response = self.openai_client.responses.parse(
            model=self.settings.vision_model,
            instructions=(
                "You are the visual-analysis layer of an educational tutor. Return a careful structured image analysis. "
                "Do not invent handwriting, values, labels or errors. Use British English."
            ),
            input=[{"role": "user", "content": content}],
            text_format=VisionAnalysis,
            reasoning={"effort": "low"},
            max_output_tokens=3200,
            store=False,
        )
        parsed = getattr(response, "output_parsed", None)
        value = parsed if isinstance(parsed, VisionAnalysis) else VisionAnalysis.model_validate(parsed)
        input_tokens, output_tokens = self._usage(response)
        return StructuredResult(value=value, provider="openai", model=self.settings.vision_model, input_tokens=input_tokens, output_tokens=output_tokens)

    def openai_parse_with_images(
        self,
        *,
        schema: type[T],
        instructions: str,
        text: str,
        images: list[dict[str, str]],
        max_tokens: int,
    ) -> StructuredResult:
        if self.openai_client is None:
            raise ProviderError("OPENAI_API_KEY is required for this image task")
        content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
        for image in images:
            content.append({"type": "input_text", "text": image["label"]})
            content.append({"type": "input_image", "image_url": image["data_url"], "detail": self._image_detail()})
        response = self.openai_client.responses.parse(
            model=self.settings.vision_model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
            text_format=schema,
            reasoning={"effort": "low"},
            max_output_tokens=max_tokens,
            store=False,
        )
        parsed = getattr(response, "output_parsed", None)
        value = parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
        input_tokens, output_tokens = self._usage(response)
        return StructuredResult(value=value, provider="openai", model=self.settings.vision_model, input_tokens=input_tokens, output_tokens=output_tokens)

    def _image_detail(self) -> str:
        value = self.settings.image_detail.strip().lower()
        if value == "original":
            return "high"
        return value if value in {"low", "high", "auto"} else "auto"

    @staticmethod
    def vision_context(analysis: VisionAnalysis) -> str:
        sections = [f"Summary: {analysis.summary}"]
        if analysis.visible_text:
            sections.append("Visible text: " + " | ".join(analysis.visible_text))
        if analysis.observations:
            sections.append("Observations: " + " | ".join(analysis.observations))
        if analysis.possible_errors:
            sections.append("Possible errors: " + " | ".join(analysis.possible_errors))
        if analysis.uncertainties:
            sections.append("Uncertainties: " + " | ".join(analysis.uncertainties))
        return "\n".join(sections)

    @staticmethod
    def inject_image_annotations(plan: VisualPlan, annotations: list[VisualAnnotation], has_image: bool) -> VisualPlan:
        if not has_image or not annotations:
            return plan
        data = plan.model_dump()
        if data.get("kind") in {"none", "steps", "image_annotation"}:
            data["kind"] = "image_annotation"
            data["annotations"] = [item.model_dump() for item in annotations[:8]]
        return VisualPlan.model_validate(data)

    @staticmethod
    def _extract_openai_text(response: Any) -> str:
        direct = getattr(response, "output_text", "") or ""
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "output_text":
                    text = getattr(content, "text", "") or ""
                    if text.strip():
                        parts.append(text.strip())
        return "\n\n".join(parts).strip()
