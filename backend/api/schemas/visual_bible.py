from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import (
    ApprovalStatus,
    VisualAssetRole,
    VisualEntityType,
)


class OutfitVariantRequest(BaseModel):
    outline_character_id: int = Field(gt=0)
    key: str
    name: str
    garment_components: list[Any] = Field(default_factory=list)
    layer_order: list[Any] = Field(default_factory=list)
    colors: list[Any] = Field(default_factory=list)
    materials: list[Any] = Field(default_factory=list)
    patterns: list[Any] = Field(default_factory=list)
    accessories: list[Any] = Field(default_factory=list)
    trigger_tokens: list[Any] = Field(default_factory=list)
    negative_constraints: str = ""


class OutfitVariantResponse(OutfitVariantRequest):
    id: int
    project_id: int
    version: int
    status: ApprovalStatus
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StyleProfileRequest(BaseModel):
    key: str
    name: str
    positive_tag: str = ""
    negative_tag: str = ""
    positive_natural_language: str = ""
    negative_natural_language: str = ""
    color_palette: list[Any] = Field(default_factory=list)
    lighting: str = ""


class StyleProfileResponse(StyleProfileRequest):
    id: int
    project_id: int
    version: int
    status: ApprovalStatus
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SceneVisualVersionRequest(BaseModel):
    script_scene_id: int = Field(gt=0)
    landmarks: list[Any] = Field(default_factory=list)
    spatial_relations: dict[str, Any] = Field(default_factory=dict)
    camera_presets: list[Any] = Field(default_factory=list)
    object_states: dict[str, Any] = Field(default_factory=dict)
    color_palette: list[Any] = Field(default_factory=list)
    lighting_state: dict[str, Any] = Field(default_factory=dict)


class SceneVisualVersionResponse(SceneVisualVersionRequest):
    id: int
    project_id: int
    version: int
    status: ApprovalStatus
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApprovalRequest(BaseModel):
    status: ApprovalStatus


class VisualAssetLocatorRequest(BaseModel):
    entity_type: VisualEntityType
    entity_id: int | None = Field(default=None, gt=0)
    entity_key: str | None = None
    role: VisualAssetRole
    renderer_locator: str
    sha256: str | None = None
    approve: bool = False

    @model_validator(mode="after")
    def validate_owner(self):
        if self.entity_id is None and not (self.entity_key or "").strip():
            raise ValueError("entity_id or entity_key is required")
        return self


class PromoteImageRequest(BaseModel):
    entity_type: VisualEntityType
    entity_id: int | None = Field(default=None, gt=0)
    entity_key: str | None = None
    role: VisualAssetRole
    approve: bool = False


class VisualAssetResponse(BaseModel):
    id: int
    project_id: int
    entity_type: VisualEntityType
    entity_id: int | None
    entity_key: str | None
    role: VisualAssetRole
    storage_kind: str
    local_path: str | None
    renderer_locator: str | None
    mime_type: str | None
    sha256: str | None
    width: int | None
    height: int | None
    version: int
    status: ApprovalStatus
    source: str
    source_image_id: int | None
    crop_metadata: dict[str, Any]
    mask_asset_id: int | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssignOutfitRequest(BaseModel):
    outfit_variant_id: int | None = Field(default=None, gt=0)


class SelectSceneVersionRequest(BaseModel):
    scene_visual_version_id: int | None = Field(default=None, gt=0)
