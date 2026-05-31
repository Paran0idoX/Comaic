from backend.models.comic import ComicProject
from backend.repositories.comic_repository import ComicRepository


class ProjectService:
    """项目业务服务，只负责项目自身的创建、读取、更新和删除。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository，让 Service 只编排业务规则，不直接关心数据库细节。"""

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

    @staticmethod
    def _normalize_project_title(title: str) -> str:
        """统一处理项目标题，避免空标题或只包含空格的标题落库。"""

        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Project title cannot be empty")
        return normalized_title
