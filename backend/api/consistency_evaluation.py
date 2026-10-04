"""ViStoryBench 旁路评测、历史查询和人工采用候选 API。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, status
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas.consistency_evaluation import (
    ConsistencyGateResponse,
    ConsistencyReadinessResponse,
    ConsistencyTaskListResponse,
    ConsistencyTaskResponse,
    ConsistencyTrackResponse,
)
from backend.api.scripts import SSE_HEADERS, sse_event
from backend.i18n.errors import http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.models.comic import ConsistencyEvaluationTask, ConsistencyEvaluationTrack
from backend.models.database import SessionLocal
from backend.models.enums import ConsistencyEvaluationStatus
from backend.repositories.consistency_evaluation_repository import (
    ConsistencyEvaluationRepository,
)
from backend.services.consistency_evaluation_runtime import (
    consistency_evaluation_runtime,
)
from backend.services.consistency_evaluation_service import ConsistencyEvaluationService


router = APIRouter(prefix="/api/consistency-evaluations", tags=["consistency-evaluations"])


def track_to_response(track: ConsistencyEvaluationTrack) -> ConsistencyTrackResponse:
    return ConsistencyTrackResponse(
        id=track.id,
        evaluation_task_id=track.evaluation_task_id,
        candidate_index=track.candidate_index,
        status=track.status.value,
        passed=track.passed,
        image_ids=json.loads(track.image_ids_json),
        metrics=json.loads(track.metrics_json),
        details=json.loads(track.details_json),
        error_code=track.error_code,
        error_message=track.error_message,
        adopted_at=track.adopted_at,
        created_at=track.created_at,
        updated_at=track.updated_at,
    )


def task_to_response(task: ConsistencyEvaluationTask) -> ConsistencyTaskResponse:
    return ConsistencyTaskResponse(
        id=task.id,
        batch_task_id=task.batch_task_id,
        script_task_id=task.script_task_id,
        status=task.status.value,
        source_hash=task.source_hash,
        thresholds=json.loads(task.thresholds_json),
        metric_version=task.metric_version,
        progress=json.loads(task.progress_json),
        error_code=task.error_code,
        error_message=task.error_message,
        heartbeat_at=task.heartbeat_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        tracks=[track_to_response(track) for track in task.tracks],
    )


@router.get(
    "/batches/{batch_task_id}/readiness",
    response_model=ConsistencyReadinessResponse,
)
def get_batch_readiness(batch_task_id: int) -> ConsistencyReadinessResponse:
    """只检查评测需要的批次、基准图和环境，不影响出图或选图。"""

    with SessionLocal() as session:
        result = ConsistencyEvaluationService(
            ConsistencyEvaluationRepository(session)
        ).batch_readiness(batch_task_id)
        result.pop("manifest", None)
        return ConsistencyReadinessResponse(**result)


@router.post(
    "/batches/{batch_task_id}",
    response_model=ConsistencyTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_evaluation(
    batch_task_id: int,
    http_request: Request,
) -> ConsistencyTaskResponse:
    """手动创建评估；相同输入、阈值和指标版本保持幂等。"""

    with SessionLocal() as session:
        try:
            task = ConsistencyEvaluationService(
                ConsistencyEvaluationRepository(session)
            ).create_task(batch_task_id)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        response = task_to_response(task)
        if task.status not in {
            ConsistencyEvaluationStatus.SUCCEEDED,
            ConsistencyEvaluationStatus.RUNNING,
            ConsistencyEvaluationStatus.WAITING_RESOURCE,
        }:
            consistency_evaluation_runtime.submit(task.id)
        return response


@router.get("/batches/{batch_task_id}/tasks", response_model=ConsistencyTaskListResponse)
def list_batch_evaluations(batch_task_id: int) -> ConsistencyTaskListResponse:
    with SessionLocal() as session:
        repository = ConsistencyEvaluationRepository(session)
        return ConsistencyTaskListResponse(
            items=[
                task_to_response(task)
                for task in repository.list_batch_tasks(batch_task_id)
            ]
        )


@router.get("/tasks/{task_id}", response_model=ConsistencyTaskResponse)
def get_evaluation(task_id: int, http_request: Request) -> ConsistencyTaskResponse:
    with SessionLocal() as session:
        try:
            task = ConsistencyEvaluationService(
                ConsistencyEvaluationRepository(session)
            ).get_task(task_id)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return task_to_response(task)


@router.get("/tasks/{task_id}/events")
def stream_evaluation_events(task_id: int, http_request: Request) -> EventSourceResponse:
    """从持久化进度生成可重连 SSE，不依赖请求内存保存任务状态。"""

    locale = request_locale(http_request)

    async def event_generator():
        previous = None
        while True:
            with SessionLocal() as session:
                try:
                    task = ConsistencyEvaluationService(
                        ConsistencyEvaluationRepository(session)
                    ).get_task(task_id)
                    payload = task_to_response(task).model_dump(mode="json")
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


@router.post("/tracks/{track_id}/adopt", response_model=ConsistencyTrackResponse)
def adopt_track(track_id: int, http_request: Request) -> ConsistencyTrackResponse:
    """人工采用已完成评测且输入未过期的候选，分数不构成门槛。"""

    with SessionLocal() as session:
        try:
            track = ConsistencyEvaluationService(
                ConsistencyEvaluationRepository(session)
            ).adopt_track(track_id)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return track_to_response(track)


@router.get(
    "/script-tasks/{script_task_id}/gate",
    response_model=ConsistencyGateResponse,
)
def get_script_gate(
    script_task_id: int,
    http_request: Request,
) -> ConsistencyGateResponse:
    with SessionLocal() as session:
        try:
            payload = ConsistencyEvaluationService(
                ConsistencyEvaluationRepository(session)
            ).script_gate(script_task_id)
            return ConsistencyGateResponse(**payload)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
