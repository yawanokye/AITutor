from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    voice: str = Field(default="nova", min_length=2, max_length=32)


class VisualStep(BaseModel):
    title: str = Field(default="", max_length=120)
    explanation: str = Field(default="", max_length=700)
    equation: str = Field(default="", max_length=500)


class VisualPoint(BaseModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    label: str = Field(default="", max_length=80)


class VisualSeries(BaseModel):
    name: str = Field(default="Series", max_length=100)
    points: list[VisualPoint] = Field(default_factory=list, max_length=40)


class VisualAnnotation(BaseModel):
    label: str = Field(default="", max_length=140)
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    width: float = Field(ge=1, le=1000)
    height: float = Field(ge=1, le=1000)


class DiagramNode(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    label: str = Field(default="", max_length=140)
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    shape: Literal["box", "circle", "pill"] = "box"


class DiagramEdge(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    label: str = Field(default="", max_length=100)


class VisualSlide(BaseModel):
    title: str = Field(default="", max_length=140)
    bullets: list[str] = Field(default_factory=list, max_length=7)
    equation: str = Field(default="", max_length=500)
    speaker_note: str = Field(default="", max_length=500)

    @field_validator("bullets", mode="after")
    @classmethod
    def trim_bullets(cls, values: list[str]) -> list[str]:
        return [str(value)[:300] for value in values]


class VisualPlan(BaseModel):
    kind: Literal[
        "none",
        "steps",
        "graph",
        "table",
        "diagram",
        "image_annotation",
        "slides",
    ] = "none"
    title: str = Field(default="", max_length=160)
    caption: str = Field(default="", max_length=700)
    steps: list[VisualStep] = Field(default_factory=list, max_length=8)
    equations: list[str] = Field(default_factory=list, max_length=8)
    x_label: str = Field(default="x", max_length=80)
    y_label: str = Field(default="y", max_length=80)
    series: list[VisualSeries] = Field(default_factory=list, max_length=5)
    table_headers: list[str] = Field(default_factory=list, max_length=8)
    table_rows: list[list[str]] = Field(default_factory=list, max_length=12)
    nodes: list[DiagramNode] = Field(default_factory=list, max_length=12)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=20)
    annotations: list[VisualAnnotation] = Field(default_factory=list, max_length=8)
    slides: list[VisualSlide] = Field(default_factory=list, max_length=8)

    @field_validator("equations", "table_headers", mode="after")
    @classmethod
    def trim_text_lists(cls, values: list[str]) -> list[str]:
        return [str(value)[:500] for value in values]

    @field_validator("table_rows", mode="after")
    @classmethod
    def trim_table_rows(cls, rows: list[list[str]]) -> list[list[str]]:
        return [[str(value)[:300] for value in row[:8]] for row in rows[:12]]


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    session_id: str
    demo: bool = False
    visual: VisualPlan | None = None


class ConfigResponse(BaseModel):
    app_name: str
    openai_enabled: bool
    demo_mode: bool
    default_voice: str
    voices: list[str]
    max_image_mb: int
    max_audio_mb: int
    max_material_mb: int
    visual_plan_enabled: bool
    image_detail: str
