"""统一参考图目录、生成输入和冻结任务响应。"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.schemas.character_reference import CharacterReferencePromptPair, CharacterReferenceTaskResponse
from backend.models.enums import ReferenceSourceMode, VisualAssetRole, VisualEntityType
from backend.models.reference_visual import ReferenceProfileRef, ReferenceProfileResponse


class ReferenceSubjectCreate(BaseModel):
    entity_type: VisualEntityType
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    negative_constraints: str = ""
    key: str | None = Field(default=None, max_length=120)


class ReferenceSubjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    negative_constraints: str = ""


class ReferenceSubjectResponse(ReferenceSubjectCreate):
    id: int
    project_id: int
    scene_definition_version: int = 1
    key: str
    created_at: datetime
    updated_at: datetime


class ReferenceSubjectListResponse(BaseModel):
    items: list[ReferenceSubjectResponse]


class AssignReferenceSubjectRequest(BaseModel):
    reference_subject_id: int | None = Field(default=None, gt=0)


class ReferencePromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: VisualEntityType
    entity_id: int | None = Field(default=None, gt=0)
    reference_subject_id: int | None = Field(default=None, gt=0)
    outfit_variant_id: int | None = Field(default=None, gt=0)
    tool_preset_id: int = Field(gt=0)
    roles: list[VisualAssetRole] = Field(min_length=1)
    source_mode: ReferenceSourceMode = ReferenceSourceMode.AUTO
    source_asset_ids: list[int] = Field(default_factory=list)
    canvas_asset_id: int | None = Field(default=None, gt=0)
    sizes: dict[str, dict[str, StrictInt]] = Field(default_factory=dict)
    refresh_visual_profiles: bool = False

    @model_validator(mode="after")
    def validate_selection(self):
        if len(set(self.roles)) != len(self.roles) or any(value <= 0 for value in self.source_asset_ids):
            raise ValueError("Reference roles must be distinct and source ids positive.")
        if self.source_mode != ReferenceSourceMode.MANUAL and self.source_asset_ids:
            raise ValueError("Only manual source mode accepts source_asset_ids.")
        return self


class CreateReferenceTaskRequest(ReferencePromptPreviewRequest):
    candidate_count: int = Field(default=2, ge=1, le=4)
    prompts: dict[str, CharacterReferencePromptPair]
    visual_profile_refs: list[ReferenceProfileRef] | None = None


class ReferencePromptBatchPreviewRequest(BaseModel):
    """整批只提交一次，逐对象准备结果通过 SSE 返回。"""
    model_config = ConfigDict(extra="forbid")
    items: list[ReferencePromptPreviewRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_owners(self):
        identities = [(item.entity_type, item.entity_id if item.entity_type == VisualEntityType.CHARACTER
            else item.reference_subject_id or item.entity_id) for item in self.items]
        if len(set(identities)) != len(identities):
            raise ValueError("Reference batch owners must be distinct.")
        return self


class CreateReferenceBatchRequest(BaseModel):
    """每个对象一条冻结输入，类别和用途沿用单任务校验。"""
    model_config = ConfigDict(extra="forbid")
    items: list[CreateReferenceTaskRequest] = Field(min_length=1, max_length=100)


class ReferencePromptPreviewResponse(BaseModel):
    visual_profiles: list[ReferenceProfileResponse] = Field(default_factory=list)
    entity_type: VisualEntityType
    entity_id: int | None
    reference_subject_id: int | None
    outfit_variant_id: int | None
    subject_name: str
    tool_preset_id: int
    prompt_type: str
    selected_roles: list[VisualAssetRole]
    source_asset_ids: list[int]
    canvas_asset_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
    prompts: dict[str, CharacterReferencePromptPair]
    sizes: dict[str, dict[str, int]] = Field(default_factory=dict)


class ReferenceTaskResponse(CharacterReferenceTaskResponse):
    outline_character_id: int | None
    entity_type: VisualEntityType
    entity_id: int | None
    entity_key: str | None
    reference_subject_id: int | None
    outfit_variant_id: int | None
    subject_name: str
    selected_roles: list[VisualAssetRole]
    source_asset_ids: list[int]
    sizes: dict[str, dict[str, int]] = Field(default_factory=dict)


class ReferenceTaskListResponse(BaseModel):
    items: list[ReferenceTaskResponse]
