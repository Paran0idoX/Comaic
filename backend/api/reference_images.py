"""独立原图的素材目录和通用参考图任务 API；旧人物路由继续共享任务。"""

import asyncio
import json
from functools import partial

from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from backend.api.character_reference import task_response
from backend.api.schemas.reference_images import (AssignReferenceSubjectRequest, CreateReferenceTaskRequest, CreateReferenceBatchRequest,
    ReferencePromptPreviewRequest, ReferencePromptPreviewResponse, ReferencePromptBatchPreviewRequest, ReferenceSubjectCreate,
    ReferenceSubjectListResponse, ReferenceSubjectResponse, ReferenceSubjectUpdate,
    ReferenceTaskListResponse, ReferenceTaskResponse)
from backend.api.schemas.visual_bible import VisualAssetResponse
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.api.visual_bible import asset_response
from backend.i18n.errors import http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.models.database import SessionLocal
from backend.models.enums import VisualEntityType, CompilationStatus
from backend.repositories.character_reference_repository import CharacterReferenceRepository
from backend.repositories.reference_subject_repository import ReferenceSubjectRepository
from backend.services.character_reference_runtime import character_reference_runtime
from backend.services.reference_prompt_runtime import reference_prompt_runtime, REFERENCE_PROMPT_WORKERS
from backend.services.reference_catalog import REFERENCE_CATALOG, selected_task_roles
from backend.services.reference_image_service import ReferenceImageService
from backend.services.reference_subject_service import ReferenceSubjectService
from backend.services.reference_visual_profile_service import ReferenceVisualProfileService
from backend.models.reference_visual import ReferenceProfileUpdate, ReferenceProfileResponse


router = APIRouter(prefix="/api/reference-images", tags=["reference-images"])


def subject_response(subject):
    return ReferenceSubjectResponse(**{field: getattr(subject, field) for field in ReferenceSubjectResponse.model_fields})


def reference_task_response(task):
    values = task_response(task).model_dump()
    snapshot = json.loads(task.subject_snapshot_json or "{}")
    sizes = {}
    for run in task.runs:
        render = json.loads(run.applied_spec_json or "{}").get("render", {})
        if render.get("width") and render.get("height"):
            sizes[run.role.value] = {"width": render["width"], "height": render["height"]}
    return ReferenceTaskResponse(**values, entity_type=task.entity_type,
        entity_id=task.entity_id if task.entity_id is not None else task.outline_character_id,
        entity_key=task.entity_key, reference_subject_id=task.reference_subject_id,
        outfit_variant_id=task.outfit_variant_id, subject_name=snapshot.get("name") or values["character_name"],
        selected_roles=selected_task_roles(task), source_asset_ids=json.loads(task.source_asset_ids_json or "[]"), sizes=sizes)


def service(session):
    return ReferenceImageService(CharacterReferenceRepository(session))


@router.get("/catalog")
def catalog():
    return {"categories": [{"entity_type": category.value, "roles": [
        {"role": role.value, "label_key": f"visualBible.roleLabels.{role.value}"} for role in roles
    ]} for category, roles in REFERENCE_CATALOG.items()]}


@router.get("/projects/{project_id}/subjects", response_model=ReferenceSubjectListResponse)
def list_subjects(project_id: int, request: Request, entity_type: VisualEntityType | None = None):
    with SessionLocal() as session:
        try:
            subjects = ReferenceSubjectService(ReferenceSubjectRepository(session)).list(project_id, entity_type)
            return ReferenceSubjectListResponse(items=[subject_response(item) for item in subjects])
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.post("/projects/{project_id}/subjects", response_model=ReferenceSubjectResponse, status_code=201)
def create_subject(project_id: int, payload: ReferenceSubjectCreate, request: Request):
    with SessionLocal() as session:
        try:
            subject = ReferenceSubjectService(ReferenceSubjectRepository(session)).create(project_id=project_id, **payload.model_dump())
            return subject_response(subject)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.put("/subjects/{subject_id}", response_model=ReferenceSubjectResponse)
def update_subject(subject_id: int, payload: ReferenceSubjectUpdate, request: Request):
    with SessionLocal() as session:
        try:
            subject = ReferenceSubjectService(ReferenceSubjectRepository(session)).update(subject_id, **payload.model_dump())
            return subject_response(subject)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.put("/script-scenes/{scene_id}/subject")
def assign_subject(scene_id: int, payload: AssignReferenceSubjectRequest, request: Request):
    with SessionLocal() as session:
        try:
            scene = ReferenceSubjectService(ReferenceSubjectRepository(session)).assign_scene(scene_id, payload.reference_subject_id)
            return {"id": scene.id, "reference_subject_id": scene.reference_subject_id}
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


def prepare_preview(project_id: int, payload: ReferencePromptPreviewRequest):
    """在线程池内创建会话、提炼摘要并编译响应，绝不跨线程传递 ORM 对象。"""
    with SessionLocal() as session:
        context = service(session).preview_reference_prompts(project_id=project_id, **payload.model_dump())
        return ReferencePromptPreviewResponse(entity_type=payload.entity_type, entity_id=payload.entity_id,
            reference_subject_id=payload.reference_subject_id, outfit_variant_id=payload.outfit_variant_id,
            subject_name=context["snapshot"]["name"], tool_preset_id=context["tool"].id,
            prompt_type=context["tool"].prompt_type.value, selected_roles=context["roles"],
            source_asset_ids=[asset.id for asset in context["sources"]], prompts=context["prompts"],
            canvas_asset_id=payload.canvas_asset_id, warnings=context["warnings"], sizes=context["sizes"],
            visual_profiles=context["visual_profiles"])


