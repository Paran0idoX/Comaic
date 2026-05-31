import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from backend.api.schemas.script import (
    CreatePageScriptRequest,
    GenerateBatchScriptRequest,
    GenerateSinglePageScriptRequest,
    ScriptPageListResponse,
    ScriptPageResponse,
    ScriptSectionListResponse,
    ScriptSectionResponse,
    ScriptTaskResponse,
    SinglePageScriptResponse,
    UpdatePageScriptRequest,
)
from backend.models.comic import ComicPage, ScriptGenerationTask, ScriptSection
from backend.models.database import SessionLocal
from backend.repositories.comic_repository import ComicRepository
from backend.services.script_service import ScriptService


router = APIRouter(prefix="/api/scripts", tags=["scripts"])
project_pages_router = APIRouter(prefix="/api/projects", tags=["scripts"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(event: str, payload: dict) -> ServerSentEvent:
    """统一把 Python 字典编码为 SSE 事件。"""

    return ServerSentEvent(
        event=event,
        data=json.dumps(payload, ensure_ascii=False),
    )


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
        section_id=page.section_id,
        section_no=page.section.section_no if page.section is not None else None,
        task_id=page.section.task_id if page.section is not None else None,
        page_no=page.page_no,
        script=page.script,
        image_prompt=page.image_prompt,
        status=page.status.value,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def section_to_response(section: ScriptSection) -> ScriptSectionResponse:
    """把脚本分段 ORM 对象转换为 API 响应。"""

    return ScriptSectionResponse(
        id=section.id,
        task_id=section.task_id,
        section_no=section.section_no,
        page_start=section.page_start,
        page_end=section.page_end,
        title=section.title,
        description=section.description,
        created_at=section.created_at,
        updated_at=section.updated_at,
        pages=[page_to_response(page) for page in sorted(section.pages, key=lambda item: item.page_no)],
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
        service = ScriptService(ComicRepository(db_session))
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
            service = ScriptService(ComicRepository(db_session))
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

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.get("/tasks/{task_id}", response_model=ScriptTaskResponse)
def get_script_task(task_id: int) -> ScriptTaskResponse:
    """查询分页脚本生成任务状态。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            task = service.get_script_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return task_to_response(task)


@router.post("/tasks/{task_id}/suspend", response_model=ScriptTaskResponse)
def suspend_script_task(task_id: int) -> ScriptTaskResponse:
    """暂停分页脚本批量生成任务；已保存的分段和页面脚本会保留。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            task = service.suspend_script_task(task_id=task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return task_to_response(task)


@router.get("/tasks/{task_id}/sections", response_model=ScriptSectionListResponse)
def list_script_task_sections(task_id: int) -> ScriptSectionListResponse:
    """读取脚本任务下的分段及其页面，便于前端按分段展示。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            sections = service.list_script_task_sections(task_id=task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return ScriptSectionListResponse(items=[section_to_response(section) for section in sections])


@router.delete("/tasks/{task_id}/sections", response_model=ScriptSectionListResponse)
def delete_script_task_sections(task_id: int) -> ScriptSectionListResponse:
    """删除脚本任务下全部分段，并同步删除这些分段下的页面。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            service.delete_script_task_sections(task_id=task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return ScriptSectionListResponse(items=[])


@project_pages_router.get("/{project_id}/pages", response_model=ScriptPageListResponse)
def list_project_pages(project_id: int) -> ScriptPageListResponse:
    """按页码读取项目页面脚本。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            pages = service.list_project_pages(project_id=project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ScriptPageListResponse(items=[page_to_response(page) for page in pages])


@project_pages_router.delete("/{project_id}/pages", response_model=ScriptPageListResponse)
def delete_project_pages(project_id: int) -> ScriptPageListResponse:
    """硬删除项目下全部页面行；会同步删除页面候选图并保留出图任务历史。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            service.delete_project_pages(project_id=project_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return ScriptPageListResponse(items=[])


@project_pages_router.post("/{project_id}/pages/scripts", response_model=ScriptPageResponse)
def create_page_script(project_id: int, request: CreatePageScriptRequest) -> ScriptPageResponse:
    """人工新增页面脚本；同页已存在时按 upsert 更新。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.upsert_manual_page_script(
                project_id=project_id,
                page_no=request.page_no,
                script=request.script,
            )
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return page_to_response(page)


@project_pages_router.put("/{project_id}/pages/{page_no}/script", response_model=ScriptPageResponse)
def update_page_script(
    project_id: int,
    page_no: int,
    request: UpdatePageScriptRequest,
) -> ScriptPageResponse:
    """人工更新页面脚本。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.upsert_manual_page_script(
                project_id=project_id,
                page_no=page_no,
                script=request.script,
            )
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return page_to_response(page)


@project_pages_router.delete("/{project_id}/pages/{page_no}/script", response_model=ScriptPageResponse)
def clear_page_script(project_id: int, page_no: int) -> ScriptPageResponse:
    """人工清空页面脚本；保留页面记录。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.clear_page_script(project_id=project_id, page_no=page_no)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return page_to_response(page)
