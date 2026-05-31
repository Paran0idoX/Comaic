from uuid import uuid4

from backend.agents.script_deep_agent import ScriptDeepAgent
from backend.models.comic import ComicPage, ComicProject, OutlineVersion, ScriptGenerationTask, Session
from backend.models.enums import (
    OutlineVersionStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    SessionPurpose,
)
from backend.repositories.comic_repository import ComicRepository


class ComicService:
    """漫画业务服务层，负责编排业务规则并调用 Repository。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository，便于测试时替换数据库实现。"""

        self.repository = repository

    def create_project(
        self,
        *,
        title: str,
    ) -> ComicProject:
        """创建项目记录；当前 MVP 项目只保存标题。"""

        return self.repository.create_project(
            title=self._normalize_project_title(title),
        )

    def list_projects(self) -> list[ComicProject]:
        """读取项目列表，业务层暂不做分页和搜索。"""

        return self.repository.list_projects()

    def get_project(self, project_id: int) -> ComicProject:
        """读取单个项目；不存在时抛出明确错误交给 API 映射为 404。"""

        project = self.repository.get_project(project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")
        return project

    def update_project(self, *, project_id: int, title: str) -> ComicProject:
        """更新项目标题，并在进入数据库前统一做空值校验和裁剪。"""

        return self.repository.update_project(
            project_id=project_id,
            title=self._normalize_project_title(title),
        )

    def delete_project(self, project_id: int) -> None:
        """删除项目；具体级联删除由 ORM relationship 配置负责。"""

        self.repository.delete_project(project_id)

    def create_outline_session(self, *, project_id: int) -> Session:
        """为项目创建大纲业务会话，并生成 LangGraph 使用的 thread_id。"""

        return self.repository.create_session(
            project_id=project_id,
            thread_id=str(uuid4()),
            purpose=SessionPurpose.OUTLINE,
        )

    def get_or_create_outline_session(self, *, project_id: int) -> Session:
        """复用项目最近的大纲会话；没有会话时再创建新的会话。"""

        self.get_project(project_id)
        session = self.repository.get_latest_session(
            project_id=project_id,
            purpose=SessionPurpose.OUTLINE,
        )
        if session is not None:
            return session
        return self.create_outline_session(project_id=project_id)

    def list_outline_versions(self, *, session_id: int) -> list[OutlineVersion]:
        """读取某个会话下保留的大纲版本，供前端刷新后恢复右侧快照。"""

        return self.repository.list_outline_versions(session_id)

    def get_current_outline(self, *, session_id: int) -> str:
        """读取当前 active 大纲文本；没有版本时返回空字符串。"""

        versions = self.repository.list_outline_versions(session_id)
        for version in reversed(versions):
            if version.status == OutlineVersionStatus.ACTIVE:
                return version.content
        return versions[-1].content if versions else ""

    def save_outline_snapshot(self, *, thread_id: str, outline: str) -> OutlineVersion:
        """把本轮对话生成的大纲快照保存为新的 active 版本。"""

        session = self.repository.get_session_by_thread_id(thread_id)
        if session is None:
            raise ValueError(f"Session not found: {thread_id}")
        if session.purpose != SessionPurpose.OUTLINE:
            raise ValueError(f"Session is not an outline session: {thread_id}")

        return self.repository.create_outline_version(
            session_id=session.id,
            content=outline,
        )

    def get_script_task(self, task_id: int) -> ScriptGenerationTask:
        """读取脚本生成任务；不存在时抛出明确错误。"""

        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return task

    def list_project_pages(self, *, project_id: int) -> list[ComicPage]:
        """读取项目页面脚本，供 API 展示生成结果。"""

        self.get_project(project_id)
        return self.repository.list_project_pages(project_id)

    async def generate_single_page_script(
        self,
        *,
        project_id: int,
        page_no: int,
        total_pages: int,
        outline_version_id: int | None = None,
        user_requirement: str | None = None,
    ) -> tuple[ScriptGenerationTask, ComicPage]:
        """同步生成单页脚本并保存到 comic_page。"""

        self._validate_page_args(page_no=page_no, total_pages=total_pages)
        outline_version = self._resolve_outline_version(
            project_id=project_id,
            outline_version_id=outline_version_id,
        )
        task = self.repository.create_script_task(
            project_id=project_id,
            outline_version_id=outline_version.id,
            mode=ScriptGenerationMode.SINGLE,
            status=ScriptGenerationTaskStatus.RUNNING,
            total_pages=total_pages,
            target_page_no=page_no,
            user_requirement=user_requirement,
        )

        try:
            result = await ScriptDeepAgent().generate_single_page(
                outline=outline_version.content,
                total_pages=total_pages,
                page_no=page_no,
                user_requirement=user_requirement or "",
            )
            page_payload = self._find_page_payload(result.get("pages", []), page_no)
            page = self.repository.upsert_page_script(
                project_id=project_id,
                page_no=page_no,
                script=self._format_page_script(page_payload),
            )
            self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
            )
            task = self.get_script_task(task.id)
            return task, page
        except Exception as exc:
            self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def stream_batch_script_generation(
        self,
        *,
        project_id: int,
        total_pages: int,
        outline_version_id: int | None = None,
        user_requirement: str | None = None,
    ):
        """批量生成分页脚本，并以事件形式返回任务进度。"""

        self._validate_total_pages(total_pages)
        outline_version = self._resolve_outline_version(
            project_id=project_id,
            outline_version_id=outline_version_id,
        )
        task = self.repository.create_script_task(
            project_id=project_id,
            outline_version_id=outline_version.id,
            mode=ScriptGenerationMode.BATCH,
            status=ScriptGenerationTaskStatus.RUNNING,
            total_pages=total_pages,
            user_requirement=user_requirement,
        )
        yield "task", {"task_id": task.id, "status": task.status.value}
        yield "phase", {"message": "正在进行故事节奏划分与分页脚本生成"}

        try:
            result = await ScriptDeepAgent().generate_batch(
                outline=outline_version.content,
                total_pages=total_pages,
                user_requirement=user_requirement or "",
            )
            section_plan = result.get("section_plan", [])
            self.repository.update_script_task(
                task_id=task.id,
                section_plan=self._json_dumps(section_plan),
            )
            yield "section_plan", {"sections": section_plan}
            for section in section_plan:
                yield "section", section if isinstance(section, dict) else {"description": str(section)}

            for review in result.get("reviews", []):
                yield "review", review if isinstance(review, dict) else {"comments": str(review)}

            for page_payload in sorted(result.get("pages", []), key=lambda item: int(item.get("page_no", 0))):
                page_no = int(page_payload["page_no"])
                page = self.repository.upsert_page_script(
                    project_id=project_id,
                    page_no=page_no,
                    script=self._format_page_script(page_payload),
                )
                yield "page", {
                    "page_id": page.id,
                    "page_no": page.page_no,
                    "status": page.status.value,
                }

            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
            )
            yield "done", {"task_id": task.id, "status": task.status.value}
        except Exception as exc:
            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            yield "error", {
                "task_id": task.id,
                "status": task.status.value,
                "message": str(exc),
            }

    @staticmethod
    def _normalize_project_title(title: str) -> str:
        """统一处理项目标题，避免空标题或只包含空格的标题落库。"""

        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Project title cannot be empty")
        return normalized_title

    def _resolve_outline_version(
        self,
        *,
        project_id: int,
        outline_version_id: int | None,
    ) -> OutlineVersion:
        """按请求指定或项目 active 版本读取大纲。"""

        self.get_project(project_id)
        if outline_version_id is not None:
            outline_version = self.repository.get_outline_version(outline_version_id)
            if outline_version is None:
                raise ValueError(f"OutlineVersion not found: {outline_version_id}")
            if outline_version.session.project_id != project_id:
                raise ValueError("OutlineVersion does not belong to project.")
            return outline_version

        outline_version = self.repository.get_active_outline_version_for_project(project_id)
        if outline_version is None:
            raise ValueError(f"Active outline not found for project: {project_id}")
        return outline_version

    @staticmethod
    def _validate_total_pages(total_pages: int) -> None:
        """校验总页数，避免无意义的脚本生成请求。"""

        if total_pages <= 0:
            raise ValueError("total_pages must be greater than 0")

    def _validate_page_args(self, *, page_no: int, total_pages: int) -> None:
        """校验单页生成页码范围。"""

        self._validate_total_pages(total_pages)
        if page_no <= 0 or page_no > total_pages:
            raise ValueError("page_no must be between 1 and total_pages")

    @staticmethod
    def _find_page_payload(pages: list, page_no: int) -> dict:
        """从 Agent 输出中找到指定页；单页输出缺页时给出明确错误。"""

        for page in pages:
            if int(page.get("page_no", 0)) == page_no:
                return page
        if len(pages) == 1:
            return pages[0]
        raise ValueError(f"Generated script missing page_no: {page_no}")

    @staticmethod
    def _format_page_script(page_payload: dict) -> str:
        """把结构化页面脚本转换为适合保存展示的中文文本。"""

        return "\n".join(
            [
                f"页面目标：{page_payload.get('page_goal', '')}",
                f"画面内容：{page_payload.get('scene', '')}",
                f"角色动作：{page_payload.get('character_action', '')}",
                f"对白或旁白：{page_payload.get('dialogue_or_caption', '')}",
                f"完整脚本：{page_payload.get('script', '')}",
            ]
        ).strip()

    @staticmethod
    def _json_dumps(value) -> str:
        """用统一格式保存 Agent 结构化中间结果。"""

        import json

        return json.dumps(value, ensure_ascii=False)
