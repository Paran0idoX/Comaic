from datetime import datetime
from typing import Optional

from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.database import Base
from backend.models.enums import (
    ApprovalStatus,
    CharacterVisualType,
    ComicPageStatus,
    CompilationStatus,
    ConsistencyEvaluationStatus,
    ConsistencyTrackStatus,
    ContinuityEventSource,
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskKind,
    GenerationTaskStatus,
    ImageGenerationProvider,
    ImagePromptType,
    ImagePromptPresetKind,
    LLMProvider,
    ReferenceProfileKind,
    OutlineVersionStatus,
    PageScriptReviewStatus,
    SeedStrategy,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
    SessionPurpose,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.models.time import AwareUTCDateTime, utc_now


def enum_column(enum_type: type[Enum], **kwargs):
    """创建枚举字段，并把枚举的 value 存到数据库中。"""

    return mapped_column(
        SqlEnum(
            enum_type,
            # 默认会存枚举名；这里显式存 value，数据库内容更直观。
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=False,
        ),
        **kwargs,
    )


class ReferenceVisualProfile(Base):
    """参考图专用摘要缓存；任务另存完整快照，修改摘要不改变历史生成。"""

    __tablename__ = "reference_visual_profile"
    __table_args__ = (UniqueConstraint("project_id", "kind", "owner_id", name="uq_reference_profile_owner"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    kind: Mapped[ReferenceProfileKind] = enum_column(ReferenceProfileKind)
    owner_id: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    format_version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now, onupdate=utc_now)


class TimestampMixin:
    """给需要时间戳的表复用 created_at / updated_at 字段。"""

    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        AwareUTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
    )


comic_page_character_table = Table(
    "comic_page_character",
    Base.metadata,
    Column("page_id", ForeignKey("comic_page.id"), primary_key=True),
    Column("character_id", ForeignKey("script_character.id"), primary_key=True),
)


class ComicProject(TimestampMixin, Base):
    """漫画项目表：保存项目基础信息，大纲内容由版本表管理。"""

    __tablename__ = "comic_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))

    # 删除项目时级联删除页面，避免孤立页面数据。
    pages: Mapped[list["ComicPage"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    # 大纲版本直接归属于项目；Session 只负责承载 Agent 对话上下文。
    outline_versions: Mapped[list["OutlineVersion"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    # 项目被硬删除时，关联任务也应删除，避免任务指向不存在的项目。
    tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    # 分页脚本生成任务独立于出图任务，便于跟踪长任务状态。
    script_tasks: Mapped[list["ScriptGenerationTask"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    # 通用会话用于承载大纲对话、后续脚本生成等不同业务上下文。
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ImagePromptPreset(TimestampMixin, Base):
    """视觉规格 Prompt 配置：维护 ShotPlanner 与不同表达类型的负向 Prompt。"""

    __tablename__ = "image_prompt_preset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[ImagePromptPresetKind] = enum_column(ImagePromptPresetKind, index=True)
    content: Mapped[str] = mapped_column(Text)
    tag_content: Mapped[str] = mapped_column(Text, default="")
    natural_language_content: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ImageGenerationToolPreset(TimestampMixin, Base):
    """通用生图工具配置：支持 ComfyUI workflow 和 OpenAI Images 兼容 API。"""

    __tablename__ = "image_generation_tool_preset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[ImageGenerationProvider] = enum_column(
        ImageGenerationProvider,
        index=True,
        default=ImageGenerationProvider.COMFYUI,
    )
    prompt_type: Mapped[ImagePromptType] = enum_column(
        ImagePromptType,
        index=True,
        default=ImagePromptType.NATURAL_LANGUAGE,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # 新版 workflow 通过能力声明和通用 binding 注入；旧三节点字段保留一版兼容。
    capabilities_json: Mapped[str] = mapped_column(Text, default='{"features":["txt2img"],"limits":{}}')
    bindings_json: Mapped[str] = mapped_column(Text, default='{"schema_version":1,"bindings":[]}')

    # ComfyUI 配置。comfy_base_url 为空时回退到 COMFYUI_BASE_URL。
    comfy_base_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    workflow_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    positive_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    positive_input_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    negative_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    negative_input_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seed_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seed_input_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # OpenAI Images 兼容 API 配置。
    api_base_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    endpoint_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    response_format: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    seed_field_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    negative_prompt_field_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extra_body_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class LLMConfig(TimestampMixin, Base):
    """全局 LLM 配置表：一组 LangChain Provider/API Key 下维护多个模型名。"""

    __tablename__ = "llm_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[LLMProvider] = enum_column(
        LLMProvider,
        default=LLMProvider.OPENAI_COMPATIBLE,
    )
    base_url: Mapped[str] = mapped_column(String(1024))
    # JSON 字符串数组，例如 ["deepseek-v4-flash", "deepseek-chat"]。
    model_names: Mapped[str] = mapped_column(Text, default="[]")
    # 按本 API 组中的模型名保存全局提示词覆盖；缺省时使用 Provider 默认模板。
    model_system_prompts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 默认模板关联仅在配置初始化时确定；请求注入不根据 Provider 或模型名分支。
    model_system_prompt_defaults_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_model: Mapped[str] = mapped_column(String(255))
    # 本地 MVP 直接保存在 SQLite；设置页允许回显明文，data/ 不能提交。
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class AppSettings(TimestampMixin, Base):
    """应用级配置表：保存不属于单个模型 API 组的全局运行参数。"""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # 分页脚本生成按 section 并发执行时的最高 worker 数。
    script_section_max_concurrency: Mapped[int] = mapped_column(Integer, default=3)
    # 仅保存任务提示词覆盖，恢复默认时删除对应 key，继续读取仓库 Markdown。
    system_prompts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Session(TimestampMixin, Base):
    """通用会话表：用 purpose 区分大纲、脚本等不同业务场景。"""

    __tablename__ = "session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    # thread_id 是暴露给前端和 LangGraph checkpoint 使用的会话标识。
    thread_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    purpose: Mapped[SessionPurpose] = enum_column(
        SessionPurpose,
        default=SessionPurpose.OUTLINE,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="sessions")
    outline_versions: Mapped[list["OutlineVersion"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class OutlineVersion(Base):
    """大纲版本表：保存每轮对话结束后的大纲快照。"""

    __tablename__ = "outline_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[OutlineVersionStatus] = enum_column(
        OutlineVersionStatus,
        default=OutlineVersionStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(),
        nullable=True,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="outline_versions")
    session: Mapped["Session"] = relationship(back_populates="outline_versions")
    characters: Mapped[list["OutlineCharacter"]] = relationship(
        back_populates="outline_version",
        cascade="all, delete-orphan",
    )
    script_tasks: Mapped[list["ScriptGenerationTask"]] = relationship(
        back_populates="outline_version",
    )


class OutlineCharacter(TimestampMixin, Base):
    """大纲版本级角色基准设定，保存跨分段不应轻易改变的角色识别信息。"""

    __tablename__ = "outline_character"
    __table_args__ = (
        UniqueConstraint("outline_version_id", "character_key", name="uq_outline_character_version_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outline_version_id: Mapped[int] = mapped_column(
        ForeignKey("outline_version.id"),
        index=True,
    )
    character_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(255), default="")
    background: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    negative_constraints: Mapped[str] = mapped_column(Text, default="")
    # 这些字段是脚本阶段可覆盖的默认造型，不作为永久锁死项。
    default_hairstyle: Mapped[str] = mapped_column(Text, default="")
    default_clothing: Mapped[str] = mapped_column(Text, default="")
    default_accessories: Mapped[str] = mapped_column(Text, default="")
    default_color_palette: Mapped[str] = mapped_column(Text, default="")
    visual_type: Mapped[CharacterVisualType] = enum_column(
        CharacterVisualType,
        default=CharacterVisualType.STYLIZED_HUMAN,
        index=True,
    )

    outline_version: Mapped["OutlineVersion"] = relationship(back_populates="characters")
    section_characters: Mapped[list["ScriptCharacter"]] = relationship(
        back_populates="outline_character",
    )
    outfit_variants: Mapped[list["OutfitVariant"]] = relationship(
        back_populates="outline_character",
        cascade="all, delete-orphan",
    )


class OutfitVariant(TimestampMixin, Base):
    """版本化服装设定：把服装真值从自由描述中独立出来。"""

    __tablename__ = "outfit_variant"
    __table_args__ = (
        UniqueConstraint(
            "outline_character_id",
            "key",
            "version",
            name="uq_outfit_variant_character_key_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    outline_character_id: Mapped[int] = mapped_column(
        ForeignKey("outline_character.id"), index=True
    )
    key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(255), default="")
    garment_components_json: Mapped[str] = mapped_column(Text, default="[]")
    layer_order_json: Mapped[str] = mapped_column(Text, default="[]")
    colors_json: Mapped[str] = mapped_column(Text, default="[]")
    materials_json: Mapped[str] = mapped_column(Text, default="[]")
    patterns_json: Mapped[str] = mapped_column(Text, default="[]")
    accessories_json: Mapped[str] = mapped_column(Text, default="[]")
    trigger_tokens_json: Mapped[str] = mapped_column(Text, default="[]")
    negative_constraints: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ApprovalStatus] = enum_column(
        ApprovalStatus,
        default=ApprovalStatus.DRAFT,
        index=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    outline_character: Mapped["OutlineCharacter"] = relationship(
        back_populates="outfit_variants"
    )
    section_characters: Mapped[list["ScriptCharacter"]] = relationship(
        back_populates="outfit_variant"
    )


class StyleProfile(TimestampMixin, Base):
    """项目级版本化风格设定，分别保存 tag 与自然语言表达。"""

    __tablename__ = "style_profile"
    __table_args__ = (
        UniqueConstraint("project_id", "key", "version", name="uq_style_project_key_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(255), default="")
    positive_tag: Mapped[str] = mapped_column(Text, default="")
    negative_tag: Mapped[str] = mapped_column(Text, default="")
    positive_natural_language: Mapped[str] = mapped_column(Text, default="")
    negative_natural_language: Mapped[str] = mapped_column(Text, default="")
    color_palette_json: Mapped[str] = mapped_column(Text, default="[]")
    lighting: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ApprovalStatus] = enum_column(
        ApprovalStatus,
        default=ApprovalStatus.DRAFT,
        index=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )


class SceneVisualVersion(TimestampMixin, Base):
    """场景的版本化视觉母版与空间状态。"""

    __tablename__ = "scene_visual_version"
    __table_args__ = (
        UniqueConstraint("script_scene_id", "version", name="uq_scene_visual_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    script_scene_id: Mapped[int] = mapped_column(ForeignKey("script_scene.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    landmarks_json: Mapped[str] = mapped_column(Text, default="[]")
    spatial_relations_json: Mapped[str] = mapped_column(Text, default="{}")
    camera_presets_json: Mapped[str] = mapped_column(Text, default="[]")
    object_states_json: Mapped[str] = mapped_column(Text, default="{}")
    color_palette_json: Mapped[str] = mapped_column(Text, default="[]")
    lighting_state_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[ApprovalStatus] = enum_column(
        ApprovalStatus,
        default=ApprovalStatus.DRAFT,
        index=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    script_scene: Mapped["ScriptScene"] = relationship(
        back_populates="visual_versions",
        foreign_keys=[script_scene_id],
    )


class ReferenceSubject(TimestampMixin, Base):
    """项目内稳定命名的场景和物品；分类固定，条目不依赖脚本批次。"""

    __tablename__ = "reference_subject"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "key", name="uq_reference_subject_project_type_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    entity_type: Mapped[VisualEntityType] = enum_column(VisualEntityType, index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # 旧条目为 1；业务入口显式创建版本 2，避免重解释历史日夜场景。
    scene_definition_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    description: Mapped[str] = mapped_column(Text, default="")
    negative_constraints: Mapped[str] = mapped_column(Text, default="")


class VisualAsset(TimestampMixin, Base):
    """视觉资产库：保存人工批准的图片条件或 ComfyUI 侧模型定位。"""

    __tablename__ = "visual_asset"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "entity_type",
            "entity_id",
            "entity_key",
            "role",
            "version",
            name="uq_visual_asset_owner_role_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    entity_type: Mapped[VisualEntityType] = enum_column(VisualEntityType, index=True)
    # 多态归属由 Service 校验：character/outfit/scene/style 对应各自表 id。
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entity_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    # 新目录显式归属，避免把 scene.entity_id 从旧视觉版本 id 偷换成目录 id。
    reference_subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reference_subject.id"), nullable=True, index=True
    )
    outfit_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outfit_variant.id"), nullable=True, index=True
    )
    role: Mapped[VisualAssetRole] = enum_column(VisualAssetRole, index=True)
    storage_kind: Mapped[VisualAssetStorageKind] = enum_column(VisualAssetStorageKind)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    renderer_locator: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ApprovalStatus] = enum_column(
        ApprovalStatus,
        default=ApprovalStatus.DRAFT,
        index=True,
    )
    source: Mapped[VisualAssetSource] = enum_column(VisualAssetSource)
    source_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comic_image.id"), nullable=True
    )
    derived_from_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("visual_asset.id"), nullable=True
    )
    crop_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    mask_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("visual_asset.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )


class CharacterReferenceGenerationTask(TimestampMixin, Base):
    """人物/场景/物品参考图后台任务；复用历史表名，与分页图片任务分离。"""

    __tablename__ = "character_reference_generation_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    outline_character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outline_character.id"), nullable=True, index=True
    )
    entity_type: Mapped[VisualEntityType] = enum_column(
        VisualEntityType, default=VisualEntityType.CHARACTER, index=True
    )
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entity_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reference_subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reference_subject.id"), nullable=True, index=True
    )
    outfit_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outfit_variant.id"), nullable=True, index=True
    )
    selected_roles_json: Mapped[str] = mapped_column(Text, default="[]")
    source_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    subject_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    tool_preset_id: Mapped[int] = mapped_column(
        ForeignKey("image_generation_tool_preset.id"), index=True
    )
    style_profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("style_profile.id"), nullable=True, index=True
    )
    status: Mapped[GenerationTaskStatus] = enum_column(
        GenerationTaskStatus,
        default=GenerationTaskStatus.PENDING,
        index=True,
    )
    candidate_count: Mapped[int] = mapped_column(Integer, default=2)
    prompt_type: Mapped[ImagePromptType] = enum_column(ImagePromptType)
    prompt_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    approved_candidate_index: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    project: Mapped["ComicProject"] = relationship()
    outline_character: Mapped[Optional["OutlineCharacter"]] = relationship()
    reference_subject: Mapped[Optional["ReferenceSubject"]] = relationship()
    tool_preset: Mapped["ImageGenerationToolPreset"] = relationship()
    style_profile: Mapped[Optional["StyleProfile"]] = relationship()
    runs: Mapped[list["CharacterReferenceGenerationRun"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by=(
            "CharacterReferenceGenerationRun.candidate_index, "
            "CharacterReferenceGenerationRun.role"
        ),
    )


class CharacterReferenceGenerationRun(TimestampMixin, Base):
    """三件套中的单个角色构图请求，保存完整 Provider 与 Prompt 溯源。"""

    __tablename__ = "character_reference_generation_run"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "candidate_index",
            "role",
            name="uq_character_reference_run_candidate_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("character_reference_generation_task.id"), index=True
    )
    candidate_index: Mapped[int] = mapped_column(Integer)
    role: Mapped[VisualAssetRole] = enum_column(VisualAssetRole, index=True)
    seed: Mapped[int] = mapped_column(Integer)
    provider: Mapped[ImageGenerationProvider] = enum_column(
        ImageGenerationProvider, index=True
    )
    prompt_type: Mapped[ImagePromptType] = enum_column(ImagePromptType)
    positive_prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[GenerationRunStatus] = enum_column(
        GenerationRunStatus,
        default=GenerationRunStatus.PENDING,
        index=True,
    )
    review_status: Mapped[ApprovalStatus] = enum_column(
        ApprovalStatus,
        default=ApprovalStatus.DRAFT,
        index=True,
    )
    seed_applied: Mapped[bool] = mapped_column(Boolean, default=True)
    external_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    workflow_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workflow_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bindings_json: Mapped[str] = mapped_column(Text, default="{}")
    degradation_json: Mapped[str] = mapped_column(Text, default="[]")
    applied_spec_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    task: Mapped["CharacterReferenceGenerationTask"] = relationship(
        back_populates="runs"
    )
    images: Mapped[list["CharacterReferenceImage"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CharacterReferenceImage.artifact_index",
    )


class CharacterReferenceImage(TimestampMixin, Base):
    """参考图候选原图；人工单图确认或兼容整套批准后提升为 VisualAsset。"""

    __tablename__ = "character_reference_image"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "artifact_index",
            name="uq_character_reference_image_artifact",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("character_reference_generation_run.id"), index=True
    )
    artifact_index: Mapped[int] = mapped_column(Integer, default=1)
    local_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promoted_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("visual_asset.id"), nullable=True, unique=True
    )

    run: Mapped["CharacterReferenceGenerationRun"] = relationship(
        back_populates="images"
    )
    promoted_asset: Mapped[Optional["VisualAsset"]] = relationship()


class ComicPage(TimestampMixin, Base):
    """漫画页面表：保存单页脚本和最终选择的生成图片。"""

    __tablename__ = "comic_page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("script_section.id"),
        nullable=True,
        index=True,
    )
    scene_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("script_scene.id"),
        nullable=True,
        index=True,
    )
    page_no: Mapped[int] = mapped_column(Integer)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    characters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clothing: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene_conditions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    composition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    character_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dialogue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ComicPageStatus] = enum_column(
        ComicPageStatus,
        default=ComicPageStatus.DRAFT,
    )
    script_review_status: Mapped[PageScriptReviewStatus] = enum_column(
        PageScriptReviewStatus,
        default=PageScriptReviewStatus.UNREVIEWED,
    )
    script_review_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # selected_image_id 指向用户最终选择的候选图；未选择前为空。
    selected_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comic_image.id"),
        nullable=True,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="pages")
    section: Mapped[Optional["ScriptSection"]] = relationship(back_populates="pages")
    script_scene: Mapped[Optional["ScriptScene"]] = relationship(back_populates="pages")
    # visual_characters 是角色视觉设定绑定；characters 字段仍保存本页局部人物描述文本。
    visual_characters: Mapped[list["ScriptCharacter"]] = relationship(
        secondary=comic_page_character_table,
        back_populates="pages",
    )
    images: Mapped[list["ComicImage"]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
        foreign_keys="ComicImage.page_id",
    )
    # selected_image 与 images 都关联 comic_image，需要显式指定外键避免歧义。
    selected_image: Mapped[Optional["ComicImage"]] = relationship(
        foreign_keys=[selected_image_id],
        post_update=True,
    )
    tasks: Mapped[list["GenerationTask"]] = relationship(back_populates="page")


