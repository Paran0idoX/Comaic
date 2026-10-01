"""统一参考图目录、生成输入和冻结任务响应。"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.schemas.character_reference import CharacterReferencePromptPair, CharacterReferenceTaskResponse
from backend.models.enums import ReferenceSourceMode, VisualAssetRole, VisualEntityType


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


class ReferencePromptPreviewResponse(BaseModel):
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


class ReferenceTaskListResponse(BaseModel):
    items: list[ReferenceTaskResponse]
