from datetime import datetime
from typing import Optional

from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.database import Base
from backend.models.enums import (
    ComicPageStatus,
    GenerationTaskStatus,
    ImagePromptPresetKind,
    OutlineVersionStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    SessionPurpose,
)


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


class TimestampMixin:
    """给需要时间戳的表复用 created_at / updated_at 字段。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    """图片 Prompt 通用配置表：维护脚本转图 SystemPrompt 和文生图 Negative Prompt。"""

    __tablename__ = "image_prompt_preset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[ImagePromptPresetKind] = enum_column(ImagePromptPresetKind, index=True)
    content: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["ComicProject"] = relationship(back_populates="outline_versions")
    session: Mapped["Session"] = relationship(back_populates="outline_versions")
    script_tasks: Mapped[list["ScriptGenerationTask"]] = relationship(
        back_populates="outline_version",
    )


class ComicPage(TimestampMixin, Base):
    """漫画页面表：保存单页脚本、图片 Prompt 和最终选择的候选图。"""

    __tablename__ = "comic_page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("script_section.id"),
        nullable=True,
        index=True,
    )
    page_no: Mapped[int] = mapped_column(Integer)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    characters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clothing: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    composition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    character_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dialogue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ComicPageStatus] = enum_column(
        ComicPageStatus,
        default=ComicPageStatus.DRAFT,
    )
    # selected_image_id 指向用户最终选择的候选图；未选择前为空。
    selected_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comic_image.id"),
        nullable=True,
    )

    project: Mapped["ComicProject"] = relationship(back_populates="pages")
    section: Mapped[Optional["ScriptSection"]] = relationship(back_populates="pages")
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
    """候选图片表：记录每页由 ComfyUI 生成的候选图片及其元信息。"""

    __tablename__ = "comic_image"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("comic_page.id"), index=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    page: Mapped["ComicPage"] = relationship(
        back_populates="images",
        foreign_keys=[page_id],
    )


class GenerationTask(TimestampMixin, Base):
    """生成任务表：记录提交到 ComfyUI 的任务状态和返回的 prompt_id。"""

    __tablename__ = "generation_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("comic_project.id"), index=True)
    page_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comic_page.id"), nullable=True)
    comfy_prompt_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[GenerationTaskStatus] = enum_column(
        GenerationTaskStatus,
        default=GenerationTaskStatus.PENDING,
    )
    batch_size: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["ComicProject"] = relationship(back_populates="tasks")
    page: Mapped[Optional["ComicPage"]] = relationship(back_populates="tasks")


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
    target_page_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_requirement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["ComicProject"] = relationship(back_populates="script_tasks")
    outline_version: Mapped[Optional["OutlineVersion"]] = relationship(
        back_populates="script_tasks",
    )
    sections: Mapped[list["ScriptSection"]] = relationship(
        back_populates="task",
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

    task: Mapped["ScriptGenerationTask"] = relationship(back_populates="sections")
    pages: Mapped[list["ComicPage"]] = relationship(back_populates="section")