class ComicImage(Base):
    """图片生成结果表：记录每页由 ComfyUI 生成的图片及其元信息。"""

    __tablename__ = "comic_image"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    generation_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("generation_run.id"), nullable=True, index=True
    )
    # 一个外部请求可能返回多张图；一致性轨道只消费 artifact_index=1 的主产物。
    artifact_index: Mapped[int] = mapped_column(Integer, default=1)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)

    page: Mapped["ComicPage"] = relationship(
        back_populates="images",
        foreign_keys=[page_id],
    )
    generation_run: Mapped[Optional["GenerationRun"]] = relationship(
        back_populates="images"
    )


class GenerationTask(TimestampMixin, Base):
    """生成任务表：记录提交到 ComfyUI 的任务状态和返回的 prompt_id。"""

    __tablename__ = "generation_task"

    # 首个外部请求前冻结整批输入；暂停继续不重新选择素材或种子。
    input_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    page_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comic_page.id"), nullable=True)
    script_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("script_generation_task.id"), nullable=True, index=True
    )
    tool_preset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("image_generation_tool_preset.id"), nullable=True, index=True
    )
    parent_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("generation_task.id"), nullable=True, index=True
    )
    task_kind: Mapped[GenerationTaskKind] = enum_column(
        GenerationTaskKind,
        default=GenerationTaskKind.LEGACY,
        index=True,
    )
    generation_mode: Mapped[Optional[GenerationMode]] = enum_column(
        GenerationMode,
        nullable=True,
        index=True,
    )
    seed_strategy: Mapped[Optional[SeedStrategy]] = enum_column(
        SeedStrategy,
        nullable=True,
    )
    candidate_count: Mapped[int] = mapped_column(Integer, default=1)
    comfy_prompt_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[GenerationTaskStatus] = enum_column(
        GenerationTaskStatus,
        default=GenerationTaskStatus.PENDING,
    )
    batch_size: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 由当前应用进程的后台线程定期刷新，用来识别异常退出后遗留的 running 任务。
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(),
        nullable=True,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="tasks")
    page: Mapped[Optional["ComicPage"]] = relationship(back_populates="tasks")
    runs: Mapped[list["GenerationRun"]] = relationship(
        back_populates="generation_task",
        cascade="all, delete-orphan",
        foreign_keys="GenerationRun.generation_task_id",
    )
    parent_task: Mapped[Optional["GenerationTask"]] = relationship(
        remote_side=[id],
        back_populates="child_tasks",
        foreign_keys=[parent_task_id],
    )
    child_tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="parent_task",
        foreign_keys=[parent_task_id],
    )
    batch_runs: Mapped[list["GenerationRun"]] = relationship(
        back_populates="batch_task",
        foreign_keys="GenerationRun.batch_task_id",
    )
    tool_preset: Mapped[Optional["ImageGenerationToolPreset"]] = relationship()


