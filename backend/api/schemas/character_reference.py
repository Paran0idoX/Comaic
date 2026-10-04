"""人物参考图 Prompt、任务、候选套组与产物 API 类型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from backend.models.reference_visual import ReferenceProfileRef, ReferenceProfileResponse

from backend.models.enums import (
    ApprovalStatus,
    CharacterVisualType,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationProvider,
    ImagePromptType,
    VisualAssetRole,
)


REFERENCE_ROLE_VALUES = {
    VisualAssetRole.IDENTITY_FACE.value,
    VisualAssetRole.IDENTITY_FULL_BODY.value,
}


class CharacterReferencePromptPair(BaseModel):
    positive: str
    negative: str = ""


class CharacterReferenceCharacterResponse(BaseModel):
    id: int
    outline_version_id: int
    character_key: str
    name: str
    visual_type: CharacterVisualType


class CharacterReferenceCharacterListResponse(BaseModel):
    items: list[CharacterReferenceCharacterResponse]


class CharacterReferencePromptPreviewRequest(BaseModel):
    tool_preset_id: int = Field(gt=0)
    style_profile_id: int | None = Field(default=None, gt=0)
    refresh_visual_profiles: bool = False


class CharacterReferencePromptPreviewResponse(BaseModel):
    visual_profiles: list[ReferenceProfileResponse] = Field(default_factory=list)
    character_id: int
    tool_preset_id: int
    style_profile_id: int | None
    prompt_type: ImagePromptType
    prompts: dict[str, CharacterReferencePromptPair]


class CreateCharacterReferenceTaskRequest(CharacterReferencePromptPreviewRequest):
    visual_profile_refs: list[ReferenceProfileRef] | None = None
    candidate_count: int = Field(default=2, ge=1, le=4)
    prompts: dict[str, CharacterReferencePromptPair]

    @model_validator(mode="after")
    def validate_roles(self):
        if set(self.prompts) != REFERENCE_ROLE_VALUES:
            raise ValueError("Face and full-body character reference prompts are required.")
        return self


class CharacterReferenceImageResponse(BaseModel):
    id: int
    artifact_index: int
    image_url: str
    sha256: str
    width: int | None
    height: int | None
    promoted_asset_id: int | None
    promoted_asset_status: ApprovalStatus | None = None


class CharacterReferenceRunResponse(BaseModel):
    id: int
    candidate_index: int
    role: VisualAssetRole
    seed: int
    provider: ImageGenerationProvider
    prompt_type: ImagePromptType
    positive_prompt: str
    negative_prompt: str
    status: GenerationRunStatus
    review_status: ApprovalStatus
    seed_applied: bool
    external_request_id: str | None
    degradations: list[dict]
    error_code: str | None
    images: list[CharacterReferenceImageResponse]
    primary_image: CharacterReferenceImageResponse | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class CharacterReferenceCandidateSetResponse(BaseModel):
    candidate_index: int
    seed: int
    status: str
    review_status: ApprovalStatus
    complete: bool
    roles: dict[str, CharacterReferenceRunResponse]


class CharacterReferenceTaskResponse(BaseModel):
    visual_profiles: list[ReferenceProfileResponse] = Field(default_factory=list)
    id: int
    project_id: int
    outline_character_id: int | None
    character_name: str
    tool_preset_id: int
    tool_name: str
    style_profile_id: int | None
    status: GenerationTaskStatus
    candidate_count: int
    prompt_type: ImagePromptType
    prompts: dict[str, CharacterReferencePromptPair]
    progress: dict
    approved_candidate_index: int | None
    error_code: str | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    candidates: list[CharacterReferenceCandidateSetResponse]


class CharacterReferenceTaskListResponse(BaseModel):
    items: list[CharacterReferenceTaskResponse]
