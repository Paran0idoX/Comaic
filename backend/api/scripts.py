import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.script import (
    GenerateBatchScriptRequest,
    GenerateSinglePageScriptRequest,
    ScriptPageListResponse,
    ScriptPageResponse,
    ScriptTaskResponse,
    SinglePageScriptResponse,
)
from backend.models.comic import ComicPage, ScriptGenerationTask
from backend.models.database import SessionLocal
from backend.repositories.comic_repository import ComicRepository
from backend.services.comic_service import ComicService


router = APIRouter(prefix="/api/scripts", tags=["scripts"])
project_pages_router = APIRouter(prefix="/api/projects", tags=["scripts"])


def sse_event(event: str, payload: dict) -> dict[str, str]:
    """统一把 Python 字典编码为 SSE 事件。"""

    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False),
    }


def task_to_response(task: ScriptGenerationTask) -> ScriptTaskResponse:
    """把脚本任务 ORM 对象转换为 API 响应。"""

    return ScriptTaskResponse(
        id=task.id,
        project_id=task.project_id,
        outline_version_id=task.outline_version_id,
        status=task.status.value,
        mode=task.mode.value,
        total_pages=task.total_pages,
        target_page_no=task.target_page_no,
        user_requirement=task.user_requirement,
        section_plan=task.section_plan,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def page_to_response(page: ComicPage) -> ScriptPageResponse:
    """把页面 ORM 对象转换为脚本页面响应。"""

    return ScriptPageResponse(
        id=page.id,
        project_id=page.project_id,
        page_no=page.page_no,
        script=page.script,
        status=page.status.value,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def value_error_status_code(exc: ValueError) -> int:
    """把业务层 ValueError 映射到更明确的 HTTP 状态码。"""

    message = str(exc).lower()
    return 404 if "not found" in message else 400


@router.post("/pages/generate", response_model=SinglePageScriptResponse)
async def generate_single_page_script(
    request: GenerateSinglePageScriptRequest,
) -> SinglePageScriptResponse:
    """生成单页漫画脚本并保存。"""

    with SessionLocal() as db_session:
        service = ComicService(ComicRepository(db_session))
        try:
            task, page = await service.generate_single_page_script(
                project_id=request.project_id,
                page_no=request.page_no,
                total_pages=request.total_pages,
                outline_version_id=request.outline_version_id,
                user_requirement=request.user_requirement,
            )
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc

        return SinglePageScriptResponse(
            task_id=task.id,
            page_id=page.id,
            page_no=page.page_no,
            script=page.script or "",
            status=task.status.value,
        )


@router.post("/batch/stream")
def stream_batch_script_generation(request: GenerateBatchScriptRequest) -> EventSourceResponse:
    """用 SSE 返回批量分页脚本生成进度。"""

    async def event_generator():
        with SessionLocal() as db_session:
            service = ComicService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_batch_script_generation(
                    project_id=request.project_id,
                    total_pages=request.total_pages,
                    outline_version_id=request.outline_version_id,
                    user_requirement=request.user_requirement,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", {"message": str(exc)})

    return EventSourceResponse(event_generator())


@router.get("/tasks/{task_id}", response_model=ScriptTaskResponse)
def get_script_task(task_id: int) -> ScriptTaskResponse:
    """查询分页脚本生成任务状态。"""

    with SessionLocal() as db_session:
        service = ComicService(ComicRepository(db_session))
        try:
            task = service.get_script_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return task_to_response(task)


@project_pages_router.get("/{project_id}/pages", response_model=ScriptPageListResponse)
def list_project_pages(project_id: int) -> ScriptPageListResponse:
    """按页码读取项目页面脚本。"""

    with SessionLocal() as db_session:
        service = ComicService(ComicRepository(db_session))
        try:
            pages = service.list_project_pages(project_id=project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ScriptPageListResponse(items=[page_to_response(page) for page in pages])