class ConsistencyEvaluationConfig(TimestampMixin, Base):
    """全局一致性准出阈值；每次评估还会保存不可变快照。"""

    __tablename__ = "consistency_evaluation_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cids_cross_min: Mapped[float] = mapped_column(Float, default=0.45)
    cids_self_min: Mapped[float] = mapped_column(Float, default=0.60)
    csd_cross_min: Mapped[float] = mapped_column(Float, default=0.35)
    csd_self_min: Mapped[float] = mapped_column(Float, default=0.60)
    occm_min: Mapped[float] = mapped_column(Float, default=70.0)
    copy_paste_max: Mapped[float] = mapped_column(Float, default=0.30)


class ConsistencyEvaluationTask(TimestampMixin, Base):
    """一次完整图片生成批次的 ViStoryBench 评估任务。"""

    __tablename__ = "consistency_evaluation_task"
    __table_args__ = (
        UniqueConstraint(
            "batch_task_id",
            "source_hash",
            "metric_version",
            name="uq_consistency_evaluation_task_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id"), index=True
    )
    script_task_id: Mapped[int] = mapped_column(
        ForeignKey("script_generation_task.id"), index=True
    )
    status: Mapped[ConsistencyEvaluationStatus] = enum_column(
        ConsistencyEvaluationStatus,
        default=ConsistencyEvaluationStatus.PENDING,
        index=True,
    )
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    thresholds_json: Mapped[str] = mapped_column(Text)
    manifest_json: Mapped[str] = mapped_column(Text)
    metric_version: Mapped[str] = mapped_column(String(64))
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    batch_task: Mapped["GenerationTask"] = relationship(
        foreign_keys=[batch_task_id]
    )
    tracks: Mapped[list["ConsistencyEvaluationTrack"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ConsistencyEvaluationTrack.candidate_index",
    )


class ConsistencyEvaluationTrack(TimestampMixin, Base):
    """候选序号跨全部页面形成的完整轨道及其准出结果。"""

    __tablename__ = "consistency_evaluation_track"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_task_id",
            "candidate_index",
            name="uq_consistency_evaluation_track_candidate",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_task_id: Mapped[int] = mapped_column(
        ForeignKey("consistency_evaluation_task.id"), index=True
    )
    candidate_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[ConsistencyTrackStatus] = enum_column(
        ConsistencyTrackStatus,
        default=ConsistencyTrackStatus.PENDING,
        index=True,
    )
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    image_ids_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    adopted_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    task: Mapped["ConsistencyEvaluationTask"] = relationship(back_populates="tracks")


class ScriptGenerationTask(TimestampMixin, Base):
    """分页脚本生成任务表：记录单页/批量脚本生成的状态。"""

    __tablename__ = "script_generation_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    outline_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outline_version.id"),
        nullable=True,
    )
    status: Mapped[ScriptGenerationTaskStatus] = enum_column(
        ScriptGenerationTaskStatus,
        default=ScriptGenerationTaskStatus.PENDING,
    )
    mode: Mapped[ScriptGenerationMode] = enum_column(ScriptGenerationMode)
    total_pages: Mapped[int] = mapped_column(Integer)
    scene_definition_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    target_page_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_requirement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 只由当前进程真实执行中的任务刷新，重启后未刷新即会被识别为僵尸任务。
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(),
        nullable=True,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="script_tasks")
    outline_version: Mapped[Optional["OutlineVersion"]] = relationship(
        back_populates="script_tasks",
    )
    sections: Mapped[list["ScriptSection"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    scenes: Mapped[list["ScriptScene"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    continuity_compilations: Mapped[list["ContinuityCompilation"]] = relationship(
        back_populates="script_task",
        cascade="all, delete-orphan",
    )
    image_spec_compilations: Mapped[list["ImageSpecCompilation"]] = relationship(
        back_populates="script_task",
        cascade="all, delete-orphan",
    )


class ScriptSection(TimestampMixin, Base):
    """分页脚本分段表：保存一次脚本任务里的故事节奏划分。"""

    __tablename__ = "script_section"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("script_generation_task.id"), index=True)
    section_no: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ScriptSectionStatus] = enum_column(
        ScriptSectionStatus,
        default=ScriptSectionStatus.GENERATING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["ScriptGenerationTask"] = relationship(back_populates="sections")
    pages: Mapped[list["ComicPage"]] = relationship(back_populates="section")
    characters: Mapped[list["ScriptCharacter"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class ScriptScene(TimestampMixin, Base):
    """脚本任务内的中心化场景设定，用于保持同一场景跨页视觉一致。"""

    __tablename__ = "script_scene"
    __table_args__ = (
        UniqueConstraint("task_id", "scene_key", name="uq_script_scene_task_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("script_generation_task.id"), index=True)
    reference_subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reference_subject.id"), nullable=True, index=True
    )
    selected_visual_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scene_visual_version.id"), nullable=True
    )
    scene_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    location_type: Mapped[str] = mapped_column(String(255), default="")
    time_of_day: Mapped[str] = mapped_column(String(255), default="")
    lighting: Mapped[str] = mapped_column(Text, default="")
    weather: Mapped[str] = mapped_column(String(255), default="")
    environment_details: Mapped[str] = mapped_column(Text, default="")
    color_palette: Mapped[str] = mapped_column(Text, default="")
    negative_constraints: Mapped[str] = mapped_column(Text, default="")

    task: Mapped["ScriptGenerationTask"] = relationship(back_populates="scenes")
    reference_subject: Mapped[Optional["ReferenceSubject"]] = relationship()
    pages: Mapped[list["ComicPage"]] = relationship(back_populates="script_scene")
    visual_versions: Mapped[list["SceneVisualVersion"]] = relationship(
        back_populates="script_scene",
        foreign_keys="SceneVisualVersion.script_scene_id",
        cascade="all, delete-orphan",
    )
    selected_visual_version: Mapped[Optional["SceneVisualVersion"]] = relationship(
        foreign_keys=[selected_visual_version_id],
        post_update=True,
    )


class ScriptCharacter(TimestampMixin, Base):
    """脚本分段内的角色细化设定，用于表达该分段中的造型和状态变化。"""

    __tablename__ = "script_character"
    __table_args__ = (
        UniqueConstraint("section_id", "character_key", name="uq_script_character_section_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("script_section.id"), index=True)
    outline_character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outline_character.id"),
        nullable=True,
        index=True,
    )
    outfit_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outfit_variant.id"), nullable=True, index=True
    )
    character_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    section_role: Mapped[str] = mapped_column(String(255), default="")
    current_hairstyle: Mapped[str] = mapped_column(Text, default="")
    current_clothing: Mapped[str] = mapped_column(Text, default="")
    current_accessories: Mapped[str] = mapped_column(Text, default="")
    current_state: Mapped[str] = mapped_column(Text, default="")
    emotion: Mapped[str] = mapped_column(Text, default="")
    temporary_changes: Mapped[str] = mapped_column(Text, default="")
    negative_constraints: Mapped[str] = mapped_column(Text, default="")

    section: Mapped["ScriptSection"] = relationship(back_populates="characters")
    outline_character: Mapped[Optional["OutlineCharacter"]] = relationship(
        back_populates="section_characters",
    )
    outfit_variant: Mapped[Optional["OutfitVariant"]] = relationship(
        back_populates="section_characters"
    )
    pages: Mapped[list["ComicPage"]] = relationship(
        secondary=comic_page_character_table,
        back_populates="visual_characters",
    )


class ContinuityCompilation(TimestampMixin, Base):
    """保留历史表名承载页输入编译；新记录不产生事件，旧连续性记录仍可读取。"""

    __tablename__ = "continuity_compilation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_task_id: Mapped[int] = mapped_column(
        ForeignKey("script_generation_task.id"), index=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[CompilationStatus] = enum_column(
        CompilationStatus,
        default=CompilationStatus.PENDING,
        index=True,
    )
    llm_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llm_config.id"), nullable=True
    )
    llm_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), default="1")
    reducer_version: Mapped[str] = mapped_column(String(64), default="1")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    script_task: Mapped["ScriptGenerationTask"] = relationship(
        back_populates="continuity_compilations"
    )
    events: Mapped[list["ContinuityEvent"]] = relationship(
        back_populates="compilation",
        cascade="all, delete-orphan",
        order_by="ContinuityEvent.page_id, ContinuityEvent.sequence_no",
    )
    snapshots: Mapped[list["VisualStateSnapshot"]] = relationship(
        back_populates="compilation",
        cascade="all, delete-orphan",
    )
    image_spec_compilations: Mapped[list["ImageSpecCompilation"]] = relationship(
        back_populates="continuity_compilation",
        cascade="all, delete-orphan",
    )


class ImageSpecCompilation(TimestampMixin, Base):
    """一次全任务 ImageSpec 编译尝试，持久保存部分进度和失败页。"""

    __tablename__ = "image_spec_compilation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_task_id: Mapped[int] = mapped_column(
        ForeignKey("script_generation_task.id"), index=True
    )
    continuity_compilation_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_compilation.id"), index=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[CompilationStatus] = enum_column(
        CompilationStatus,
        default=CompilationStatus.PENDING,
        index=True,
    )
    generation_mode: Mapped[GenerationMode] = enum_column(
        GenerationMode,
        default=GenerationMode.PREVIEW,
        index=True,
    )
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    completed_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_specs: Mapped[int] = mapped_column(Integer, default=0)
    completed_specs: Mapped[int] = mapped_column(Integer, default=0)
    failed_pages_json: Mapped[str] = mapped_column(Text, default="[]")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    script_task: Mapped["ScriptGenerationTask"] = relationship(
        back_populates="image_spec_compilations"
    )
    continuity_compilation: Mapped["ContinuityCompilation"] = relationship(
        back_populates="image_spec_compilations"
    )


