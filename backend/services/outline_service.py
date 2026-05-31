from uuid import uuid4

from backend.models.comic import ComicProject, OutlineVersion, Session
from backend.models.enums import OutlineVersionStatus, SessionPurpose
from backend.repositories.comic_repository import ComicRepository


class OutlineService:
    """大纲业务服务，负责会话创建、大纲版本读取和快照保存。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository，保持大纲业务流程和数据库实现解耦。"""

        self.repository = repository

    def create_outline_session(self, *, project_id: int) -> Session:
        """为项目创建大纲业务会话，并生成 LangGraph 使用的 thread_id。"""

        self._get_project(project_id)
        return self.repository.create_session(
            project_id=project_id,
            thread_id=str(uuid4()),
            purpose=SessionPurpose.OUTLINE,
        )

    def get_or_create_outline_session(self, *, project_id: int) -> Session:
        """复用项目最近的大纲会话；没有会话时再创建新的会话。"""

        self._get_project(project_id)
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

    def _get_project(self, project_id: int) -> ComicProject:
        """校验项目存在；大纲会话必须挂在已有项目下。"""

        project = self.repository.get_project(project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")
        return project
