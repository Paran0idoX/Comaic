from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import (
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
)


class CompileImageSpecsRequest(BaseModel):
    model_profile_ids: list[int] = Field(min_length=1)
    primary_model_profile_id: int = Field(gt=0)
    style_profile_id: int | None = Field(default=None, gt=0)
    shot_planner_preset_id: int | None = Field(default=None, gt=0)
    negative_prompt_preset_id: int | None = Field(default=None, gt=0)
    generation_mode: GenerationMode = GenerationMode.PREVIEW
    concurrency: int = Field(default=8, ge=1, le=20)
    regenerate_continuity: bool = False

    @model_validator(mode="after")
    def validate_primary(self):
        if len(set(self.model_profile_ids)) != len(self.model_profile_ids):
            raise ValueError("model_profile_ids cannot contain duplicates")
        if self.primary_model_profile_id not in self.model_profile_ids:
            raise ValueError("primary_model_profile_id must be included in model_profile_ids")
        return self


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


class ImageSpecResponse(BaseModel):
    id: int
    page_id: int
    page_no: int
    snapshot_id: int
    shot_plan_id: int
    model_profile_id: int
    model_family: str
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
