from uuid import uuid4

from backend.agents.outline_character_agent import OutlineCharacterAgent
from backend.models.comic import ComicProject, OutlineCharacter, OutlineVersion, Session
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

    def list_outline_characters(self, *, outline_version_id: int) -> list[OutlineCharacter]:
        """读取某个大纲版本下的角色基准设定。"""

        return self.repository.list_outline_characters(outline_version_id)

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

    async def generate_and_save_outline_characters(
        self,
        *,
        outline_version: OutlineVersion,
        user_message: str = "",
    ) -> list[OutlineCharacter]:
        """为大纲版本生成角色基准设定草案，并保存到 outline_character。"""

        previous_characters = []
        versions = self.repository.list_outline_versions(outline_version.session_id)
        for version in reversed(versions):
            if version.id == outline_version.id:
                continue
            previous_characters = [
                self.outline_character_to_payload(character)
                for character in self.repository.list_outline_characters(version.id)
            ]
            if previous_characters:
                break

        characters = await OutlineCharacterAgent().generate_characters(
            outline=outline_version.content,
            previous_characters=previous_characters,
            user_message=user_message,
        )
        normalized = [
            self._normalize_outline_character_payload(character)
            for character in characters
        ]
        return self.repository.replace_outline_characters(
            outline_version_id=outline_version.id,
            characters=normalized,
        )

    def confirm_outline_version(self, *, outline_version_id: int) -> OutlineVersion:
        """确认大纲版本及其角色基准设定。"""

        outline_version = self.repository.get_outline_version(outline_version_id)
        if outline_version is None:
            raise ValueError(f"OutlineVersion not found: {outline_version_id}")
        return self.repository.confirm_outline_version(outline_version_id)

    def _get_project(self, project_id: int) -> ComicProject:
        """校验项目存在；大纲会话必须挂在已有项目下。"""

        project = self.repository.get_project(project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")
        return project

    @staticmethod
    def outline_character_to_payload(character: OutlineCharacter) -> dict:
        """把大纲角色基准设定转成 Agent/API 共用字典。"""

        return {
            "id": character.id,
            "outline_version_id": character.outline_version_id,
            "character_key": character.character_key,
            "name": character.name,
            "role": character.role,
            "background": character.background,
            "appearance": character.appearance,
            "visual_anchors": character.visual_anchors,
            "negative_constraints": character.negative_constraints,
            "default_hairstyle": character.default_hairstyle,
            "default_clothing": character.default_clothing,
            "default_accessories": character.default_accessories,
            "default_color_palette": character.default_color_palette,
        }

    @staticmethod
    def _normalize_outline_character_payload(raw_character: dict) -> dict:
        """规范化大纲角色基准设定，避免空 key 或空名称进入数据库。"""

        payload = {
            "character_key": str(raw_character.get("character_key", "")).strip(),
            "name": str(raw_character.get("name", "")).strip(),
            "role": str(raw_character.get("role", "")).strip(),
            "background": str(raw_character.get("background", "")).strip(),
            "appearance": str(raw_character.get("appearance", "")).strip(),
            "visual_anchors": str(raw_character.get("visual_anchors", "")).strip(),
            "negative_constraints": str(raw_character.get("negative_constraints", "")).strip(),
            "default_hairstyle": str(raw_character.get("default_hairstyle", "")).strip(),
            "default_clothing": str(raw_character.get("default_clothing", "")).strip(),
            "default_accessories": str(raw_character.get("default_accessories", "")).strip(),
            "default_color_palette": str(raw_character.get("default_color_palette", "")).strip(),
        }
        for field_name in ("character_key", "name", "appearance"):
            if not payload[field_name]:
                raise ValueError(f"outline character missing required field: {field_name}")
        return payload
