import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from backend.api.schemas.script import (
    ContinueBatchScriptRequest,
    CreatePageScriptRequest,
    GenerateBatchScriptRequest,
    GenerateSinglePageScriptRequest,
    ScriptPageListResponse,
    ScriptPageResponse,
    ScriptCharacterListResponse,
    ScriptCharacterResponse,
    ScriptSceneListResponse,
    ScriptSceneResponse,
    ScriptSectionListResponse,
    ScriptSectionResponse,
    ScriptTaskResponse,
    SinglePageScriptResponse,
    UpdatePageScriptRequest,
)
from backend.models.comic import ComicPage, ScriptCharacter, ScriptGenerationTask, ScriptScene, ScriptSection
from backend.models.database import SessionLocal
from backend.models.enums import ScriptGenerationMode, ScriptGenerationTaskStatus
from backend.repositories.comic_repository import ComicRepository
from backend.i18n.errors import http_exception, sse_error_payload
from backend.i18n.locale import request_locale
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
        scene_id=page.scene_id,
        scene_key=page.script_scene.scene_key if page.script_scene is not None else None,
        character_keys=[
            character.character_key
            for character in sorted(page.visual_characters, key=lambda item: item.character_key)
        ],
        page_no=page.page_no,
        summary=page.summary,
        characters=page.characters,
        clothing=page.clothing,
        scene=page.scene,
        composition=page.composition,
        character_action=page.character_action,
        dialogue=page.dialogue,
        image_prompt=page.image_prompt,
        status=page.status.value,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def scene_to_response(scene: ScriptScene) -> ScriptSceneResponse:
    """把中心化场景设定 ORM 对象转换为 API 响应。"""

    return ScriptSceneResponse(
        id=scene.id,
        task_id=scene.task_id,
        scene_key=scene.scene_key,
        name=scene.name,
        location_type=scene.location_type,
        time_of_day=scene.time_of_day,
        lighting=scene.lighting,
        weather=scene.weather,
        environment_details=scene.environment_details,
        color_palette=scene.color_palette,
        visual_anchors=scene.visual_anchors,
        negative_constraints=scene.negative_constraints,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )


