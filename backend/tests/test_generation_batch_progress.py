"""批次摘要只聚合真实 run/图片，不能随恢复包装任务或心跳重复计数。"""

from datetime import timedelta

from fastapi import Request
import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from backend.api import image_generation as image_api
from backend.models.comic import ComicImage, GenerationRun, GenerationTask, ImageSpec
from backend.models.enums import (
    GenerationMode, GenerationRunStatus, GenerationTaskKind,
    GenerationTaskStatus, ImageGenerationProvider, ImagePromptType,
)
from backend.models.time import utc_now
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.generation_repository import GenerationRepository
from backend.tests.test_reference_batch_snapshot import _setup_batch


def _task(session, script_task, *, parent=None, status=GenerationTaskStatus.SUSPENDED):
    task = GenerationTask(
        project_id=script_task.project_id, script_task_id=script_task.id,
        task_kind=GenerationTaskKind.PAGE if parent else GenerationTaskKind.BATCH,
        parent_task_id=parent.id if parent else None, status=status,
        input_snapshot_json='{"large_frozen_prompt": "must not be read by summary"}',
    )
    session.add(task)
    session.flush()
    return task


def _run(session, batch, child, page, preset, *, candidate=1, status=GenerationRunStatus.SUCCEEDED, images=0):
    spec_id = session.scalar(select(ImageSpec.id).where(
        ImageSpec.page_id == page.id,
        ImageSpec.prompt_type == ImagePromptType.NATURAL_LANGUAGE,
    ))
    run = GenerationRun(
        generation_task_id=child.id, batch_task_id=batch.id, page_id=page.id,
        image_spec_id=spec_id, tool_preset_id=preset.id,
        provider=ImageGenerationProvider.COMFYUI,
        prompt_type=ImagePromptType.NATURAL_LANGUAGE, candidate_index=candidate,
        generation_mode=GenerationMode.FINAL, status=status,
        workflow_json='{"large_workflow": "not a summary field"}',
    )
    session.add(run)
    session.flush()
    for index in range(images):
        session.add(ComicImage(
            generation_run_id=run.id, page_id=page.id, artifact_index=index + 1,
            prompt="full prompt must not be loaded", local_path=f"image-{run.id}-{index}.png",
        ))
    session.flush()
    return run


@pytest.mark.asyncio
async def test_progress_deduplicates_recovered_candidate_and_counts_actual_images(tmp_path, monkeypatch):
    session, task, pages, preset, _client, _service = await _setup_batch(tmp_path, monkeypatch)
    batch = _task(session, task)
    old_child = _task(session, task, parent=batch)
    # 断线恢复复用旧 run；新 wrapper 没有新 run，不能增加已完成候选数。
    recovered = _run(session, batch, old_child, pages[0], preset, images=2)
    wrapper = _task(session, task, parent=batch, status=GenerationTaskStatus.SUCCEEDED)
    retry_child = _task(session, task, parent=batch, status=GenerationTaskStatus.SUCCEEDED)
    _run(session, batch, retry_child, pages[0], preset, images=1)
    _run(session, batch, retry_child, pages[0], preset, candidate=2, status=GenerationRunStatus.FAILED, images=1)
    _run(session, batch, retry_child, pages[0], preset, candidate=2)  # 不能借失败尝试的图算完成。
    _run(session, batch, retry_child, pages[0], preset, candidate=3)  # 成功但无图。
    running = _run(session, batch, old_child, pages[0], preset, candidate=4, status=GenerationRunStatus.RUNNING, images=1)
    _run(session, batch, old_child, pages[0], preset, candidate=5, status=GenerationRunStatus.QUEUED)
    _run(session, batch, old_child, pages[0], preset, candidate=6, status=GenerationRunStatus.PENDING)
    last = _run(session, batch, retry_child, pages[1], preset, images=1)
    last_image_id = session.scalar(select(ComicImage.id).where(ComicImage.generation_run_id == last.id))
    other = _task(session, task)
    _run(session, other, _task(session, task, parent=other), pages[0], preset, images=1)
    empty = _task(session, task)
    session.commit()
    batch_ids = [batch.id, other.id, empty.id]
    expected = {"completed_candidates": 2, "images_count": 6, "latest_image_id": last_image_id, "active_runs": 3}
    progress = GenerationRepository(session).batch_progress(batch_ids)
    assert progress[batch.id] == expected
    assert progress[other.id]["completed_candidates"] == progress[other.id]["images_count"] == 1
    assert progress[empty.id] == {"completed_candidates": 0, "images_count": 0, "latest_image_id": None, "active_runs": 0}
    assert recovered.generation_task_id == old_child.id != wrapper.id

    batch.heartbeat_at = utc_now()
    old_child.heartbeat_at = utc_now() - timedelta(hours=2)
    wrapper.status = GenerationTaskStatus.FAILED
    session.commit()
    assert GenerationRepository(session).batch_progress(batch_ids)[batch.id] == expected
    running.status = GenerationRunStatus.SUCCEEDED
    session.commit()
    expected.update(completed_candidates=3, active_runs=2)
    assert GenerationRepository(session).batch_progress(batch_ids)[batch.id] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_count", [1, 12])
async def test_batch_api_has_constant_query_count_and_never_loads_prompt_snapshots(tmp_path, monkeypatch, batch_count):
    session, task, pages, preset, _client, _service = await _setup_batch(tmp_path, monkeypatch)
    for _ in range(batch_count):
        batch = _task(session, task)
        child = _task(session, task, parent=batch)
        _run(session, batch, child, pages[0], preset, images=1)
    session.commit()
    task_id = task.id
    engine = session.get_bind()
    monkeypatch.setattr(image_api, "SessionLocal", lambda: Session(engine))
    queries = []

    def record_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        queries.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        response = image_api.list_generation_batches(task_id, Request({"type": "http", "headers": []}))
        assert len(response.items) == batch_count
        assert all(item.progress.completed_candidates == item.progress.images_count == 1 for item in response.items)
        assert all(item.progress.active_runs == 0 and item.progress.latest_image_id for item in response.items)
        assert len(queries) == 4  # existence + batch metadata + 两次集合聚合，不按批次逐个查。
        assert all(forbidden not in sql for sql in queries for forbidden in (
            "input_snapshot_json", "applied_spec_json", "workflow_json", "positive_prompt",
            "comic_image.prompt", "section_plan_json",
        ))
        assert "large_frozen_prompt" not in response.model_dump_json()
        queries.clear()
        assert GenerationRepository(session).batch_progress([]) == {}
        assert queries == []
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
    with Session(engine) as fresh_session:
        batches = ComicRepository(fresh_session).list_generation_batches(task_id)
        assert all("input_snapshot_json" in inspect(batch).unloaded for batch in batches)
