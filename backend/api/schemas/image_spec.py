from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.models.enums import (
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
    ImagePromptPresetKind,
    ImagePromptType,
)


class CompileImageSpecsRequest(BaseModel):
    style_profile_id: int | None = Field(default=None, gt=0)
    shot_planner_preset_id: int | None = Field(default=None, gt=0)
    negative_prompt_preset_id: int | None = Field(default=None, gt=0)
    generation_mode: GenerationMode = GenerationMode.PREVIEW
    concurrency: int = Field(default=8, ge=1, le=20)
    regenerate_continuity: bool = False
    resume_existing: bool = True



class ImageSpecPresetRequest(BaseModel):
    name: str
    kind: ImagePromptPresetKind
    content: str = ""
    tag_content: str = ""
    natural_language_content: str = ""
    description: str | None = None
    is_default: bool = False


class ImageSpecPresetResponse(ImageSpecPresetRequest):
    id: int
    created_at: datetime
    updated_at: datetime


class ContinuityEventEditItem(BaseModel):
    page_no: int = Field(gt=0)
    sequence_no: int = Field(gt=0)
    event_type: ContinuityEventType
    target_type: ContinuityTargetType
    target_key: str
    timing: ContinuityEventTiming = ContinuityEventTiming.AFTER_PAGE
    payload: dict[str, Any] = Field(default_factory=dict)


class ReplaceContinuityEventsRequest(BaseModel):
    events: list[ContinuityEventEditItem] = Field(default_factory=list)


class ContinuityEventResponse(BaseModel):
    id: int
    page_id: int
    page_no: int
    sequence_no: int
    event_type: str
    target_type: str
    target_key: str
    timing: str
    payload: dict[str, Any]
    source: str


class VisualSnapshotResponse(BaseModel):
    id: int
    page_id: int
    page_no: int
    state: dict[str, Any]
    state_hash: str
    warnings: list[Any]
    created_at: datetime


class ContinuityCompilationResponse(BaseModel):
    id: int
    task_id: int
    source_hash: str
    status: str
    events: list[ContinuityEventResponse]
    snapshots: list[VisualSnapshotResponse]
    created_at: datetime


class ImageSpecCompilationResponse(BaseModel):
    id: int
    task_id: int
    continuity_compilation_id: int
    source_hash: str
    status: str
    generation_mode: GenerationMode
    total_pages: int
    completed_pages: int
    total_specs: int
    completed_specs: int
    failed_pages: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ImageSpecResponse(BaseModel):
    id: int
    page_id: int
    page_no: int
    snapshot_id: int
    shot_plan_id: int
    prompt_type: ImagePromptType
    generation_mode: str
    spec: dict[str, Any]
    positive_prompt: str
    negative_prompt: str
    required_capabilities: list[str]
    warnings: list[Any]
    source_hash: str
    spec_hash: str
    compiler_key: str
    compiler_version: str
    created_at: datetime