class ContinuityEvent(Base):
    """历史连续性事件，仅供生成记录回溯；新流程不再写入或修改。"""

    __tablename__ = "continuity_event"
    __table_args__ = (
        UniqueConstraint(
            "compilation_id",
            "page_id",
            "sequence_no",
            name="uq_continuity_event_compilation_page_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    compilation_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_compilation.id"), index=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[ContinuityEventType] = enum_column(ContinuityEventType, index=True)
    target_type: Mapped[ContinuityTargetType] = enum_column(ContinuityTargetType)
    target_key: Mapped[str] = mapped_column(String(120), index=True)
    timing: Mapped[ContinuityEventTiming] = enum_column(
        ContinuityEventTiming,
        default=ContinuityEventTiming.AFTER_PAGE,
    )
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[ContinuityEventSource] = enum_column(
        ContinuityEventSource,
        default=ContinuityEventSource.LLM,
    )
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)

    compilation: Mapped["ContinuityCompilation"] = relationship(back_populates="events")
    page: Mapped["ComicPage"] = relationship()


class VisualStateSnapshot(Base):
    """某页不可变的脚本、绑定设定和资产版本；历史状态快照保持原样。"""

    __tablename__ = "visual_state_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "compilation_id", "page_id", name="uq_snapshot_compilation_page"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    compilation_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_compilation.id"), index=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    scene_visual_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scene_visual_version.id"), nullable=True
    )
    state_json: Mapped[str] = mapped_column(Text)
    state_hash: Mapped[str] = mapped_column(String(64), index=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)

    compilation: Mapped["ContinuityCompilation"] = relationship(back_populates="snapshots")
    page: Mapped["ComicPage"] = relationship()
    shot_plans: Mapped[list["PageShotPlan"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class PageShotPlan(Base):
    """模型无关镜头计划；只允许描述镜头、动作和空间布局。"""

    __tablename__ = "page_shot_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("visual_state_snapshot.id"), index=True
    )
    planner_preset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("image_prompt_preset.id"), nullable=True
    )
    plan_json: Mapped[str] = mapped_column(Text)
    plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    planner_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), default="1")
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)

    page: Mapped["ComicPage"] = relationship()
    snapshot: Mapped["VisualStateSnapshot"] = relationship(back_populates="shot_plans")
    image_specs: Mapped[list["ImageSpec"]] = relationship(
        back_populates="shot_plan",
        cascade="all, delete-orphan",
    )


