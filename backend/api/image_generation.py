from pathlib import Path

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.image_generation import (
    ComicImageResponse,
    ComfyWorkflowPresetListResponse,
    ComfyWorkflowPresetRequest,
    ComfyWorkflowPresetResponse,
    GenerateImagesRequest,
    GenerationTaskResponse,
    ImageGenerationPageListResponse,
    ImageGenerationPageResponse,
)
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.models.comic import ComicImage, ComicPage, ComfyWorkflowPreset, GenerationTask
from backend.models.database import SessionLocal
from backend.repositories.comic_repository import ComicRepository
from backend.i18n.errors import AppError, http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.services.image_generation_service import ImageGenerationService


router = APIRouter(prefix="/api/image-generation", tags=["image-generation"])


def workflow_to_response(preset: ComfyWorkflowPreset) -> ComfyWorkflowPresetResponse:
    """把 workflow 配置 ORM 对象转换为 API 响应。"""

    return ComfyWorkflowPresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        workflow_json=preset.workflow_json,
        is_default=preset.is_default,
        positive_node_id=preset.positive_node_id,
        positive_input_name=preset.positive_input_name,
        negative_node_id=preset.negative_node_id,
        negative_input_name=preset.negative_input_name,
        seed_node_id=preset.seed_node_id,
        seed_input_name=preset.seed_input_name,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


def image_to_response(image: ComicImage) -> ComicImageResponse:
    """把图片 ORM 对象转换为前端可展示的响应。"""

    return ComicImageResponse(
        id=image.id,
        page_id=image.page_id,
        image_url=f"/api/image-generation/images/{image.id}/file",
        local_path=image.local_path,
        seed=image.seed,
        workflow_name=image.workflow_name,
        prompt=image.prompt,
        negative_prompt=image.negative_prompt,
        score=image.score,
        is_selected=image.is_selected,
        created_at=image.created_at,
    )


def page_to_response(page: ComicPage, repo: ComicRepository) -> ImageGenerationPageResponse:
    """把页面和其生成图片列表转换为图片生成页面响应。"""

    return ImageGenerationPageResponse(
        page_id=page.id,
        page_no=page.page_no,
        image_prompt=page.image_prompt,
        status=page.status.value,
        selected_image_id=page.selected_image_id,
        images=[image_to_response(image) for image in repo.list_page_images(page.id)],
    )


def task_to_response(task: GenerationTask) -> GenerationTaskResponse:
    """把 ComfyUI 生成任务转换为 API 响应。"""

    return GenerationTaskResponse(
        id=task.id,
        project_id=task.project_id,
        page_id=task.page_id,
        comfy_prompt_id=task.comfy_prompt_id,
        status=task.status.value,
        batch_size=task.batch_size,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/workflows", response_model=ComfyWorkflowPresetListResponse)
def list_workflows() -> ComfyWorkflowPresetListResponse:
    """读取 ComfyUI workflow 配置列表。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        presets = service.list_workflow_presets()
        return ComfyWorkflowPresetListResponse(items=[workflow_to_response(preset) for preset in presets])


@router.post("/workflows", response_model=ComfyWorkflowPresetResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    request: ComfyWorkflowPresetRequest,
    http_request: Request,
) -> ComfyWorkflowPresetResponse:
    """创建 ComfyUI workflow 配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            preset = service.create_workflow_preset(**request.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return workflow_to_response(preset)


@router.put("/workflows/{workflow_id}", response_model=ComfyWorkflowPresetResponse)
def update_workflow(
    workflow_id: int,
    request: ComfyWorkflowPresetRequest,
    http_request: Request,
) -> ComfyWorkflowPresetResponse:
    """更新 ComfyUI workflow 配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            preset = service.update_workflow_preset(preset_id=workflow_id, **request.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return workflow_to_response(preset)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: int, http_request: Request) -> Response:
    """删除 ComfyUI workflow 配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            service.delete_workflow_preset(workflow_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/script-tasks/{task_id}/pages", response_model=ImageGenerationPageListResponse)
def list_generation_pages(task_id: int, http_request: Request) -> ImageGenerationPageListResponse:
    """读取脚本任务下的图片生成页面状态和已有图片。"""

    with SessionLocal() as db_session:
        repo = ComicRepository(db_session)
        service = ImageGenerationService(repo)
        try:
            pages = service.list_script_task_pages(task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        project_id = pages[0].project_id if pages else 0
        return ImageGenerationPageListResponse(
            task_id=task_id,
            project_id=project_id,
            items=[page_to_response(page, repo) for page in pages],
        )


@router.post("/script-tasks/{task_id}/generate/stream")
def stream_generate_for_script_task(
    task_id: int,
    request: GenerateImagesRequest,
    http_request: Request,
) -> EventSourceResponse:
    """批量生成脚本任务下所有页面图片，并用 SSE 返回进度。"""

    locale = request_locale(http_request)

    async def event_generator():
        with SessionLocal() as db_session:
            service = ImageGenerationService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_generate_for_script_task(
                    task_id=task_id,
                    workflow_preset_id=request.workflow_preset_id,
                    poll_interval_seconds=request.poll_interval_seconds,
                    candidates_per_page=request.candidates_per_page,
                    negative_prompt=request.negative_prompt,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.post("/pages/{page_id}/generate/stream")
def stream_generate_for_page(
    page_id: int,
    request: GenerateImagesRequest,
    http_request: Request,
) -> EventSourceResponse:
    """单页追加生成图片候选。"""

    locale = request_locale(http_request)

    async def event_generator():
        with SessionLocal() as db_session:
            service = ImageGenerationService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_generate_for_page(
                    page_id=page_id,
                    workflow_preset_id=request.workflow_preset_id,
                    poll_interval_seconds=request.poll_interval_seconds,
                    candidates_per_page=request.candidates_per_page,
                    negative_prompt=request.negative_prompt,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.post("/tasks/{task_id}/suspend", response_model=GenerationTaskResponse)
def suspend_generation_task(task_id: int, http_request: Request) -> GenerationTaskResponse:
    """暂停图片生成任务：停止提交后续页面，不 interrupt 当前 ComfyUI prompt。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            task = service.suspend_generation_task(task_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return task_to_response(task)


@router.post("/pages/{page_id}/images/{image_id}/select", response_model=ImageGenerationPageResponse)
def select_image(page_id: int, image_id: int, http_request: Request) -> ImageGenerationPageResponse:
    """人工选择某页最终图片。"""

    with SessionLocal() as db_session:
        repo = ComicRepository(db_session)
        service = ImageGenerationService(repo)
        try:
            page = service.select_image(page_id=page_id, image_id=image_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return page_to_response(page, repo)


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, http_request: Request) -> FileResponse:
    """读取本地 outputs 中的生成图片文件。"""

    with SessionLocal() as db_session:
        image = db_session.get(ComicImage, image_id)
        if image is None or not image.local_path:
            raise http_exception(
                AppError("image_generation.file_not_found", status_code=404),
                request_locale(http_request),
            )
        local_path = Path(image.local_path)
        if not local_path.exists():
            raise http_exception(
                AppError("image_generation.file_not_found", status_code=404),
                request_locale(http_request),
            )
        return FileResponse(local_path)
