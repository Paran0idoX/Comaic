from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as SqlAlchemySession

from backend.models.comic import (
    AppSettings,
    ComicImage,
    ComicPage,
    ComicProject,
    GenerationTask,
    ImageGenerationToolPreset,
    ImagePromptPreset,
    LLMConfig,
    OutlineCharacter,
    OutlineVersion,
    ScriptCharacter,
    ScriptScene,
    ScriptSection,
    ScriptGenerationTask,
    Session as ComicSession,
)
from backend.models.enums import (
    ComicPageStatus,
    GenerationTaskStatus,
    ImageGenerationToolKind,
    ImagePromptPresetKind,
    LLMProvider,
    OutlineVersionStatus,
    PageScriptReviewStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
    SessionPurpose,
)
from backend.models.time import utc_now


KEEP_EXISTING_VALUE = object()


class ComicRepository:
    """漫画项目的数据访问层，只负责数据库读写。"""

    def __init__(self, session: SqlAlchemySession):
        """注入 SQLAlchemy session，方便外层控制事务生命周期。"""

        self.session = session

    def create_project(
        self,
        *,
        title: str,
    ) -> ComicProject:
        """创建漫画项目；不自动创建页面，页面由后续流程显式创建。"""

        project = ComicProject(
            title=title,
        )
        self.session.add(project)
        self.session.commit()
        self.session.refresh(project)
        return project

    def get_project(self, project_id: int) -> ComicProject | None:
        """根据主键读取项目，不存在时返回 None。"""

        return self.session.get(ComicProject, project_id)

    def list_projects(self) -> list[ComicProject]:
        """按最近更新时间倒序读取项目列表，供项目页展示。"""

        statement = select(ComicProject).order_by(ComicProject.updated_at.desc())
        return list(self.session.scalars(statement))

    def update_project(self, *, project_id: int, title: str) -> ComicProject:
        """更新项目基础信息；找不到项目时由上层转换为 404。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        project.title = title
        self.session.commit()
        self.session.refresh(project)
        return project

    def delete_project(self, project_id: int) -> None:
        """硬删除项目；关联会话、页面、任务依赖 ORM cascade 一并删除。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        self.session.delete(project)
        self.session.commit()

    def get_active_llm_config(self) -> LLMConfig | None:
        """读取当前启用的全局 LLM 配置；没有配置时返回 None。"""

        statement = (
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True))
            .order_by(LLMConfig.updated_at.desc(), LLMConfig.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_llm_config(self, config_id: int) -> LLMConfig | None:
        """按主键读取 LLM 配置。"""

        return self.session.get(LLMConfig, config_id)

    def list_llm_configs(self) -> list[LLMConfig]:
        """读取全部 LLM 配置，active 配置优先展示。"""

        statement = select(LLMConfig).order_by(
            LLMConfig.is_active.desc(),
            LLMConfig.updated_at.desc(),
            LLMConfig.id.desc(),
        )
        return list(self.session.scalars(statement))

    def create_llm_config(
        self,
        *,
        name: str,
        provider: LLMProvider,
        base_url: str,
        model_names: str,
        default_model: str,
        api_key: str | None,
        is_active: bool = True,
    ) -> LLMConfig:
        """创建一组 LLM API 配置；active 配置仍保持全局唯一。"""

        if is_active:
            self._deactivate_llm_configs()
        config = LLMConfig(
            name=name,
            provider=provider,
            base_url=base_url,
            model_names=model_names,
            default_model=default_model,
            api_key=api_key,
            is_active=is_active,
        )
        self.session.add(config)
        self.session.commit()
        self.session.refresh(config)
        return config

    def update_llm_config(
        self,
        *,
        config_id: int,
        name: str,
        provider: LLMProvider,
        base_url: str,
        model_names: str,
        default_model: str,
        api_key: str | None | object,
        clear_api_key: bool = False,
    ) -> LLMConfig:
        """更新一组 LLM API 配置；api_key 为 sentinel 时保留旧值。"""

        config = self.session.get(LLMConfig, config_id)
        if config is None:
            raise ValueError(f"LLMConfig not found: {config_id}")
        config.name = name
        config.provider = provider
        config.base_url = base_url
        config.model_names = model_names
        config.default_model = default_model
        if clear_api_key:
            config.api_key = None
        elif api_key is not KEEP_EXISTING_VALUE:
            config.api_key = str(api_key) if api_key is not None else None
        self.session.commit()
        self.session.refresh(config)
        return config

    def activate_llm_config(self, config_id: int) -> LLMConfig:
        """设置某组 LLM 配置为当前 active。"""

        config = self.session.get(LLMConfig, config_id)
        if config is None:
            raise ValueError(f"LLMConfig not found: {config_id}")
        self._deactivate_llm_configs()
        config.is_active = True
        self.session.commit()
        self.session.refresh(config)
        return config

    def delete_llm_config(self, config_id: int) -> None:
        """删除一组 LLM 配置；删除 active 时自动激活剩余最近配置。"""

        configs = self.list_llm_configs()
        if len(configs) <= 1:
            raise ValueError("Cannot delete the last LLMConfig.")
        config = self.session.get(LLMConfig, config_id)
        if config is None:
            raise ValueError(f"LLMConfig not found: {config_id}")
        was_active = config.is_active
        self.session.delete(config)
        self.session.flush()
        if was_active:
            fallback = self.session.scalar(
                select(LLMConfig)
                .order_by(LLMConfig.updated_at.desc(), LLMConfig.id.desc())
                .limit(1)
            )
            if fallback is not None:
                fallback.is_active = True
        self.session.commit()

    def _deactivate_llm_configs(self) -> None:
        """取消其它 LLM 配置的 active 状态，保持全局唯一。"""

        for config in self.session.scalars(
            select(LLMConfig).where(LLMConfig.is_active.is_(True))
        ):
            config.is_active = False

    def get_app_settings(self) -> AppSettings:
        """读取应用全局设置；首次访问时创建默认配置行。"""

        settings = self.session.get(AppSettings, 1)
        if settings is None:
            settings = AppSettings(id=1, script_section_max_concurrency=3)
            self.session.add(settings)
            self.session.commit()
            self.session.refresh(settings)
        return settings

    def update_app_settings(self, *, script_section_max_concurrency: int) -> AppSettings:
        """更新应用全局设置。"""

        settings = self.get_app_settings()
        settings.script_section_max_concurrency = script_section_max_concurrency
        self.session.commit()
        self.session.refresh(settings)
        return settings

    def create_session(
        self,
        *,
        project_id: int,
        thread_id: str,
        purpose: SessionPurpose,
    ) -> ComicSession:
        """为项目创建通用会话，thread_id 用于关联 Agent 记忆。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        session = ComicSession(
            project_id=project_id,
            thread_id=thread_id,
            purpose=purpose,
        )
        self.session.add(session)
        self.session.commit()
        self.session.refresh(session)
        return session

    def get_session_by_thread_id(self, thread_id: str) -> ComicSession | None:
        """通过公开的 thread_id 查找通用会话。"""

        statement = select(ComicSession).where(ComicSession.thread_id == thread_id)
        return self.session.scalar(statement)

    def get_latest_session(
        self,
        *,
        project_id: int,
        purpose: SessionPurpose,
    ) -> ComicSession | None:
        """读取项目下某类业务的最近会话，用于刷新页面后继续上下文。"""

        statement = (
            select(ComicSession)
            .where(
                ComicSession.project_id == project_id,
                ComicSession.purpose == purpose,
            )
            .order_by(ComicSession.updated_at.desc(), ComicSession.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_outline_version(
        self,
        *,
        session_id: int,
        content: str,
        keep_latest: int = 5,
    ) -> OutlineVersion:
        """保存新的大纲版本，并只保留该会话最近 keep_latest 个版本。"""

        session = self.session.get(ComicSession, session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        current_max_version = self.session.scalar(
            select(OutlineVersion.version_no)
            .where(OutlineVersion.session_id == session_id)
            .order_by(OutlineVersion.version_no.desc())
            .limit(1)
        )
        next_version_no = (current_max_version or 0) + 1

        # 同一个会话下只有最新版本保持 active，其余版本归档。
        active_versions = self.session.scalars(
            select(OutlineVersion).where(
                OutlineVersion.session_id == session_id,
                OutlineVersion.status == OutlineVersionStatus.ACTIVE,
            )
        )
        for version in active_versions:
            version.status = OutlineVersionStatus.ARCHIVED

        outline_version = OutlineVersion(
            project_id=session.project_id,
            session_id=session_id,
            version_no=next_version_no,
            content=content,
            status=OutlineVersionStatus.ACTIVE,
        )
        self.session.add(outline_version)
        self.session.flush()

        versions = list(
            self.session.scalars(
                select(OutlineVersion)
                .where(OutlineVersion.session_id == session_id)
                .order_by(OutlineVersion.version_no.desc())
            )
        )
        for old_version in versions[keep_latest:]:
            self.session.delete(old_version)

        self.session.commit()
        self.session.refresh(outline_version)
        return outline_version

    def list_outline_versions(self, session_id: int) -> list[OutlineVersion]:
        """按版本号升序读取某个会话保留的大纲版本。"""

        statement = (
            select(OutlineVersion)
            .where(OutlineVersion.session_id == session_id)
            .order_by(OutlineVersion.version_no)
        )
        return list(self.session.scalars(statement))

    def get_outline_version(self, outline_version_id: int) -> OutlineVersion | None:
        """根据主键读取大纲版本。"""

        return self.session.get(OutlineVersion, outline_version_id)

    def confirm_outline_version(self, outline_version_id: int) -> OutlineVersion:
        """确认大纲版本；脚本生成只允许使用已确认的大纲版本。"""

        outline_version = self.get_outline_version(outline_version_id)
        if outline_version is None:
            raise ValueError(f"OutlineVersion not found: {outline_version_id}")
        outline_version.confirmed_at = utc_now()
        self.session.commit()
        self.session.refresh(outline_version)
        return outline_version

    def list_outline_characters(self, outline_version_id: int) -> list[OutlineCharacter]:
        """读取大纲版本下的角色基准设定。"""

        statement = (
            select(OutlineCharacter)
            .where(OutlineCharacter.outline_version_id == outline_version_id)
            .order_by(OutlineCharacter.character_key, OutlineCharacter.id)
        )
        return list(self.session.scalars(statement))

    def get_outline_character_by_key(
        self,
        *,
        outline_version_id: int,
        character_key: str,
    ) -> OutlineCharacter | None:
        """按稳定 key 读取大纲版本内的角色基准设定。"""

        statement = select(OutlineCharacter).where(
            OutlineCharacter.outline_version_id == outline_version_id,
            OutlineCharacter.character_key == character_key,
        )
        return self.session.scalar(statement)

    def replace_outline_characters(
        self,
        *,
        outline_version_id: int,
        characters: list[dict],
    ) -> list[OutlineCharacter]:
        """替换某个大纲版本的角色基准设定草案。"""

        for character in self.list_outline_characters(outline_version_id):
            self.session.delete(character)
        self.session.flush()

        saved: list[OutlineCharacter] = []
        for payload in characters:
            character = OutlineCharacter(
                outline_version_id=outline_version_id,
                character_key=str(payload["character_key"]).strip(),
                name=str(payload.get("name", "")).strip(),
                role=str(payload.get("role", "")).strip(),
                background=str(payload.get("background", "")).strip(),
                appearance=str(payload.get("appearance", "")).strip(),
                visual_anchors=str(payload.get("visual_anchors", "")).strip(),
                negative_constraints=str(payload.get("negative_constraints", "")).strip(),
                default_hairstyle=str(payload.get("default_hairstyle", "")).strip(),
                default_clothing=str(payload.get("default_clothing", "")).strip(),
                default_accessories=str(payload.get("default_accessories", "")).strip(),
                default_color_palette=str(payload.get("default_color_palette", "")).strip(),
            )
            self.session.add(character)
            saved.append(character)

        self.session.commit()
        for character in saved:
            self.session.refresh(character)
        return saved

    def get_active_outline_version_for_project(self, project_id: int) -> OutlineVersion | None:
        """读取项目最近大纲会话中的 active 大纲版本。"""

        statement = (
            select(OutlineVersion)
            .where(
                OutlineVersion.project_id == project_id,
                OutlineVersion.status == OutlineVersionStatus.ACTIVE,
            )
            .order_by(OutlineVersion.created_at.desc(), OutlineVersion.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_script_task(
        self,
        *,
        project_id: int,
        mode: ScriptGenerationMode,
        total_pages: int,
        outline_version_id: int | None = None,
        target_page_no: int | None = None,
        user_requirement: str | None = None,
        status: ScriptGenerationTaskStatus = ScriptGenerationTaskStatus.PENDING,
    ) -> ScriptGenerationTask:
        """创建分页脚本生成任务，用于跟踪单页或批量生成状态。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        task = ScriptGenerationTask(
            project_id=project_id,
            outline_version_id=outline_version_id,
            status=status,
            mode=mode,
            total_pages=total_pages,
            target_page_no=target_page_no,
            user_requirement=user_requirement,
            heartbeat_at=utc_now() if status == ScriptGenerationTaskStatus.RUNNING else None,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def upsert_script_section(
        self,
        *,
        task_id: int,
        section_no: int,
        page_start: int,
        page_end: int,
        title: str = "",
        description: str = "",
    ) -> ScriptSection:
        """按任务和分段编号创建或更新故事节奏分段。"""

        task = self.session.get(ScriptGenerationTask, task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")

        section = self.get_script_section_by_no(task_id=task_id, section_no=section_no)
        if section is None:
            section = ScriptSection(
                task_id=task_id,
                section_no=section_no,
                page_start=page_start,
                page_end=page_end,
                title=title,
                description=description,
            )
            self.session.add(section)
        else:
            section.page_start = page_start
            section.page_end = page_end
            section.title = title
            section.description = description
            if section.status != ScriptSectionStatus.COMPLETED:
                section.status = ScriptSectionStatus.GENERATING
                section.error_message = None

        self.session.commit()
        self.session.refresh(section)
        return section

    def update_script_section_status(
        self,
        *,
        section_id: int,
        status: ScriptSectionStatus,
        error_message: str | None = None,
    ) -> ScriptSection:
        """更新分段生成状态，供继续生成和前端分段卡片使用。"""

        section = self.session.get(ScriptSection, section_id)
        if section is None:
            raise ValueError(f"ScriptSection not found: {section_id}")

        section.status = status
        section.error_message = error_message
        self.session.commit()
        self.session.refresh(section)
        return section

    def reset_script_section_for_generation(self, section_id: int) -> ScriptSection:
        """继续生成前把失败/未完成分段重新置为生成中。"""

        return self.update_script_section_status(
            section_id=section_id,
            status=ScriptSectionStatus.GENERATING,
            error_message=None,
        )

    def get_script_section_by_no(self, *, task_id: int, section_no: int) -> ScriptSection | None:
        """读取某个脚本任务下指定编号的分段。"""

        statement = select(ScriptSection).where(
            ScriptSection.task_id == task_id,
            ScriptSection.section_no == section_no,
        )
        return self.session.scalar(statement)

    def list_script_sections(self, task_id: int) -> list[ScriptSection]:
        """按分段编号读取脚本任务下的全部分段。"""

        statement = (
            select(ScriptSection)
            .where(ScriptSection.task_id == task_id)
            .order_by(ScriptSection.section_no)
        )
        return list(self.session.scalars(statement))

    def list_script_scenes(self, task_id: int) -> list[ScriptScene]:
        """读取某次脚本任务下的中心化场景设定。"""

        statement = (
            select(ScriptScene)
            .where(ScriptScene.task_id == task_id)
            .order_by(ScriptScene.scene_key, ScriptScene.id)
        )
        return list(self.session.scalars(statement))

    def list_script_characters(self, task_id: int) -> list[ScriptCharacter]:
        """读取某次脚本任务下所有分段角色设定。"""

        statement = (
            select(ScriptCharacter)
            .join(ScriptSection, ScriptCharacter.section_id == ScriptSection.id)
            .where(ScriptSection.task_id == task_id)
            .order_by(ScriptSection.section_no, ScriptCharacter.character_key, ScriptCharacter.id)
        )
        return list(self.session.scalars(statement))

    def list_script_section_characters(self, section_id: int) -> list[ScriptCharacter]:
        """读取某个分段内的角色细化设定。"""

        statement = (
            select(ScriptCharacter)
            .where(ScriptCharacter.section_id == section_id)
            .order_by(ScriptCharacter.character_key, ScriptCharacter.id)
        )
        return list(self.session.scalars(statement))

    def get_script_scene_by_key(self, *, task_id: int, scene_key: str) -> ScriptScene | None:
        """按稳定 key 读取任务内场景设定。"""

        statement = select(ScriptScene).where(
            ScriptScene.task_id == task_id,
            ScriptScene.scene_key == scene_key,
        )
        return self.session.scalar(statement)

    def get_script_character_by_key(
        self,
        *,
        section_id: int,
        character_key: str,
    ) -> ScriptCharacter | None:
        """按稳定 key 读取分段内角色设定。"""

        statement = select(ScriptCharacter).where(
            ScriptCharacter.section_id == section_id,
            ScriptCharacter.character_key == character_key,
        )
        return self.session.scalar(statement)

    def upsert_script_scene(self, *, task_id: int, **payload) -> ScriptScene:
        """创建或补充任务内场景设定；已有关键视觉锚点不被后续输出覆盖。"""

        scene_key = str(payload["scene_key"]).strip()
        scene = self.get_script_scene_by_key(task_id=task_id, scene_key=scene_key)
        if scene is None:
            scene = ScriptScene(task_id=task_id, scene_key=scene_key)
            self.session.add(scene)
        self._fill_empty_fields(
            scene,
            payload,
            [
                "name",
                "location_type",
                "time_of_day",
                "lighting",
                "weather",
                "environment_details",
                "color_palette",
                "visual_anchors",
                "negative_constraints",
            ],
        )
        self.session.commit()
        self.session.refresh(scene)
        return scene

    def upsert_script_character(self, *, task_id: int, **payload) -> ScriptCharacter:
        """兼容旧调用：按 payload 中的 section_id 保存分段角色设定。"""

        section_id = int(payload["section_id"])
        return self.upsert_script_section_character(section_id=section_id, **payload)

    def upsert_script_section_character(
        self,
        *,
        section_id: int,
        **payload,
    ) -> ScriptCharacter:
        """创建或补充分段内角色设定；大纲基准锚点不在这里被覆盖。"""

        character_key = str(payload["character_key"]).strip()
        character = self.get_script_character_by_key(
            section_id=section_id,
            character_key=character_key,
        )
        if character is None:
            character = ScriptCharacter(section_id=section_id, character_key=character_key)
            self.session.add(character)
        outline_character_id = payload.get("outline_character_id")
        if outline_character_id is not None:
            character.outline_character_id = int(outline_character_id)
        self._fill_empty_fields(
            character,
            payload,
            [
                "name",
                "section_role",
                "current_hairstyle",
                "current_clothing",
                "current_accessories",
                "current_state",
                "emotion",
                "temporary_changes",
                "visual_anchors",
                "negative_constraints",
            ],
        )
        self.session.commit()
        self.session.refresh(character)
        return character

    def has_script_sections(self, task_id: int) -> bool:
        """判断任务是否已有分段；用于实现分段计划首次注册后锁定。"""

        statement = select(ScriptSection.id).where(ScriptSection.task_id == task_id).limit(1)
        return self.session.scalar(statement) is not None

    def get_script_section_signature(self, task_id: int) -> tuple[tuple[int, int, int], ...] | None:
        """从数据库读取分段锁定签名，只比较分段编号和页码范围。"""

        sections = self.list_script_sections(task_id)
        if not sections:
            return None
        return tuple(
            (section.section_no, section.page_start, section.page_end)
            for section in sections
        )

    def list_script_task_pages(self, task_id: int) -> list[ComicPage]:
        """读取某次脚本任务下已经挂载到分段的页面脚本。"""

        statement = (
            select(ComicPage)
            .join(ScriptSection, ComicPage.section_id == ScriptSection.id)
            .where(ScriptSection.task_id == task_id)
            .order_by(ComicPage.page_no)
        )
        return list(self.session.scalars(statement))

    def list_script_task_page_nos(self, task_id: int) -> set[int]:
        """读取某次任务已经保存的页码集合，供兜底保存时去重。"""

        return {page.page_no for page in self.list_script_task_pages(task_id) if page.summary}

    def get_script_task_page(self, *, task_id: int, page_no: int) -> ComicPage | None:
        """读取某次任务下指定页码的页面脚本。"""

        statement = (
            select(ComicPage)
            .join(ScriptSection, ComicPage.section_id == ScriptSection.id)
            .where(
                ScriptSection.task_id == task_id,
                ComicPage.page_no == page_no,
            )
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_script_section_page(self, *, section_id: int, page_no: int) -> ComicPage | None:
        """读取某个分段下指定页码页面，用于任务维度 upsert 避免跨任务覆盖。"""

        statement = select(ComicPage).where(
            ComicPage.section_id == section_id,
            ComicPage.page_no == page_no,
        )
        return self.session.scalar(statement)

    def list_script_section_page_nos(self, section_id: int) -> set[int]:
        """读取某个分段下已有脚本的页码集合，用于判断分段完成度。"""

        statement = select(ComicPage.page_no).where(
            ComicPage.section_id == section_id,
            ComicPage.summary.is_not(None),
        )
        return set(self.session.scalars(statement))

    def list_script_section_passed_page_nos(self, section_id: int) -> set[int]:
        """读取某个分段下已经审查通过的页码集合。"""

        statement = select(ComicPage.page_no).where(
            ComicPage.section_id == section_id,
            ComicPage.summary.is_not(None),
            ComicPage.script_review_status == PageScriptReviewStatus.PASSED,
        )
        return set(self.session.scalars(statement))

    def list_script_section_unpassed_page_nos(self, section_id: int) -> list[int]:
        """读取分段内缺失或未审查通过的页码，继续生成只处理这些页面。"""

        section = self.session.get(ScriptSection, section_id)
        if section is None:
            raise ValueError(f"ScriptSection not found: {section_id}")

        passed_page_nos = self.list_script_section_passed_page_nos(section_id)
        return [
            page_no
            for page_no in range(section.page_start, section.page_end + 1)
            if page_no not in passed_page_nos
        ]

    def is_script_section_completed(self, section_id: int) -> bool:
        """判断分段内 page_start 到 page_end 的页面脚本是否全部审查通过。"""

        section = self.session.get(ScriptSection, section_id)
        if section is None:
            raise ValueError(f"ScriptSection not found: {section_id}")

        saved_page_nos = self.list_script_section_passed_page_nos(section_id)
        expected_page_nos = set(range(section.page_start, section.page_end + 1))
        return expected_page_nos.issubset(saved_page_nos)

    def delete_script_task_sections(self, task_id: int) -> None:
        """硬删除脚本任务下全部分段，以及这些分段下的页面行。"""

        task = self.session.get(ScriptGenerationTask, task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")

        sections = self.list_script_sections(task_id)
        if not sections:
            return

        pages = [page for section in sections for page in section.pages]
        page_ids = [page.id for page in pages]
        if page_ids:
            # 出图任务是历史记录，删除页面前先断开外键，避免引用已删除页面。
            tasks = self.session.scalars(
                select(GenerationTask).where(GenerationTask.page_id.in_(page_ids))
            )
            for generation_task in tasks:
                generation_task.page_id = None

        for page in pages:
            # 断开最终选中图引用后再删除页面，让候选图级联删除更稳定。
            page.selected_image_id = None
            page.visual_characters = []
            self.session.delete(page)

        for section in sections:
            self.session.delete(section)

        self.session.commit()

    def find_section_for_page(self, *, task_id: int, page_no: int) -> ScriptSection | None:
        """按页码查找所属分段，用于人工新增脚本时自动挂载分段。"""

        statement = (
            select(ScriptSection)
            .where(
                ScriptSection.task_id == task_id,
                ScriptSection.page_start <= page_no,
                ScriptSection.page_end >= page_no,
            )
            .order_by(ScriptSection.section_no)
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_latest_script_task_for_project(self, project_id: int) -> ScriptGenerationTask | None:
        """读取项目最近一次脚本任务，人工新增页面时可复用其分段。"""

        statement = (
            select(ScriptGenerationTask)
            .where(ScriptGenerationTask.project_id == project_id)
            .order_by(ScriptGenerationTask.created_at.desc(), ScriptGenerationTask.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_script_task(self, task_id: int) -> ScriptGenerationTask | None:
        """根据主键读取分页脚本生成任务。"""

        return self.session.get(ScriptGenerationTask, task_id)

    def list_script_tasks(
        self,
        *,
        project_id: int | None = None,
        outline_version_id: int | None = None,
        mode: ScriptGenerationMode | None = None,
        status: ScriptGenerationTaskStatus | None = None,
    ) -> list[ScriptGenerationTask]:
        """读取脚本生成任务列表，供后续 Prompt 生成选择已完成任务。"""

        statement = select(ScriptGenerationTask)
        if project_id is not None:
            statement = statement.where(ScriptGenerationTask.project_id == project_id)
        if outline_version_id is not None:
            statement = statement.where(ScriptGenerationTask.outline_version_id == outline_version_id)
        if mode is not None:
            statement = statement.where(ScriptGenerationTask.mode == mode)
        if status is not None:
            statement = statement.where(ScriptGenerationTask.status == status)
        statement = statement.order_by(
            ScriptGenerationTask.updated_at.desc(),
            ScriptGenerationTask.id.desc(),
        )
        return list(self.session.scalars(statement))

    def get_script_task_status(self, task_id: int) -> ScriptGenerationTaskStatus | None:
        """从数据库刷新读取脚本任务状态，供长 SSE 连接感知外部暂停。"""

        # 长任务持有的 session 可能缓存了旧 ORM 对象；先过期再读取最新状态。
        self.session.expire_all()
        task = self.session.get(ScriptGenerationTask, task_id)
        return None if task is None else task.status

    def suspend_script_task(self, task_id: int) -> ScriptGenerationTask:
        """暂停脚本任务；接口保持幂等，非 running 任务直接返回当前状态。"""

        task = self.session.get(ScriptGenerationTask, task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if task.status == ScriptGenerationTaskStatus.RUNNING:
            task.status = ScriptGenerationTaskStatus.SUSPENDED
            task.error_message = "任务已暂停。"
            self.session.commit()
            self.session.refresh(task)
        return task

    def update_script_task(
        self,
        *,
        task_id: int,
        status: ScriptGenerationTaskStatus | None = None,
        section_plan: str | None = None,
        error_message: str | None = None,
        heartbeat_at: datetime | None = None,
    ) -> ScriptGenerationTask:
        """更新分页脚本任务状态和过程信息。"""

        task = self.session.get(ScriptGenerationTask, task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if status is not None:
            task.status = status
            if status == ScriptGenerationTaskStatus.RUNNING:
                task.heartbeat_at = heartbeat_at or utc_now()
        if section_plan is not None:
            task.section_plan = section_plan
        if error_message is not None:
            task.error_message = error_message
        if heartbeat_at is not None:
            task.heartbeat_at = heartbeat_at
        self.session.commit()
        self.session.refresh(task)
        return task

    def update_running_task_heartbeats(
        self,
        *,
        script_task_ids: set[int],
        generation_task_ids: set[int],
        heartbeat_at: datetime,
    ) -> tuple[int, int]:
        """刷新当前进程注册的 running 任务心跳，避免给旧僵尸任务续命。"""

        script_count = 0
        if script_task_ids:
            statement = select(ScriptGenerationTask).where(
                ScriptGenerationTask.id.in_(script_task_ids),
                ScriptGenerationTask.status == ScriptGenerationTaskStatus.RUNNING,
            )
            for task in self.session.scalars(statement):
                task.heartbeat_at = heartbeat_at
                script_count += 1

        generation_count = 0
        if generation_task_ids:
            statement = select(GenerationTask).where(
                GenerationTask.id.in_(generation_task_ids),
                GenerationTask.status == GenerationTaskStatus.RUNNING,
            )
            for task in self.session.scalars(statement):
                task.heartbeat_at = heartbeat_at
                generation_count += 1

        if script_count or generation_count:
            self.session.commit()
        return script_count, generation_count

    def suspend_stale_running_tasks(
        self,
        *,
        stale_before: datetime,
        error_message: str,
    ) -> tuple[int, int]:
        """把心跳超时的 running 任务改为 suspended，供用户后续继续生成。"""

        script_statement = select(ScriptGenerationTask).where(
            ScriptGenerationTask.status == ScriptGenerationTaskStatus.RUNNING,
            or_(
                ScriptGenerationTask.heartbeat_at.is_(None),
                ScriptGenerationTask.heartbeat_at < stale_before,
            ),
        )
        script_count = 0
        for task in self.session.scalars(script_statement):
            task.status = ScriptGenerationTaskStatus.SUSPENDED
            task.error_message = error_message
            script_count += 1

        generation_statement = select(GenerationTask).where(
            GenerationTask.status == GenerationTaskStatus.RUNNING,
            or_(
                GenerationTask.heartbeat_at.is_(None),
                GenerationTask.heartbeat_at < stale_before,
            ),
        )
        generation_count = 0
        for task in self.session.scalars(generation_statement):
            task.status = GenerationTaskStatus.SUSPENDED
            task.error_message = error_message
            generation_count += 1

        if script_count or generation_count:
            self.session.commit()
        return script_count, generation_count

    def list_project_pages(self, project_id: int) -> list[ComicPage]:
        """按页码顺序读取某个项目的全部页面。"""

        statement = (
            select(ComicPage)
            .where(ComicPage.project_id == project_id)
            .order_by(ComicPage.page_no)
        )
        return list(self.session.scalars(statement))

    def create_page(self, *, project_id: int, page_no: int) -> ComicPage:
        """为指定项目创建单个页面。"""

        # 先确认项目存在，避免创建指向无效 project_id 的页面。
        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        page = ComicPage(project_id=project_id, page_no=page_no)
        self.session.add(page)
        self.session.commit()
        self.session.refresh(page)
        return page

    def get_project_page(self, *, project_id: int, page_no: int) -> ComicPage | None:
        """读取项目下指定页码的页面。"""

        statement = select(ComicPage).where(
            ComicPage.project_id == project_id,
            ComicPage.page_no == page_no,
        )
        return self.session.scalar(statement)

    def upsert_page_script(
        self,
        *,
        project_id: int,
        page_no: int,
        summary: str,
        characters: str,
        clothing: str,
        scene: str,
        composition: str,
        character_action: str,
        dialogue: str,
        section_id: int | None = None,
        scene_id: int | None = None,
        character_ids: list[int] | None = None,
        script_review_status: PageScriptReviewStatus = PageScriptReviewStatus.UNREVIEWED,
        script_review_error: str | None = None,
    ) -> ComicPage:
        """按页码创建或更新结构化页面脚本，并标记为脚本已生成。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        page = (
            self.get_script_section_page(section_id=section_id, page_no=page_no)
            if section_id is not None
            else self.get_project_page(project_id=project_id, page_no=page_no)
        )
        if page is None:
            page = ComicPage(project_id=project_id, page_no=page_no, section_id=section_id)
            self.session.add(page)
        elif section_id is not None:
            page.section_id = section_id

        page.summary = summary
        page.characters = characters
        page.clothing = clothing
        page.scene = scene
        page.composition = composition
        page.character_action = character_action
        page.dialogue = dialogue
        page.scene_id = scene_id
        if character_ids is not None:
            page.visual_characters = list(
                self.session.scalars(
                    select(ScriptCharacter).where(ScriptCharacter.id.in_(character_ids))
                )
            )
        page.status = ComicPageStatus.SCRIPT_READY
        page.script_review_status = script_review_status
        page.script_review_error = script_review_error
        self.session.commit()
        self.session.refresh(page)
        return page

    def update_page_script_review_status(
        self,
        *,
        page_id: int,
        status: PageScriptReviewStatus,
        error_message: str | None = None,
    ) -> ComicPage:
        """更新单页脚本审查状态。"""

        page = self.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")

        page.script_review_status = status
        page.script_review_error = error_message
        self.session.commit()
        self.session.refresh(page)
        return page

    def update_section_pages_review_status(
        self,
        *,
        section_id: int,
        page_nos: list[int],
        status: PageScriptReviewStatus,
        error_message: str | None = None,
    ) -> list[ComicPage]:
        """批量更新一个分段内指定页码的脚本审查状态。"""

        if not page_nos:
            return []
        pages = list(
            self.session.scalars(
                select(ComicPage).where(
                    ComicPage.section_id == section_id,
                    ComicPage.page_no.in_(page_nos),
                )
            )
        )
        for page in pages:
            page.script_review_status = status
            page.script_review_error = error_message
        self.session.commit()
        for page in pages:
            self.session.refresh(page)
        return pages

    def mark_section_pages_review_failed(
        self,
        *,
        project_id: int,
        section_id: int,
        page_nos: list[int],
        error_message: str,
    ) -> list[ComicPage]:
        """把分段内指定页面标记为脚本异常；缺失页面创建空占位，便于前端展示和继续生成。"""

        pages: list[ComicPage] = []
        for page_no in sorted(set(page_nos)):
            page = self.get_script_section_page(section_id=section_id, page_no=page_no)
            if page is None:
                page = ComicPage(
                    project_id=project_id,
                    section_id=section_id,
                    page_no=page_no,
                    status=ComicPageStatus.DRAFT,
                )
                self.session.add(page)
            page.script_review_status = PageScriptReviewStatus.FAILED
            page.script_review_error = error_message
            pages.append(page)
        self.session.commit()
        for page in pages:
            self.session.refresh(page)
        return pages

    def clear_page_script(self, *, project_id: int, page_no: int) -> ComicPage:
        """清空指定页脚本；保留页面记录，便于后续继续关联 Prompt 和图片。"""

        page = self.get_project_page(project_id=project_id, page_no=page_no)
        if page is None:
            raise ValueError(f"ComicPage not found for project {project_id}: {page_no}")
        return self.clear_page_script_by_id(page.id)

    def clear_page_script_by_id(self, page_id: int) -> ComicPage:
        """按页面主键清空脚本，避免同项目同页码多任务时误改其它任务。"""

        page = self.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")

        page.summary = None
        page.characters = None
        page.clothing = None
        page.scene = None
        page.composition = None
        page.character_action = None
        page.dialogue = None
        page.scene_id = None
        page.visual_characters = []
        page.status = ComicPageStatus.DRAFT
        page.script_review_status = PageScriptReviewStatus.UNREVIEWED
        page.script_review_error = None
        self.session.commit()
        self.session.refresh(page)
        return page

    def delete_project_pages(self, project_id: int) -> None:
        """硬删除项目下全部页面行，并解除出图任务对这些页面的引用。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        pages = self.list_project_pages(project_id)
        if not pages:
            return

        page_ids = [page.id for page in pages]
        # 出图任务是任务历史，不随页面批量删除一起删除；先置空外键避免约束冲突。
        tasks = self.session.scalars(
            select(GenerationTask).where(GenerationTask.page_id.in_(page_ids))
        )
        for task in tasks:
            task.page_id = None

        for page in pages:
            # 页面和候选图之间存在最终选中图的额外引用，删除前先断开更稳妥。
            page.selected_image_id = None
            page.visual_characters = []
            self.session.delete(page)

        self.session.commit()

    def update_page_prompt(self, page_id: int, image_prompt: str) -> ComicPage:
        """保存页面图片 Prompt，并把页面状态推进到 Prompt 已生成。"""

        page = self.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        page.image_prompt = image_prompt
        page.status = ComicPageStatus.PROMPT_READY
        self.session.commit()
        self.session.refresh(page)
        return page

    def get_page(self, page_id: int) -> ComicPage | None:
        """按主键读取页面，供页面级 Prompt/图片生成操作使用。"""

        return self.session.get(ComicPage, page_id)

    @staticmethod
    def _fill_empty_fields(target, payload: dict, field_names: list[str]) -> None:
        """只填充空字段，避免后续分段改写已建立的视觉锚点。"""

        for field_name in field_names:
            current_value = str(getattr(target, field_name, "") or "").strip()
            next_value = str(payload.get(field_name, "") or "").strip()
            if not current_value and next_value:
                setattr(target, field_name, next_value)

    def clear_script_task_image_prompts(self, task_id: int) -> None:
        """清空某次脚本任务下所有页面的图片 Prompt，重新生成前避免新旧 Prompt 混用。"""

        for page in self.list_script_task_pages(task_id):
            page.image_prompt = None
            if page.summary:
                page.status = ComicPageStatus.SCRIPT_READY
        self.session.commit()

    def list_image_prompt_presets(
        self,
        kind: ImagePromptPresetKind | None = None,
    ) -> list[ImagePromptPreset]:
        """读取图片 Prompt 配置列表，可按类型筛选。"""

        statement = select(ImagePromptPreset)
        if kind is not None:
            statement = statement.where(ImagePromptPreset.kind == kind)
        statement = statement.order_by(
            ImagePromptPreset.kind,
            ImagePromptPreset.is_default.desc(),
            ImagePromptPreset.updated_at.desc(),
            ImagePromptPreset.id.desc(),
        )
        return list(self.session.scalars(statement))

    def get_image_prompt_preset(self, preset_id: int) -> ImagePromptPreset | None:
        """根据主键读取图片 Prompt 配置。"""

        return self.session.get(ImagePromptPreset, preset_id)

    def get_default_image_prompt_preset(
        self,
        kind: ImagePromptPresetKind,
    ) -> ImagePromptPreset | None:
        """读取某个类型下的默认图片 Prompt 配置。"""

        statement = (
            select(ImagePromptPreset)
            .where(
                ImagePromptPreset.kind == kind,
                ImagePromptPreset.is_default.is_(True),
            )
            .order_by(ImagePromptPreset.updated_at.desc(), ImagePromptPreset.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_image_prompt_preset(
        self,
        *,
        name: str,
        kind: ImagePromptPresetKind,
        content: str,
        description: str | None = None,
        is_default: bool = False,
    ) -> ImagePromptPreset:
        """创建图片 Prompt 配置；默认配置在同类型下保持唯一。"""

        if is_default:
            self._clear_default_image_prompt_presets(kind)
        preset = ImagePromptPreset(
            name=name,
            description=description,
            kind=kind,
            content=content,
            is_default=is_default,
        )
        self.session.add(preset)
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def update_image_prompt_preset(
        self,
        *,
        preset_id: int,
        name: str,
        kind: ImagePromptPresetKind,
        content: str,
        description: str | None = None,
        is_default: bool = False,
    ) -> ImagePromptPreset:
        """更新图片 Prompt 配置；切换默认时只影响同类型配置。"""

        preset = self.session.get(ImagePromptPreset, preset_id)
        if preset is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        if is_default:
            self._clear_default_image_prompt_presets(kind, except_preset_id=preset_id)
        preset.name = name
        preset.description = description
        preset.kind = kind
        preset.content = content
        preset.is_default = is_default
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def delete_image_prompt_preset(self, preset_id: int) -> None:
        """删除图片 Prompt 配置；已保存到页面的 Prompt 不受影响。"""

        preset = self.session.get(ImagePromptPreset, preset_id)
        if preset is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        self.session.delete(preset)
        self.session.commit()

    def list_image_generation_tool_presets(
        self,
        *,
        kind: ImageGenerationToolKind | None = None,
    ) -> list[ImageGenerationToolPreset]:
        """读取通用生图工具配置，默认配置排在前面。"""

        statement = select(ImageGenerationToolPreset)
        if kind is not None:
            statement = statement.where(ImageGenerationToolPreset.kind == kind)
        statement = statement.order_by(
            ImageGenerationToolPreset.is_default.desc(),
            ImageGenerationToolPreset.updated_at.desc(),
            ImageGenerationToolPreset.id.desc(),
        )
        return list(self.session.scalars(statement))

    def get_image_generation_tool_preset(self, preset_id: int) -> ImageGenerationToolPreset | None:
        """根据主键读取通用生图工具配置。"""

        return self.session.get(ImageGenerationToolPreset, preset_id)

    def create_image_generation_tool_preset(
        self,
        *,
        name: str,
        kind: ImageGenerationToolKind,
        description: str | None = None,
        is_default: bool = False,
        comfy_base_url: str | None = None,
        workflow_json: str | None = None,
        positive_node_id: str | None = None,
        positive_input_name: str | None = None,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
        api_base_url: str | None = None,
        endpoint_path: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        size: str | None = None,
        response_format: str | None = None,
        seed_field_name: str | None = None,
        negative_prompt_field_name: str | None = None,
        extra_body_json: str | None = None,
    ) -> ImageGenerationToolPreset:
        """创建通用生图工具配置；同一时间只保留一个默认配置。"""

        if is_default:
            self._clear_default_image_generation_tool_presets()
        preset = ImageGenerationToolPreset(
            name=name,
            description=description,
            kind=kind,
            is_default=is_default,
            comfy_base_url=comfy_base_url,
            workflow_json=workflow_json,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=negative_node_id,
            negative_input_name=negative_input_name,
            seed_node_id=seed_node_id,
            seed_input_name=seed_input_name,
            api_base_url=api_base_url,
            endpoint_path=endpoint_path,
            api_key=api_key,
            model=model,
            size=size,
            response_format=response_format,
            seed_field_name=seed_field_name,
            negative_prompt_field_name=negative_prompt_field_name,
            extra_body_json=extra_body_json,
        )
        self.session.add(preset)
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def update_image_generation_tool_preset(
        self,
        *,
        preset_id: int,
        name: str,
        kind: ImageGenerationToolKind,
        description: str | None = None,
        is_default: bool = False,
        comfy_base_url: str | None = None,
        workflow_json: str | None = None,
        positive_node_id: str | None = None,
        positive_input_name: str | None = None,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
        api_base_url: str | None = None,
        endpoint_path: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        size: str | None = None,
        response_format: str | None = None,
        seed_field_name: str | None = None,
        negative_prompt_field_name: str | None = None,
        extra_body_json: str | None = None,
    ) -> ImageGenerationToolPreset:
        """更新通用生图工具配置。"""

        preset = self.session.get(ImageGenerationToolPreset, preset_id)
        if preset is None:
            raise ValueError(f"ImageGenerationToolPreset not found: {preset_id}")
        if is_default:
            self._clear_default_image_generation_tool_presets(except_preset_id=preset_id)
        preset.name = name
        preset.description = description
        preset.kind = kind
        preset.is_default = is_default
        preset.comfy_base_url = comfy_base_url
        preset.workflow_json = workflow_json
        preset.positive_node_id = positive_node_id
        preset.positive_input_name = positive_input_name
        preset.negative_node_id = negative_node_id
        preset.negative_input_name = negative_input_name
        preset.seed_node_id = seed_node_id
        preset.seed_input_name = seed_input_name
        preset.api_base_url = api_base_url
        preset.endpoint_path = endpoint_path
        preset.api_key = api_key
        preset.model = model
        preset.size = size
        preset.response_format = response_format
        preset.seed_field_name = seed_field_name
        preset.negative_prompt_field_name = negative_prompt_field_name
        preset.extra_body_json = extra_body_json
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def delete_image_generation_tool_preset(self, preset_id: int) -> None:
        """删除通用生图工具配置；已生成图片不受影响。"""

        preset = self.session.get(ImageGenerationToolPreset, preset_id)
        if preset is None:
            raise ValueError(f"ImageGenerationToolPreset not found: {preset_id}")
        self.session.delete(preset)
        self.session.commit()

    def _clear_default_image_generation_tool_presets(
        self,
        except_preset_id: int | None = None,
    ) -> None:
        """确保生图工具只有一个默认项。"""

        statement = select(ImageGenerationToolPreset).where(ImageGenerationToolPreset.is_default.is_(True))
        for preset in self.session.scalars(statement):
            if except_preset_id is not None and preset.id == except_preset_id:
                continue
            preset.is_default = False

    def list_comfy_workflow_presets(self) -> list[ImageGenerationToolPreset]:
        """旧接口别名：读取 ComfyUI 类型生图工具。"""

        return self.list_image_generation_tool_presets(kind=ImageGenerationToolKind.COMFYUI)

    def get_comfy_workflow_preset(self, preset_id: int) -> ImageGenerationToolPreset | None:
        """旧接口别名：读取 ComfyUI 类型生图工具。"""

        preset = self.get_image_generation_tool_preset(preset_id)
        if preset is None or preset.kind != ImageGenerationToolKind.COMFYUI:
            return None
        return preset

    def create_comfy_workflow_preset(
        self,
        *,
        name: str,
        workflow_json: str,
        positive_node_id: str,
        positive_input_name: str,
        description: str | None = None,
        is_default: bool = False,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
    ) -> ImageGenerationToolPreset:
        """旧接口别名：创建 ComfyUI 类型生图工具。"""

        return self.create_image_generation_tool_preset(
            name=name,
            description=description,
            kind=ImageGenerationToolKind.COMFYUI,
            is_default=is_default,
            workflow_json=workflow_json,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=negative_node_id,
            negative_input_name=negative_input_name,
            seed_node_id=seed_node_id,
            seed_input_name=seed_input_name,
        )

    def update_comfy_workflow_preset(
        self,
        *,
        preset_id: int,
        name: str,
        workflow_json: str,
        positive_node_id: str,
        positive_input_name: str,
        description: str | None = None,
        is_default: bool = False,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
    ) -> ImageGenerationToolPreset:
        """旧接口别名：更新 ComfyUI 类型生图工具。"""

        return self.update_image_generation_tool_preset(
            preset_id=preset_id,
            name=name,
            description=description,
            kind=ImageGenerationToolKind.COMFYUI,
            is_default=is_default,
            workflow_json=workflow_json,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=negative_node_id,
            negative_input_name=negative_input_name,
            seed_node_id=seed_node_id,
            seed_input_name=seed_input_name,
        )

    def delete_comfy_workflow_preset(self, preset_id: int) -> None:
        """旧接口别名：删除 ComfyUI 类型生图工具。"""

        self.delete_image_generation_tool_preset(preset_id)

    def _clear_default_image_prompt_presets(
        self,
        kind: ImagePromptPresetKind,
        except_preset_id: int | None = None,
    ) -> None:
        """同一类型下只保留一个默认配置。"""

        statement = select(ImagePromptPreset).where(
            ImagePromptPreset.kind == kind,
            ImagePromptPreset.is_default.is_(True),
        )
        for preset in self.session.scalars(statement):
            if except_preset_id is not None and preset.id == except_preset_id:
                continue
            preset.is_default = False

    def add_image(
        self,
        *,
        page_id: int,
        prompt: str,
        negative_prompt: str | None = None,
        image_url: str | None = None,
        local_path: str | None = None,
        seed: int | None = None,
        workflow_name: str | None = None,
    ) -> ComicImage:
        """保存某一页的一张候选图片。"""

        image = ComicImage(
            page_id=page_id,
            prompt=prompt,
            negative_prompt=negative_prompt,
            image_url=image_url,
            local_path=local_path,
            seed=seed,
            workflow_name=workflow_name,
        )
        self.session.add(image)
        self.session.commit()
        self.session.refresh(image)
        return image

    def list_page_images(self, page_id: int) -> list[ComicImage]:
        """读取某页所有生成图片，供图片生成页面回显。"""

        statement = (
            select(ComicImage)
            .where(ComicImage.page_id == page_id)
            .order_by(ComicImage.created_at.desc(), ComicImage.id.desc())
        )
        return list(self.session.scalars(statement))

    def mark_page_image_ready(self, page_id: int) -> ComicPage:
        """页面已有生成图片时推进页面状态；已选中最终图时不降级状态。"""

        page = self.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        if page.status != ComicPageStatus.IMAGE_SELECTED:
            page.status = ComicPageStatus.IMAGE_READY
        self.session.commit()
        self.session.refresh(page)
        return page

    def select_image(self, page_id: int, image_id: int) -> ComicPage:
        """人工选择某一页的最终图片，并取消同页其他候选图的选中状态。"""

        page = self.session.get(ComicPage, page_id)
        image = self.session.get(ComicImage, image_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        if image is None or image.page_id != page_id:
            raise ValueError(f"ComicImage not found for page {page_id}: {image_id}")

        # 同一页只能有一张最终图，所以这里会同步重置所有候选图。
        for candidate in page.images:
            candidate.is_selected = candidate.id == image_id

        page.selected_image_id = image_id
        page.status = ComicPageStatus.IMAGE_SELECTED
        self.session.commit()
        self.session.refresh(page)
        return page

    def create_generation_task(
        self,
        *,
        project_id: int,
        page_id: int | None,
        batch_size: int = 1,
        comfy_prompt_id: str | None = None,
        status: GenerationTaskStatus = GenerationTaskStatus.PENDING,
    ) -> GenerationTask:
        """记录一次出图任务，后续可根据 comfy_prompt_id 查询任务结果。"""

        task = GenerationTask(
            project_id=project_id,
            page_id=page_id,
            batch_size=batch_size,
            comfy_prompt_id=comfy_prompt_id,
            status=status,
            heartbeat_at=utc_now() if status == GenerationTaskStatus.RUNNING else None,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def get_generation_task(self, task_id: int) -> GenerationTask | None:
        """根据主键读取 ComfyUI 生成任务。"""

        return self.session.get(GenerationTask, task_id)

    def get_generation_task_status(self, task_id: int) -> GenerationTaskStatus | None:
        """刷新读取图片生成任务状态，供 SSE 长连接感知暂停。"""

        self.session.expire_all()
        task = self.session.get(GenerationTask, task_id)
        return None if task is None else task.status

    def suspend_generation_task(self, task_id: int) -> GenerationTask:
        """暂停图片生成批量任务；非 running 任务保持原状态返回。"""

        task = self.session.get(GenerationTask, task_id)
        if task is None:
            raise ValueError(f"GenerationTask not found: {task_id}")
        if task.status == GenerationTaskStatus.RUNNING:
            task.status = GenerationTaskStatus.SUSPENDED
            task.error_message = "任务已暂停。"
            self.session.commit()
            self.session.refresh(task)
        return task

    def update_generation_task(
        self,
        *,
        task_id: int,
        status: GenerationTaskStatus | None = None,
        comfy_prompt_id: str | None = None,
        error_message: str | None = None,
        heartbeat_at: datetime | None = None,
    ) -> GenerationTask:
        """更新 ComfyUI 生成任务状态和外部 prompt_id。"""

        task = self.session.get(GenerationTask, task_id)
        if task is None:
            raise ValueError(f"GenerationTask not found: {task_id}")
        if status is not None:
            task.status = status
            if status == GenerationTaskStatus.RUNNING:
                task.heartbeat_at = heartbeat_at or utc_now()
        if comfy_prompt_id is not None:
            task.comfy_prompt_id = comfy_prompt_id
        if error_message is not None:
            task.error_message = error_message
        if heartbeat_at is not None:
            task.heartbeat_at = heartbeat_at
        self.session.commit()
        self.session.refresh(task)
        return task
