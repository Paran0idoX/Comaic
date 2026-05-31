from sqlalchemy import select
from sqlalchemy.orm import Session as SqlAlchemySession

from backend.models.comic import (
    ComicImage,
    ComicPage,
    ComicProject,
    GenerationTask,
    OutlineVersion,
    ScriptGenerationTask,
    Session as ComicSession,
)
from backend.models.enums import (
    ComicPageStatus,
    OutlineVersionStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    SessionPurpose,
)


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

    def get_active_outline_version_for_project(self, project_id: int) -> OutlineVersion | None:
        """读取项目最近大纲会话中的 active 大纲版本。"""

        statement = (
            select(OutlineVersion)
            .join(ComicSession, OutlineVersion.session_id == ComicSession.id)
            .where(
                ComicSession.project_id == project_id,
                ComicSession.purpose == SessionPurpose.OUTLINE,
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
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def get_script_task(self, task_id: int) -> ScriptGenerationTask | None:
        """根据主键读取分页脚本生成任务。"""

        return self.session.get(ScriptGenerationTask, task_id)

    def update_script_task(
        self,
        *,
        task_id: int,
        status: ScriptGenerationTaskStatus | None = None,
        section_plan: str | None = None,
        error_message: str | None = None,
    ) -> ScriptGenerationTask:
        """更新分页脚本任务状态和过程信息。"""

        task = self.session.get(ScriptGenerationTask, task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if status is not None:
            task.status = status
        if section_plan is not None:
            task.section_plan = section_plan
        if error_message is not None:
            task.error_message = error_message
        self.session.commit()
        self.session.refresh(task)
        return task

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

    def upsert_page_script(self, *, project_id: int, page_no: int, script: str) -> ComicPage:
        """按页码创建或更新页面脚本，并标记为脚本已生成。"""

        project = self.session.get(ComicProject, project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")

        page = self.get_project_page(project_id=project_id, page_no=page_no)
        if page is None:
            page = ComicPage(project_id=project_id, page_no=page_no)
            self.session.add(page)

        page.script = script
        page.status = ComicPageStatus.SCRIPT_READY
        self.session.commit()
        self.session.refresh(page)
        return page

    def update_page_script(self, page_id: int, script: str) -> ComicPage:
        """保存页面脚本，并把页面状态推进到脚本已生成。"""

        page = self.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        page.script = script
        page.status = ComicPageStatus.SCRIPT_READY
        self.session.commit()
        self.session.refresh(page)
        return page

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
    ) -> GenerationTask:
        """记录一次出图任务，后续可根据 comfy_prompt_id 查询任务结果。"""

        task = GenerationTask(
            project_id=project_id,
            page_id=page_id,
            batch_size=batch_size,
            comfy_prompt_id=comfy_prompt_id,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task
