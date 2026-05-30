from uuid import uuid4

from backend.models.comic import ComicProject, OutlineVersion, Session
from backend.models.enums import OutlineVersionStatus, SessionPurpose
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

    @staticmethod
    def _normalize_project_title(title: str) -> str:
        """统一处理项目标题，避免空标题或只包含空格的标题落库。"""

        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Project title cannot be empty")
        return normalized_title