@router.post("/projects/{project_id}/prompt-preview", response_model=ReferencePromptPreviewResponse)
async def preview(project_id: int, payload: ReferencePromptPreviewRequest, request: Request):
    try:
        return await reference_prompt_runtime.run(partial(prepare_preview, project_id, payload))
    except Exception as exc:
        raise http_exception(exc, request_locale(request)) from exc


@router.post("/projects/{project_id}/prompt-preview/batch")
async def preview_batch(project_id: int, payload: ReferencePromptBatchPreviewRequest, request: Request):
    """后端一次接收所有对象，专用五线程池调度，逐项推送开始和完成状态。"""
    locale = request_locale(request)
    async def generator():
        yield sse_event("accepted", {"project_id": project_id, "total": len(payload.items), "concurrency": REFERENCE_PROMPT_WORKERS})
        operations = [partial(prepare_preview, project_id, item) for item in payload.items]
        completed = failed = 0
        async for index, state, value in reference_prompt_runtime.stream(operations):
            event = {"project_id": project_id, "index": index, "status": state.value}
            if state == CompilationStatus.SUCCEEDED:
                completed += 1
                event["preview"] = value.model_dump(mode="json")
            elif state == CompilationStatus.FAILED:
                failed += 1
                event["error"] = sse_error_payload(value, locale)
            yield sse_event("item", event)
        yield sse_event("done", {"project_id": project_id, "total": len(payload.items), "completed": completed, "failed": failed})
    return EventSourceResponse(generator(), headers=SSE_HEADERS, ping=5)


@router.post("/projects/{project_id}/tasks", response_model=ReferenceTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_task(project_id: int, payload: CreateReferenceTaskRequest, request: Request):
    with SessionLocal() as session:
        try:
            values = payload.model_dump()
            task = service(session).create_reference_task(project_id=project_id, **values)
            result = reference_task_response(task)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc
    character_reference_runtime.submit(task.id)
    return result


@router.put("/visual-profiles/{profile_id}", response_model=ReferenceProfileResponse)
def update_visual_profile(profile_id: int, payload: ReferenceProfileUpdate, request: Request):
    """人工修正只保存摘要；客户端用缓存重新编译，修订冲突要求重新准备。"""
    with SessionLocal() as session:
        try:
            return ReferenceVisualProfileService(session).update(profile_id, payload.expected_revision, payload.data)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.get("/projects/{project_id}/tasks", response_model=ReferenceTaskListResponse)
def list_tasks(project_id: int, request: Request, entity_type: VisualEntityType | None = None,
               entity_id: int | None = None, reference_subject_id: int | None = None):
    with SessionLocal() as session:
        try:
            tasks = service(session).list_project_tasks(project_id, entity_type=entity_type,
                entity_id=entity_id, reference_subject_id=reference_subject_id)
            return ReferenceTaskListResponse(items=[reference_task_response(item) for item in tasks])
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.post("/projects/{project_id}/tasks/batch", response_model=ReferenceTaskListResponse, status_code=status.HTTP_202_ACCEPTED)
def create_batch(project_id: int, payload: CreateReferenceBatchRequest, request: Request):
    """整批持久化成功后再入队，关闭页面不会中断后续对象的生成。"""
    with SessionLocal() as session:
        try:
            tasks = service(session).create_reference_tasks(
                project_id=project_id, items=[item.model_dump() for item in payload.items],
            )
            result = ReferenceTaskListResponse(items=[reference_task_response(task) for task in tasks])
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc
    for task in result.items:
        character_reference_runtime.submit(task.id)
    return result


@router.get("/tasks/{task_id}", response_model=ReferenceTaskResponse)
def get_task(task_id: int, request: Request):
    with SessionLocal() as session:
        try:
            return reference_task_response(service(session).get_task(task_id))
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.get("/tasks/{task_id}/events")
def events(task_id: int, request: Request):
    """只发布持久化快照，离页和连接重建不会改变正在运行的任务。"""
    async def generator():
        previous = None
        while True:
            with SessionLocal() as session:
                try:
                    payload = reference_task_response(service(session).get_task(task_id)).model_dump(mode="json")
                except Exception as exc:
                    yield sse_event("error", sse_error_payload(exc, request_locale(request)))
                    return
            serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if serialized != previous:
                yield sse_event("progress", payload)
                previous = serialized
            if payload["status"] in {"succeeded", "failed", "suspended"}:
                yield sse_event("done", payload)
                return
            await asyncio.sleep(1)
    return EventSourceResponse(generator(), headers=SSE_HEADERS, ping=5)


@router.post("/tasks/{task_id}/suspend", response_model=ReferenceTaskResponse)
def suspend(task_id: int, request: Request):
    with SessionLocal() as session:
        try:
            return reference_task_response(service(session).suspend_task(task_id))
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.post("/tasks/{task_id}/continue", response_model=ReferenceTaskResponse, status_code=202)
def continue_task(task_id: int, request: Request):
    with SessionLocal() as session:
        try:
            task = service(session).prepare_continue(task_id)
            result = reference_task_response(task)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc
    character_reference_runtime.submit(task.id)
    return result


@router.post("/images/{image_id}/approve", response_model=VisualAssetResponse)
def approve_image(image_id: int, request: Request):
    with SessionLocal() as session:
        try:
            return asset_response(service(session).approve_image(image_id))
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc


@router.get("/images/{image_id}/file")
def image_file(image_id: int, request: Request):
    with SessionLocal() as session:
        try:
            path, mime_type = service(session).artifact_file(image_id)
            return FileResponse(path, media_type=mime_type)
        except Exception as exc:
            raise http_exception(exc, request_locale(request)) from exc
