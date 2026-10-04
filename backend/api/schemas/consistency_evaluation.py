"""一致性评估 API 的请求与响应结构。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConsistencyThresholdsResponse(BaseModel):
    cids_cross_min: float = Field(ge=0, le=1)
    cids_self_min: float = Field(ge=0, le=1)
    csd_cross_min: float = Field(ge=0, le=1)
    csd_self_min: float = Field(ge=0, le=1)
    occm_min: float = Field(ge=0, le=100)
    copy_paste_max: float = Field(ge=0, le=1)


class UpdateConsistencyThresholdsRequest(ConsistencyThresholdsResponse):
    """更新全局准出阈值；已有评估仍保留原始阈值快照。"""


class ConsistencySettingsResponse(ConsistencyThresholdsResponse):
    runtime: dict[str, Any]
    metric_version: str


class ConsistencyReadinessResponse(BaseModel):
    ready: bool
    batch_task_id: int
    metric_version: str
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    runtime: dict[str, Any] | None
    track_count: int
    incomplete_tracks: list[dict[str, Any]]
    source_hash: str | None
    reference_baseline: dict[str, Any] | None


class ConsistencyTrackResponse(BaseModel):
    id: int
    evaluation_task_id: int
    candidate_index: int
    status: str
    passed: bool
    image_ids: dict[str, int]
    metrics: dict[str, Any]
    details: dict[str, Any]
    error_code: str | None
    error_message: str | None
    adopted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConsistencyTaskResponse(BaseModel):
    id: int
    batch_task_id: int
    script_task_id: int
    status: str
    source_hash: str
    thresholds: dict[str, float]
    metric_version: str
    progress: dict[str, Any]
    error_code: str | None
    error_message: str | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tracks: list[ConsistencyTrackResponse]


class ConsistencyTaskListResponse(BaseModel):
    items: list[ConsistencyTaskResponse]


class ConsistencyGateResponse(BaseModel):
    """历史接口兼容：passed 仅代表逐页人工选图完成，不要求评测。"""

    passed: bool
    evaluation_required: bool = False
    script_task_id: int
    batch_task_id: int | None
    evaluation_task_id: int | None
    track_id: int | None
    candidate_index: int | None
    source_hash: str | None