class ImageSpec(Base):
    """按 Prompt 表达类型保存的结构化生成规格。"""

    __tablename__ = "image_spec"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("visual_state_snapshot.id"), index=True
    )
    shot_plan_id: Mapped[int] = mapped_column(
        ForeignKey("page_shot_plan.id"), index=True
    )
    prompt_type: Mapped[ImagePromptType] = enum_column(
        ImagePromptType,
        index=True,
    )
    style_profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("style_profile.id"), nullable=True
    )
    negative_prompt_preset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("image_prompt_preset.id"), nullable=True
    )
    generation_mode: Mapped[GenerationMode] = enum_column(
        GenerationMode,
        default=GenerationMode.PREVIEW,
        index=True,
    )
    spec_json: Mapped[str] = mapped_column(Text)
    positive_prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    required_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    spec_hash: Mapped[str] = mapped_column(String(64), index=True)
    compiler_key: Mapped[str] = mapped_column(String(120))
    compiler_version: Mapped[str] = mapped_column(String(64), default="1")
    created_at: Mapped[datetime] = mapped_column(AwareUTCDateTime(), default=utc_now)

    page: Mapped["ComicPage"] = relationship()
    snapshot: Mapped["VisualStateSnapshot"] = relationship()
    shot_plan: Mapped["PageShotPlan"] = relationship(back_populates="image_specs")
    style_profile: Mapped[Optional["StyleProfile"]] = relationship()
    generation_runs: Mapped[list["GenerationRun"]] = relationship(
        back_populates="image_spec"
    )


