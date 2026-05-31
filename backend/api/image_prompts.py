from fastapi import APIRouter, HTTPException, Response, status
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.image_prompt import (
    GenerateImagePromptsRequest,
    GenerateImagePromptsResponse,
    ImagePromptGenerationItemResponse,
    ImagePromptPresetListResponse,
    ImagePromptPresetRequest,
    ImagePromptPresetResponse,
)
from backend.api.schemas.script import ScriptTaskResponse
from backend.api.scripts import SSE_HEADERS, sse_event, task_to_response, value_error_status_code
from backend.models.comic import ImagePromptPreset
from backend.models.database import SessionLocal
from backend.models.enums import ImagePromptPresetKind
from backend.repositories.comic_repository import ComicRepository
from backend.services.image_prompt_service import (
    ImagePromptGenerateItem,
    ImagePromptGenerateResult,
    ImagePromptService,
)


router = APIRouter(prefix="/api/image-prompts", tags=["image-prompts"])


def preset_to_response(preset: ImagePromptPreset) -> ImagePromptPresetResponse:
    """把图片 Prompt 配置 ORM 对象转换为 API 响应。"""

    return ImagePromptPresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        kind=preset.kind.value,
        content=preset.content,
        is_default=preset.is_default,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


def parse_preset_kind(value: str | None) -> ImagePromptPresetKind | None:
    """把请求里的 kind 字符串转换为枚举，保证固定值集中管理。"""

    if value is None:
        return None
    try:
        return ImagePromptPresetKind(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image prompt preset kind: {value}") from exc


def generation_item_to_response(item: ImagePromptGenerateItem) -> ImagePromptGenerationItemResponse:
    """把单页图片 Prompt 生成结果转换为 API 响应。"""

    return ImagePromptGenerationItemResponse(
        page_id=item.page_id,
        page_no=item.page_no,
        image_prompt=item.image_prompt,
        status=item.status,
        error=item.error,
    )


def generation_result_to_response(result: ImagePromptGenerateResult) -> GenerateImagePromptsResponse:
    """把图片 Prompt 批量结果转换为 API 响应。"""

    return GenerateImagePromptsResponse(
        task_id=result.task_id,
        total=result.total,
        succeeded=result.succeeded,
        failed=result.failed,
        items=[generation_item_to_response(item) for item in result.items],
    )


@router.get("/presets", response_model=ImagePromptPresetListResponse)
def list_presets(kind: str | None = None) -> ImagePromptPresetListResponse:
    """读取图片 Prompt 配置列表，可按 kind 筛选。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        presets = service.list_presets(parse_preset_kind(kind))
        return ImagePromptPresetListResponse(items=[preset_to_response(preset) for preset in presets])


@router.post("/presets", response_model=ImagePromptPresetResponse, status_code=status.HTTP_201_CREATED)
def create_preset(request: ImagePromptPresetRequest) -> ImagePromptPresetResponse:
    """创建图片 Prompt 配置。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            preset = service.create_preset(
                name=request.name,
                kind=parse_preset_kind(request.kind),
                content=request.content,
                description=request.description,
                is_default=request.is_default,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return preset_to_response(preset)


@router.put("/presets/{preset_id}", response_model=ImagePromptPresetResponse)
def update_preset(preset_id: int, request: ImagePromptPresetRequest) -> ImagePromptPresetResponse:
    """更新图片 Prompt 配置。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            preset = service.update_preset(
                preset_id=preset_id,
                name=request.name,
                kind=parse_preset_kind(request.kind),
                content=request.content,
                description=request.description,
                is_default=request.is_default,
            )
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return preset_to_response(preset)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: int) -> Response:
    """删除图片 Prompt 配置。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            service.delete_preset(preset_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/script-tasks", response_model=list[ScriptTaskResponse])
def list_completed_script_tasks(project_id: int) -> list[ScriptTaskResponse]:
    """读取项目下已完成脚本任务，供图片 Prompt 生成选择。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            tasks = service.list_completed_script_tasks(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return [task_to_response(task) for task in tasks]


@router.get("/script-tasks/{task_id}/pages", response_model=GenerateImagePromptsResponse)
def list_script_task_image_prompts(task_id: int) -> GenerateImagePromptsResponse:
    """读取脚本任务下已生成的图片 Prompt，供前端切换任务时回显。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            result = service.list_script_task_image_prompts(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return generation_result_to_response(result)


@router.post("/script-tasks/{task_id}/generate", response_model=GenerateImagePromptsResponse)
async def generate_for_script_task(
    task_id: int,
    request: GenerateImagePromptsRequest,
) -> GenerateImagePromptsResponse:
    """为已完成脚本任务下所有页面生成图片 Prompt。"""

    with SessionLocal() as db_session:
        service = ImagePromptService(ComicRepository(db_session))
        try:
            result = await service.generate_for_script_task(
                task_id=task_id,
                system_prompt_preset_id=request.system_prompt_preset_id,
                concurrency=request.concurrency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status_code(exc), detail=str(exc)) from exc
        return generation_result_to_response(result)


@router.post("/script-tasks/{task_id}/generate/stream")
def stream_generate_for_script_task(
    task_id: int,
    request: GenerateImagePromptsRequest,
) -> EventSourceResponse:
    """用 SSE 实时返回图片 Prompt 生成进度；每页保存后立即推送。"""

    async def event_generator():
        with SessionLocal() as db_session:
            service = ImagePromptService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_generate_for_script_task(
                    task_id=task_id,
                    system_prompt_preset_id=request.system_prompt_preset_id,
                    concurrency=request.concurrency,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", {"message": str(exc)})

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)
