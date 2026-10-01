"""人物参考图三件套的 Prompt、后台任务、SSE 与整套批准 API。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.character_reference import (
    CharacterReferenceCharacterListResponse,
    CharacterReferenceCharacterResponse,
    CharacterReferenceCandidateSetResponse,
    CharacterReferenceImageResponse,
    CharacterReferencePromptPreviewRequest,
    CharacterReferencePromptPreviewResponse,
    CharacterReferencePromptPair,
    CharacterReferenceRunResponse,
    CharacterReferenceTaskListResponse,
    CharacterReferenceTaskResponse,
    CreateCharacterReferenceTaskRequest,
)
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.i18n.errors import http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.models.comic import (
    CharacterReferenceGenerationRun,
    CharacterReferenceGenerationTask,
    CharacterReferenceImage,
)
from backend.models.database import SessionLocal
from backend.models.enums import (
    ApprovalStatus,
    GenerationRunStatus,
)
from backend.repositories.character_reference_repository import (
    CharacterReferenceRepository,
)
from backend.services.character_reference_runtime import character_reference_runtime
from backend.services.character_reference_service import CharacterReferenceService
from backend.services.reference_catalog import selected_task_roles


router = APIRouter(prefix="/api/character-references", tags=["character-references"])


@router.get(
    "/projects/{project_id}/outline-characters",
    response_model=CharacterReferenceCharacterListResponse,
)
def list_project_outline_characters(
    project_id: int,
    http_request: Request,
) -> CharacterReferenceCharacterListResponse:
    """无脚本任务时也可展示项目当前已确认大纲里的全部角色。"""

    with SessionLocal() as session:
        try:
            characters = service_for_session(session).list_project_outline_characters(
                project_id
            )
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return CharacterReferenceCharacterListResponse(
            items=[
                CharacterReferenceCharacterResponse(
                    id=character.id,
                    outline_version_id=character.outline_version_id,
                    character_key=character.character_key,
                    name=character.name,
                    visual_type=character.visual_type,
                )
                for character in characters
            ]
        )


@router.get(
    "/outline-versions/{outline_version_id}/characters",
    response_model=CharacterReferenceCharacterListResponse,
)
def list_outline_characters(
    outline_version_id: int,
    http_request: Request,
) -> CharacterReferenceCharacterListResponse:
    """返回大纲版本的完整角色集合，避免只显示当前脚本中已出场角色。"""

    with SessionLocal() as session:
        try:
            characters = service_for_session(session).list_outline_characters(
                outline_version_id
            )
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return CharacterReferenceCharacterListResponse(
            items=[
                CharacterReferenceCharacterResponse(
                    id=character.id,
                    outline_version_id=character.outline_version_id,
                    character_key=character.character_key,
                    name=character.name,
                    visual_type=character.visual_type,
                )
                for character in characters
            ]
        )


def image_response(image: CharacterReferenceImage) -> CharacterReferenceImageResponse:
    return CharacterReferenceImageResponse(
        id=image.id,
        artifact_index=image.artifact_index,
        image_url=f"/api/character-references/images/{image.id}/file",
        sha256=image.sha256,
        width=image.width,
        height=image.height,
        promoted_asset_id=image.promoted_asset_id,
    )


def run_response(
    run: CharacterReferenceGenerationRun,
) -> CharacterReferenceRunResponse:
    images = [image_response(image) for image in run.images]
    primary = next((image for image in images if image.artifact_index == 1), None)
    try:
        degradations = json.loads(run.degradation_json or "[]")
    except json.JSONDecodeError:
        degradations = []
    return CharacterReferenceRunResponse(
        id=run.id,
        candidate_index=run.candidate_index,
        role=run.role,
        seed=run.seed,
        provider=run.provider,
        prompt_type=run.prompt_type,
        positive_prompt=run.positive_prompt,
        negative_prompt=run.negative_prompt,
        status=run.status,
        review_status=run.review_status,
        seed_applied=run.seed_applied,
        external_request_id=run.external_request_id,
        degradations=degradations if isinstance(degradations, list) else [],
        error_code=run.error_code,
        images=images,
        primary_image=primary,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def candidate_response(
    runs: list[CharacterReferenceGenerationRun],
    expected_roles: tuple | None = None,
) -> CharacterReferenceCandidateSetResponse:
    role_responses = {run.role.value: run_response(run) for run in runs}
    expected = {role.value for role in expected_roles} if expected_roles else {"identity_face", "identity_half_body", "identity_full_body"}
    complete = set(role_responses) == expected and all(
        run.status == GenerationRunStatus.SUCCEEDED
        and any(image.artifact_index == 1 for image in run.images)
        for run in runs
    )
    if complete:
        generation_status = "succeeded"
    elif any(run.status == GenerationRunStatus.FAILED for run in runs):
        generation_status = "failed"
    elif any(
        run.status in {GenerationRunStatus.RUNNING, GenerationRunStatus.QUEUED}
        for run in runs
    ):
        generation_status = "running"
    else:
        generation_status = "pending"
    review_status = (
        ApprovalStatus.APPROVED
        if runs and all(run.review_status == ApprovalStatus.APPROVED for run in runs)
        else ApprovalStatus.ARCHIVED
        if runs and all(run.review_status == ApprovalStatus.ARCHIVED for run in runs)
        else ApprovalStatus.DRAFT
    )
    return CharacterReferenceCandidateSetResponse(
        candidate_index=runs[0].candidate_index,
        seed=runs[0].seed,
        status=generation_status,
        review_status=review_status,
        complete=complete,
        roles=role_responses,
    )


def task_response(
    task: CharacterReferenceGenerationTask,
) -> CharacterReferenceTaskResponse:
    grouped: dict[int, list[CharacterReferenceGenerationRun]] = {}
    for run in task.runs:
        grouped.setdefault(run.candidate_index, []).append(run)
    try:
        prompts = json.loads(task.prompt_snapshot_json or "{}")
    except json.JSONDecodeError:
        prompts = {}
    try:
        progress = json.loads(task.progress_json or "{}")
    except json.JSONDecodeError:
        progress = {}
    return CharacterReferenceTaskResponse(
        id=task.id,
        project_id=task.project_id,
        outline_character_id=task.outline_character_id,
        character_name=(
            task.outline_character.name or task.outline_character.character_key
        ) if task.outline_character is not None else json.loads(task.subject_snapshot_json or "{}").get("name", ""),
        tool_preset_id=task.tool_preset_id,
        tool_name=task.tool_preset.name,
        style_profile_id=task.style_profile_id,
        status=task.status,
        candidate_count=task.candidate_count,
        prompt_type=task.prompt_type,
        prompts={
            key: CharacterReferencePromptPair(**value)
            for key, value in prompts.items()
            if isinstance(value, dict)
        },
        progress=progress if isinstance(progress, dict) else {},
        approved_candidate_index=task.approved_candidate_index,
        error_code=task.error_code,
        heartbeat_at=task.heartbeat_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        candidates=[candidate_response(grouped[index], selected_task_roles(task)) for index in sorted(grouped)],
    )


def service_for_session(session) -> CharacterReferenceService:
    return CharacterReferenceService(CharacterReferenceRepository(session))


@router.post(
    "/outline-characters/{character_id}/prompt-preview",
    response_model=CharacterReferencePromptPreviewResponse,
)
def preview_prompts(
    character_id: int,
    payload: CharacterReferencePromptPreviewRequest,
    http_request: Request,
) -> CharacterReferencePromptPreviewResponse:
    with SessionLocal() as session:
        try:
            tool, prompts = service_for_session(session).preview_prompts(
                character_id=character_id,
                tool_preset_id=payload.tool_preset_id,
                style_profile_id=payload.style_profile_id,
            )
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return CharacterReferencePromptPreviewResponse(
            character_id=character_id,
            tool_preset_id=tool.id,
            style_profile_id=payload.style_profile_id,
            prompt_type=tool.prompt_type,
            prompts={
                role: CharacterReferencePromptPair(**prompt)
                for role, prompt in prompts.items()
            },
        )


@router.post(
    "/outline-characters/{character_id}/tasks",
    response_model=CharacterReferenceTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_task(
    character_id: int,
    payload: CreateCharacterReferenceTaskRequest,
    http_request: Request,
) -> CharacterReferenceTaskResponse:
    with SessionLocal() as session:
        try:
            task = service_for_session(session).create_task(
                character_id=character_id,
                tool_preset_id=payload.tool_preset_id,
                style_profile_id=payload.style_profile_id,
                candidate_count=payload.candidate_count,
                prompts={
                    role: prompt.model_dump()
                    for role, prompt in payload.prompts.items()
                },
            )
            response = task_response(task)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
    character_reference_runtime.submit(task.id)
    return response


@router.get(
    "/outline-characters/{character_id}/tasks",
    response_model=CharacterReferenceTaskListResponse,
)
def list_tasks(
    character_id: int,
    http_request: Request,
) -> CharacterReferenceTaskListResponse:
    with SessionLocal() as session:
        try:
            tasks = service_for_session(session).list_character_tasks(character_id)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return CharacterReferenceTaskListResponse(
            items=[task_response(task) for task in tasks]
        )


@router.get("/tasks/{task_id}", response_model=CharacterReferenceTaskResponse)
def get_task(task_id: int, http_request: Request) -> CharacterReferenceTaskResponse:
    with SessionLocal() as session:
        try:
            return task_response(service_for_session(session).get_task(task_id))
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc


@router.get("/tasks/{task_id}/events")
def stream_task_events(task_id: int, http_request: Request) -> EventSourceResponse:
    """从数据库任务快照生成可重连 SSE，断开连接不会停止后台生成。"""

    locale = request_locale(http_request)

    async def event_generator():
        previous = None
        while True:
            with SessionLocal() as session:
                try:
                    payload = task_response(
                        service_for_session(session).get_task(task_id)
                    ).model_dump(mode="json")
                except Exception as exc:
                    yield sse_event("error", sse_error_payload(exc, locale))
                    return
            current = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if current != previous:
                yield sse_event("progress", payload)
                previous = current
            if payload["status"] in {"succeeded", "failed", "suspended"}:
                yield sse_event("done", payload)
                return
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.post(
    "/tasks/{task_id}/suspend",
    response_model=CharacterReferenceTaskResponse,
)
def suspend_task(task_id: int, http_request: Request) -> CharacterReferenceTaskResponse:
    with SessionLocal() as session:
        try:
            return task_response(service_for_session(session).suspend_task(task_id))
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc


@router.post(
    "/tasks/{task_id}/continue",
    response_model=CharacterReferenceTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def continue_task(
    task_id: int, http_request: Request
) -> CharacterReferenceTaskResponse:
    with SessionLocal() as session:
        try:
            task = service_for_session(session).prepare_continue(task_id)
            response = task_response(task)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
    character_reference_runtime.submit(task.id)
    return response


@router.post(
    "/tasks/{task_id}/candidate-sets/{candidate_index}/approve",
    response_model=CharacterReferenceTaskResponse,
)
def approve_candidate_set(
    task_id: int,
    candidate_index: int,
    http_request: Request,
) -> CharacterReferenceTaskResponse:
    with SessionLocal() as session:
        try:
            task = service_for_session(session).approve_candidate_set(
                task_id=task_id,
                candidate_index=candidate_index,
            )
            return task_response(task)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, http_request: Request) -> FileResponse:
    with SessionLocal() as session:
        try:
            path, mime_type = service_for_session(session).artifact_file(image_id)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return FileResponse(path, media_type=mime_type)