def character_to_response(character: ScriptCharacter) -> ScriptCharacterResponse:
    """把中心化角色设定 ORM 对象转换为 API 响应。"""

    return ScriptCharacterResponse(
        id=character.id,
        task_id=character.task_id,
        character_key=character.character_key,
        name=character.name,
        role=character.role,
        appearance=character.appearance,
        hairstyle=character.hairstyle,
        clothing_style=character.clothing_style,
        accessories=character.accessories,
        color_palette=character.color_palette,
        visual_anchors=character.visual_anchors,
        negative_constraints=character.negative_constraints,
        created_at=character.created_at,
        updated_at=character.updated_at,
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


@router.post("/pages/generate", response_model=SinglePageScriptResponse)
async def generate_single_page_script(
    request: GenerateSinglePageScriptRequest,
    http_request: Request,
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
            raise http_exception(exc, request_locale(http_request)) from exc

        return SinglePageScriptResponse(
            task_id=task.id,
            page_id=page.id,
            page_no=page.page_no,
            summary=page.summary or "",
            characters=page.characters or "",
            clothing=page.clothing or "",
            scene=page.scene or "",
            composition=page.composition or "",
            character_action=page.character_action or "",
            dialogue=page.dialogue or "",
            status=task.status.value,
        )


@router.post("/batch/stream")
def stream_batch_script_generation(
    request: GenerateBatchScriptRequest,
    http_request: Request,
) -> EventSourceResponse:
    """用 SSE 返回批量分页脚本生成进度。"""

    locale = request_locale(http_request)

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
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.post("/tasks/{task_id}/continue/stream")
def stream_continue_batch_script_generation(
    task_id: int,
    request: ContinueBatchScriptRequest,
    http_request: Request,
) -> EventSourceResponse:
    """继续未完成的批量分页脚本任务，并用 SSE 返回进度。"""

    locale = request_locale(http_request)

    async def event_generator():
        with SessionLocal() as db_session:
            service = ScriptService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_continue_batch_script_generation(
                    task_id=task_id,
                    user_requirement=request.user_requirement,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.get("/tasks/{task_id}", response_model=ScriptTaskResponse)
def get_script_task(task_id: int, http_request: Request) -> ScriptTaskResponse:
    """查询分页脚本生成任务状态。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            task = service.get_script_task(task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return task_to_response(task)


@router.get("/tasks/{task_id}/pages", response_model=ScriptPageListResponse)
def list_script_task_pages(task_id: int, http_request: Request) -> ScriptPageListResponse:
    """读取指定脚本任务下的页面脚本，避免混入同项目其它任务。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            pages = service.list_script_task_pages(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptPageListResponse(items=[page_to_response(page) for page in pages])


@router.post("/tasks/{task_id}/suspend", response_model=ScriptTaskResponse)
def suspend_script_task(task_id: int, http_request: Request) -> ScriptTaskResponse:
    """暂停分页脚本批量生成任务；已保存的分段和页面脚本会保留。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            task = service.suspend_script_task(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return task_to_response(task)


@router.get("/tasks/{task_id}/sections", response_model=ScriptSectionListResponse)
def list_script_task_sections(task_id: int, http_request: Request) -> ScriptSectionListResponse:
    """读取脚本任务下的分段及其页面，便于前端按分段展示。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            sections = service.list_script_task_sections(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptSectionListResponse(items=[section_to_response(section) for section in sections])


@router.get("/tasks/{task_id}/scenes", response_model=ScriptSceneListResponse)
def list_script_task_scenes(task_id: int, http_request: Request) -> ScriptSceneListResponse:
    """读取脚本任务下的中心化场景设定。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            scenes = service.list_script_scenes(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptSceneListResponse(items=[scene_to_response(scene) for scene in scenes])


@router.get("/tasks/{task_id}/characters", response_model=ScriptCharacterListResponse)
def list_script_task_characters(task_id: int, http_request: Request) -> ScriptCharacterListResponse:
    """读取脚本任务下的中心化角色设定。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            characters = service.list_script_characters(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptCharacterListResponse(
            items=[character_to_response(character) for character in characters]
        )


@router.delete("/tasks/{task_id}/sections", response_model=ScriptSectionListResponse)
def delete_script_task_sections(task_id: int, http_request: Request) -> ScriptSectionListResponse:
    """删除脚本任务下全部分段，并同步删除这些分段下的页面。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            service.delete_script_task_sections(task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptSectionListResponse(items=[])


@project_pages_router.get("/{project_id}/pages", response_model=ScriptPageListResponse)
def list_project_pages(project_id: int, http_request: Request) -> ScriptPageListResponse:
    """按页码读取项目页面脚本。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            pages = service.list_project_pages(project_id=project_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptPageListResponse(items=[page_to_response(page) for page in pages])


@project_pages_router.get("/{project_id}/script-tasks", response_model=list[ScriptTaskResponse])
def list_project_script_tasks(
    project_id: int,
    http_request: Request,
    outline_version_id: int | None = None,
    mode: str | None = None,
    status: str | None = None,
) -> list[ScriptTaskResponse]:
    """按项目和可选大纲版本读取脚本任务，供分页脚本页选择历史任务。"""

    parsed_mode = None
    parsed_status = None
    try:
        if mode is not None:
            parsed_mode = ScriptGenerationMode(mode)
        if status is not None:
            parsed_status = ScriptGenerationTaskStatus(status)
    except ValueError as exc:
        raise http_exception(ValueError("Invalid script task filter."), request_locale(http_request)) from exc

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            tasks = service.list_script_tasks(
                project_id=project_id,
                outline_version_id=outline_version_id,
                mode=parsed_mode,
                status=parsed_status,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return [task_to_response(task) for task in tasks]


@project_pages_router.delete("/{project_id}/pages", response_model=ScriptPageListResponse)
def delete_project_pages(project_id: int, http_request: Request) -> ScriptPageListResponse:
    """硬删除项目下全部页面行；会同步删除页面候选图并保留出图任务历史。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            service.delete_project_pages(project_id=project_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return ScriptPageListResponse(items=[])


@project_pages_router.post("/{project_id}/pages/scripts", response_model=ScriptPageResponse)
def create_page_script(
    project_id: int,
    request: CreatePageScriptRequest,
    http_request: Request,
) -> ScriptPageResponse:
    """人工新增页面脚本；同页已存在时按 upsert 更新。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.upsert_manual_page_script(
                project_id=project_id,
                page_no=request.page_no,
                task_id=request.task_id,
                summary=request.summary,
                characters=request.characters,
                clothing=request.clothing,
                scene=request.scene,
                composition=request.composition,
                character_action=request.character_action,
                dialogue=request.dialogue,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return page_to_response(page)


@project_pages_router.put("/{project_id}/pages/{page_no}/script", response_model=ScriptPageResponse)
def update_page_script(
    project_id: int,
    page_no: int,
    request: UpdatePageScriptRequest,
    http_request: Request,
) -> ScriptPageResponse:
    """人工更新页面脚本。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.upsert_manual_page_script(
                project_id=project_id,
                page_no=page_no,
                task_id=request.task_id,
                summary=request.summary,
                characters=request.characters,
                clothing=request.clothing,
                scene=request.scene,
                composition=request.composition,
                character_action=request.character_action,
                dialogue=request.dialogue,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return page_to_response(page)


@project_pages_router.delete("/{project_id}/pages/{page_no}/script", response_model=ScriptPageResponse)
def clear_page_script(
    project_id: int,
    page_no: int,
    http_request: Request,
    task_id: int | None = None,
) -> ScriptPageResponse:
    """人工清空页面脚本；保留页面记录。"""

    with SessionLocal() as db_session:
        service = ScriptService(ComicRepository(db_session))
        try:
            page = service.clear_page_script(project_id=project_id, page_no=page_no, task_id=task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return page_to_response(page)