class GenerationRun(TimestampMixin, Base):
    """单个候选请求的完整生成溯源；GenerationTask 继续负责批量状态。"""

    __tablename__ = "generation_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation_task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id"), index=True
    )
    batch_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("generation_task.id"), nullable=True, index=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    image_spec_id: Mapped[int] = mapped_column(ForeignKey("image_spec.id"), index=True)
    tool_preset_id: Mapped[int] = mapped_column(
        ForeignKey("image_generation_tool_preset.id"), index=True
    )
    provider: Mapped[ImageGenerationProvider] = enum_column(
        ImageGenerationProvider,
        index=True,
    )
    prompt_type: Mapped[ImagePromptType] = enum_column(
        ImagePromptType,
        index=True,
    )
    candidate_index: Mapped[int] = mapped_column(Integer)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seed_applied: Mapped[bool] = mapped_column(Boolean, default=True)
    seed_strategy: Mapped[SeedStrategy] = enum_column(
        SeedStrategy,
        default=SeedStrategy.PER_PAGE,
    )
    generation_mode: Mapped[GenerationMode] = enum_column(
        GenerationMode,
        default=GenerationMode.PREVIEW,
    )
    status: Mapped[GenerationRunStatus] = enum_column(
        GenerationRunStatus,
        default=GenerationRunStatus.PENDING,
        index=True,
    )
    external_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    workflow_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workflow_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bindings_json: Mapped[str] = mapped_column(Text, default="{}")
    resolved_assets_json: Mapped[str] = mapped_column(Text, default="[]")
    degradation_json: Mapped[str] = mapped_column(Text, default="[]")
    applied_spec_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        AwareUTCDateTime(), nullable=True
    )

    generation_task: Mapped["GenerationTask"] = relationship(
        back_populates="runs",
        foreign_keys=[generation_task_id],
    )
    batch_task: Mapped[Optional["GenerationTask"]] = relationship(
        back_populates="batch_runs",
        foreign_keys=[batch_task_id],
    )
    page: Mapped["ComicPage"] = relationship()
    image_spec: Mapped["ImageSpec"] = relationship(back_populates="generation_runs")
    tool_preset: Mapped["ImageGenerationToolPreset"] = relationship()
    images: Mapped[list["ComicImage"]] = relationship(back_populates="generation_run")
