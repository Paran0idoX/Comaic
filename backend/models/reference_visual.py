"""Agent、预览与人工修正共用的视觉摘要结构；事实必须带来源和视角。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.models.enums import ReferenceProfileKind, ReferenceFactKind, ReferenceFactPolarity, ReferenceProfileView

PROFILE_FORMAT_VERSION = 1


class VisualPhrase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    natural: str = Field(min_length=1, max_length=600)
    tags: list[str] = Field(min_length=1, max_length=30)


class ReferenceVisualFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ReferenceFactKind
    attribute: str = Field(min_length=1, max_length=120)
    polarity: ReferenceFactPolarity
    must_keep: bool = False
    source_field: str = Field(min_length=1, max_length=100)
    source_excerpt: str = Field(min_length=1, max_length=2000)
    views: list[ReferenceProfileView] = Field(min_length=1, max_length=6)
    options: list[VisualPhrase] = Field(min_length=1, max_length=12)
    selected: int = Field(default=0, ge=0)
    default_index: int = Field(default=0, ge=0)
    default_is_explicit: bool = False
    selection_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_choice(self):
        if self.selected >= len(self.options) or self.default_index >= len(self.options) or len(set(self.views)) != len(self.views):
            raise ValueError("Invalid visual choice or duplicate views")
        if not self.default_is_explicit and self.default_index != 0:
            raise ValueError("Without an explicit default, select the first candidate")
        return self


class ReferenceVisualData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human: bool = False
    facts: list[ReferenceVisualFact] = Field(max_length=100)


class ExtractedVisualProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ReferenceProfileKind
    owner_id: int = Field(gt=0)
    data: ReferenceVisualData


class ReferenceVisualExtraction(BaseModel):
    profiles: list[ExtractedVisualProfile] = Field(min_length=1, max_length=2)


class FixedSceneVisualFact(ReferenceVisualFact):
    """在模型输出协议中限制固定场景，正负事实共用地点语义。"""

    kind: Literal[ReferenceFactKind.ENVIRONMENT, ReferenceFactKind.LAYOUT,
                  ReferenceFactKind.MATERIAL, ReferenceFactKind.COLOR]


class FixedSceneVisualData(ReferenceVisualData):
    facts: list[FixedSceneVisualFact] = Field(max_length=100)


class FixedSceneVisualProfile(ExtractedVisualProfile):
    kind: Literal[ReferenceProfileKind.SCENE_SUBJECT]
    data: FixedSceneVisualData


class FixedSceneVisualExtraction(ReferenceVisualExtraction):
    """场景目录的提炼协议；持久化和公开 API 仍使用通用摘要结构。"""

    profiles: list[FixedSceneVisualProfile] = Field(min_length=1, max_length=2)


class ReferenceProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    revision: int = Field(gt=0)
    source_hash: str = Field(min_length=64, max_length=64)


class ReferenceProfileResponse(ReferenceProfileRef):
    project_id: int
    kind: ReferenceProfileKind
    owner_id: int
    format_version: int
    data: ReferenceVisualData


class ReferenceProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    data: ReferenceVisualData
