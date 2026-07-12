from pathlib import Path
import json

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
    GenerationRunResponse,
    ImageGenerationToolPresetListResponse,
    ImageGenerationToolPresetRequest,
    ImageGenerationToolPresetResponse,
    ImageGenerationPageListResponse,
    ImageGenerationPageResponse,
)
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.models.comic import ComicImage, ComicPage, GenerationRun, GenerationTask, ImageGenerationToolPreset
from backend.models.database import SessionLocal
from backend.models.enums import GenerationMode, ImagePromptType
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.generation_repository import GenerationRepository
from backend.i18n.errors import AppError, http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.services.image_generation_service import ImageGenerationService


router = APIRouter(prefix="/api/image-generation", tags=["image-generation"])


def tool_to_response(preset: ImageGenerationToolPreset) -> ImageGenerationToolPresetResponse:
    """把生图工具配置 ORM 对象转换为 API 响应。"""

    return ImageGenerationToolPresetResponse(
        id=preset.id,
        name=preset.name,
        provider=preset.provider,
        prompt_type=preset.prompt_type,
        description=preset.description,
        is_default=preset.is_default,
        capabilities=json.loads(preset.capabilities_json),
        bindings=json.loads(preset.bindings_json),
        comfy_base_url=preset.comfy_base_url,
        workflow_json=preset.workflow_json,
        positive_node_id=preset.positive_node_id,
        positive_input_name=preset.positive_input_name,
        negative_node_id=preset.negative_node_id,
        negative_input_name=preset.negative_input_name,
        seed_node_id=preset.seed_node_id,
        seed_input_name=preset.seed_input_name,
        api_base_url=preset.api_base_url,
        endpoint_path=preset.endpoint_path,
        api_key=preset.api_key,
        model=preset.model,
        size=preset.size,
        response_format=preset.response_format,
        seed_field_name=preset.seed_field_name,
        negative_prompt_field_name=preset.negative_prompt_field_name,
        extra_body_json=preset.extra_body_json,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


workflow_to_response = tool_to_response


def image_to_response(image: ComicImage) -> ComicImageResponse:
    """把图片 ORM 对象转换为前端可展示的响应。"""

    return ComicImageResponse(
        id=image.id,
        page_id=image.page_id,
        generation_run_id=image.generation_run_id,
        image_url=f"/api/image-generation/images/{image.id}/file",
        local_path=image.local_path,
        seed=image.seed,
        workflow_name=image.workflow_name,
        prompt=image.prompt,
        negative_prompt=image.negative_prompt,
        score=image.score,
        sha256=image.sha256,
        width=image.width,
        height=image.height,
        is_selected=image.is_selected,
        created_at=image.created_at,
    )


def page_to_response(
    page: ComicPage,
    repo: ComicRepository,
    *,
    prompt_type: ImagePromptType = ImagePromptType.NATURAL_LANGUAGE,
    generation_mode: GenerationMode = GenerationMode.PREVIEW,
) -> ImageGenerationPageResponse:
    """把页面和其生成图片列表转换为图片生成页面响应。"""

    spec = GenerationRepository(repo.session).latest_spec_for_page(
        page_id=page.id,
        prompt_type=prompt_type,
        generation_mode=generation_mode,
    )
    images = repo.list_page_images(page.id)
    completed_candidates = (
        len(
            {
                run.candidate_index
                for run in GenerationRepository(repo.session).list_successful_runs(
                    page_id=page.id,
                    prompt_type=prompt_type,
                    generation_mode=generation_mode,
                    image_spec_id=spec.id,
                )
            }
        )
        if spec is not None
        else 0
    )
    return ImageGenerationPageResponse(
        page_id=page.id,
        page_no=page.page_no,
        prompt_type=spec.prompt_type if spec else None,
        positive_prompt=spec.positive_prompt if spec else None,
        status=page.status.value,
        selected_image_id=page.selected_image_id,
        latest_spec_id=spec.id if spec else None,
        spec_warnings=json.loads(spec.warnings_json) if spec else [],
        completed_candidates=completed_candidates,
        images=[image_to_response(image) for image in images],
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


def run_to_response(run: GenerationRun) -> GenerationRunResponse:
    """把单候选 GenerationRun 转换为完整溯源响应。"""

    return GenerationRunResponse(
        id=run.id,
        generation_task_id=run.generation_task_id,
        page_id=run.page_id,
        image_spec_id=run.image_spec_id,
        tool_preset_id=run.tool_preset_id,
        provider=run.provider,
        prompt_type=run.prompt_type,
        candidate_index=run.candidate_index,
        seed=run.seed,
        seed_applied=run.seed_applied,
        seed_strategy=run.seed_strategy.value,
        generation_mode=run.generation_mode.value,
        status=run.status.value,
        external_request_id=run.external_request_id,
        workflow=json.loads(run.workflow_json) if run.workflow_json else None,
        workflow_hash=run.workflow_hash,
        bindings=json.loads(run.bindings_json),
        resolved_assets=json.loads(run.resolved_assets_json),
        degradations=json.loads(run.degradation_json),
        applied_spec=json.loads(run.applied_spec_json),
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


@router.get("/workflows", response_model=ComfyWorkflowPresetListResponse, deprecated=True)
def list_workflows() -> ComfyWorkflowPresetListResponse:
    """读取 ComfyUI workflow 配置列表。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        presets = service.list_workflow_presets()
        return ComfyWorkflowPresetListResponse(items=[workflow_to_response(preset) for preset in presets])


@router.get("/tools", response_model=ImageGenerationToolPresetListResponse)
def list_tools() -> ImageGenerationToolPresetListResponse:
    """读取全部生图工具配置列表。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        presets = service.list_tool_presets()
        return ImageGenerationToolPresetListResponse(items=[tool_to_response(preset) for preset in presets])


@router.post("/tools", response_model=ImageGenerationToolPresetResponse, status_code=status.HTTP_201_CREATED)
def create_tool(
    request: ImageGenerationToolPresetRequest,
    http_request: Request,
) -> ImageGenerationToolPresetResponse:
    """创建生图工具配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            preset = service.create_tool_preset(**request.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return tool_to_response(preset)


@router.put("/tools/{tool_id}", response_model=ImageGenerationToolPresetResponse)
def update_tool(
    tool_id: int,
    request: ImageGenerationToolPresetRequest,
    http_request: Request,
) -> ImageGenerationToolPresetResponse:
    """更新生图工具配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            preset = service.update_tool_preset(preset_id=tool_id, **request.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return tool_to_response(preset)


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(tool_id: int, http_request: Request) -> Response:
    """删除生图工具配置。"""

    with SessionLocal() as db_session:
        service = ImageGenerationService(ComicRepository(db_session))
        try:
            service.delete_tool_preset(tool_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/workflows",
    response_model=ComfyWorkflowPresetResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
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


@router.put(
    "/workflows/{workflow_id}",
    response_model=ComfyWorkflowPresetResponse,
    deprecated=True,
)
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


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    deprecated=True,
)
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
def list_generation_pages(
    task_id: int,
    http_request: Request,
    prompt_type: ImagePromptType = ImagePromptType.NATURAL_LANGUAGE,
    generation_mode: GenerationMode = GenerationMode.PREVIEW,
) -> ImageGenerationPageListResponse:
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
            items=[
                page_to_response(
                    page,
                    repo,
                    prompt_type=prompt_type,
                    generation_mode=generation_mode,
                )
                for page in pages
            ],
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
                    tool_preset_id=request.effective_tool_preset_id,
                    poll_interval_seconds=request.poll_interval_seconds,
                    wait_timeout_seconds=request.wait_timeout_seconds,
                    candidates_per_page=request.candidates_per_page,
                    generation_mode=request.generation_mode,
                    seed_strategy=request.seed_strategy,
                ):
                    yield sse_event(event, payload)
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.post("/script-tasks/{task_id}/continue/stream")
def stream_continue_for_script_task(
    task_id: int,
    request: GenerateImagesRequest,
    http_request: Request,
) -> EventSourceResponse:
    """继续批量生成脚本任务下缺少候选图的页面，并用 SSE 返回进度。"""

    locale = request_locale(http_request)

    async def event_generator():
        with SessionLocal() as db_session:
            service = ImageGenerationService(ComicRepository(db_session))
            try:
                async for event, payload in service.stream_continue_for_script_task(
                    task_id=task_id,
                    tool_preset_id=request.effective_tool_preset_id,
                    poll_interval_seconds=request.poll_interval_seconds,
                    wait_timeout_seconds=request.wait_timeout_seconds,
                    candidates_per_page=request.candidates_per_page,
                    generation_mode=request.generation_mode,
                    seed_strategy=request.seed_strategy,
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
                    tool_preset_id=request.effective_tool_preset_id,
                    poll_interval_seconds=request.poll_interval_seconds,
                    wait_timeout_seconds=request.wait_timeout_seconds,
                    candidates_per_page=request.candidates_per_page,
                    generation_mode=request.generation_mode,
                    seed_strategy=request.seed_strategy,
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


@router.get("/runs/{run_id}", response_model=GenerationRunResponse)
def get_generation_run(run_id: int, http_request: Request) -> GenerationRunResponse:
    """读取某张新候选图关联的完整模型、规格、Workflow 和资产溯源。"""

    with SessionLocal() as db_session:
        run = GenerationRepository(db_session).get_run(run_id)
        if run is None:
            raise http_exception(
                ValueError(f"GenerationRun not found: {run_id}"),
                request_locale(http_request),
            )
        return run_to_response(run)
