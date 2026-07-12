import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.image_spec import (
    CompileImageSpecsRequest,
    ContinuityCompilationResponse,
    ContinuityEventResponse,
    ImageSpecResponse,
    ReplaceContinuityEventsRequest,
    VisualSnapshotResponse,
)
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.i18n.errors import http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.models.comic import ContinuityCompilation
from backend.models.database import SessionLocal
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService


router = APIRouter(prefix="/api/image-specs", tags=["image-specs"])


def compilation_response(item: ContinuityCompilation) -> ContinuityCompilationResponse:
    events = []
    for event in sorted(item.events, key=lambda value: (value.page.page_no, value.sequence_no)):
        events.append(
            ContinuityEventResponse(
                id=event.id,
                page_id=event.page_id,
                page_no=event.page.page_no,
                sequence_no=event.sequence_no,
                event_type=event.event_type.value,
                target_type=event.target_type.value,
                target_key=event.target_key,
                timing=event.timing.value,
                payload=json.loads(event.payload_json),
                source=event.source.value,
            )
        )
    snapshots = [
        VisualSnapshotResponse(
            id=snapshot.id,
            page_id=snapshot.page_id,
            page_no=snapshot.page.page_no,
            state=json.loads(snapshot.state_json),
            state_hash=snapshot.state_hash,
            warnings=json.loads(snapshot.warnings_json),
            created_at=snapshot.created_at,
        )
        for snapshot in sorted(item.snapshots, key=lambda value: value.page.page_no)
    ]
    return ContinuityCompilationResponse(
        id=item.id,
        task_id=item.script_task_id,
        source_hash=item.source_hash,
        status=item.status.value,
        events=events,
        snapshots=snapshots,
        created_at=item.created_at,
    )


@router.get(
    "/script-tasks/{task_id}",
    response_model=list[ImageSpecResponse],
)
def list_task_specs(
    task_id: int,
    request: Request,
    model_profile_id: int | None = None,
) -> list[ImageSpecResponse]:
    with SessionLocal() as session:
        service = ImageSpecService(ImageSpecRepository(session))
        try:
            items = service.list_task_specs(
                task_id=task_id,
                model_profile_id=model_profile_id,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return [ImageSpecResponse.model_validate(item) for item in items]


@router.get(
    "/script-tasks/{task_id}/continuity",
    response_model=list[ContinuityCompilationResponse],
)
def list_continuity_compilations(
    task_id: int,
    request: Request,
) -> list[ContinuityCompilationResponse]:
    with SessionLocal() as session:
        repository = ImageSpecRepository(session)
        if repository.get_script_task(task_id) is None:
            raise http_exception(
                ValueError(f"ScriptGenerationTask not found: {task_id}"),
                request_locale(request),
            )
        return [
            compilation_response(item)
            for item in repository.list_compilations(task_id)
        ]


@router.post("/script-tasks/{task_id}/compile/stream")
def compile_task_stream(
    task_id: int,
    payload: CompileImageSpecsRequest,
    request: Request,
) -> EventSourceResponse:
    locale = request_locale(request)

    async def event_generator():
        with SessionLocal() as session:
            service = ImageSpecService(ImageSpecRepository(session))
            try:
                async for event, data in service.stream_compile_task(
                    task_id=task_id,
                    **payload.model_dump(),
                ):
                    yield sse_event(event, data)
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator(), headers=SSE_HEADERS, ping=5)


@router.put(
    "/compilations/{compilation_id}/events",
    response_model=ContinuityCompilationResponse,
)
async def replace_continuity_events(
    compilation_id: int,
    payload: ReplaceContinuityEventsRequest,
    request: Request,
) -> ContinuityCompilationResponse:
    with SessionLocal() as session:
        service = ImageSpecService(ImageSpecRepository(session))
        try:
            result = await service.replace_events(
                compilation_id=compilation_id,
                events=[event.model_dump(mode="json") for event in payload.events],
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return compilation_response(result)
