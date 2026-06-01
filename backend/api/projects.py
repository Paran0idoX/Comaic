from fastapi import APIRouter, Request, Response, status

from backend.api.schemas.project import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    UpdateProjectRequest,
)
from backend.models.comic import ComicProject
from backend.models.database import SessionLocal
from backend.repositories.comic_repository import ComicRepository
from backend.i18n.errors import http_exception
from backend.i18n.locale import request_locale
from backend.services.project_service import ProjectService


router = APIRouter(prefix="/api/projects", tags=["projects"])


def project_to_response(project: ComicProject) -> ProjectResponse:
    """把 ORM 对象转换为 API 响应，避免路由直接暴露数据库模型。"""

    return ProjectResponse(
        id=project.id,
        title=project.title,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def create_service() -> tuple:
    """创建项目服务及其数据库会话；由路由函数负责关闭会话。"""

    db_session = SessionLocal()
    return db_session, ProjectService(ComicRepository(db_session))


@router.get("", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    """读取全部项目，当前 MVP 暂不做分页。"""

    db_session, service = create_service()
    try:
        projects = service.list_projects()
        return ProjectListResponse(items=[project_to_response(project) for project in projects])
    finally:
        db_session.close()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: CreateProjectRequest, http_request: Request) -> ProjectResponse:
    """创建项目；标题空白校验放在 Service 层统一处理。"""

    db_session, service = create_service()
    try:
        project = service.create_project(title=request.title)
        return project_to_response(project)
    except ValueError as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, http_request: Request) -> ProjectResponse:
    """读取单个项目；不存在时返回 404。"""

    db_session, service = create_service()
    try:
        project = service.get_project(project_id)
        return project_to_response(project)
    except ValueError as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    request: UpdateProjectRequest,
    http_request: Request,
) -> ProjectResponse:
    """更新项目标题；空标题返回 400，项目不存在返回 404。"""

    db_session, service = create_service()
    try:
        project = service.update_project(project_id=project_id, title=request.title)
        return project_to_response(project)
    except ValueError as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, http_request: Request) -> Response:
    """硬删除项目；前端负责二次确认，后端执行实际删除。"""

    db_session, service = create_service()
    try:
        service.delete_project(project_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ValueError as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()
