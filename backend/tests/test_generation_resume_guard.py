"""暂停中的外部请求不能被第二个 generator 重复提交；全部使用模拟 Provider。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.i18n.errors import AppError, error_payload
from backend.models.comic import ComicImage, GenerationRun, GenerationTask
from backend.models.enums import GenerationMode, GenerationRunStatus, GenerationTaskStatus, ImageGenerationProvider
from backend.models.time import utc_now
from backend.repositories.comic_repository import ComicRepository
from backend.services.image_generation_service import ImageGenerationService
from backend.services.renderer_backends import ComfyUIBackend
from backend.services.task_runtime import RunningTaskRegistry, RuntimeTaskType, ZOMBIE_TIMEOUT_SECONDS
from backend.tests.test_reference_batch_snapshot import _setup_batch


@pytest.fixture
def registry(monkeypatch):
    value = RunningTaskRegistry()
    monkeypatch.setattr("backend.services.image_generation_service.running_task_registry", value)
    return value


def continue_stream(service, batch_id, preset_id):
    return service.stream_continue_for_batch(
        batch_task_id=batch_id, tool_preset_id=preset_id,
        generation_mode=GenerationMode.FINAL, candidates_per_page=1,
    )


async def start_until_queued(service, task_id, preset_id):
    stream = service.stream_generate_for_script_task(
        task_id=task_id, tool_preset_id=preset_id,
        generation_mode=GenerationMode.FINAL, candidates_per_page=1,
    )
    event, payload = await anext(stream)
    assert event == "start"
    batch_id = payload["task_id"]
    while event != "queued":
        event, payload = await anext(stream)
    return stream, batch_id, payload["generation_run_id"]


def assert_busy(exc):
    assert isinstance(exc, AppError)
    assert exc.code == "image_generation.batch_busy"
    assert exc.status_code == 409
    assert error_payload(exc, "zh")["message"] == "当前批次仍在处理页面，请等待当前页面完成后再继续。"
    assert "Wait for the current page" in error_payload(exc, "en")["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "running"])
async def test_pause_during_request_rejects_continue_without_resubmission(tmp_path, monkeypatch, registry, phase):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original_wait = ComfyUIBackend.wait

    async def waiting(backend, submission, **kwargs):
        entered.set()
        await release.wait()
        return await original_wait(backend, submission, **kwargs)

    if phase == "running":
        monkeypatch.setattr(ComfyUIBackend, "wait", waiting)
    stream, batch_id, run_id = await start_until_queued(service, task.id, preset.id)
    pending = None
    other_session = Session(session.get_bind())
    other = ImageGenerationService(ComicRepository(other_session), comfy_client=client, output_dir=tmp_path / "other")
    try:
        if phase == "running":
            pending = asyncio.create_task(anext(stream))
            await asyncio.wait_for(entered.wait(), 2)
        other.suspend_generation_task(batch_id)
        before = (len(client.uploads), len(client.queued), len(other_session.scalars(select(GenerationRun)).all()))
        with pytest.raises(AppError) as caught:
            await anext(continue_stream(other, batch_id, preset.id))
        assert_busy(caught.value)
        assert before == (len(client.uploads), len(client.queued), len(other_session.scalars(select(GenerationRun)).all()))
        assert batch_id in registry.snapshot_ids()[1]
        assert other.repository.get_generation_task_status(batch_id) == GenerationTaskStatus.SUSPENDED
        release.set()
        if pending is not None:
            await pending
        remaining = [item async for item in stream]
        assert remaining[-1][0] == "suspended"
        assert registry.snapshot_ids()[1] == set()
        resumed = [item async for item in continue_stream(other, batch_id, preset.id)]
        assert [data["page_id"] for event, data in resumed if event == "page_done"] == [pages[1].id]
        assert len(client.queued) == 2
        assert other_session.get(GenerationRun, run_id).status == GenerationRunStatus.SUCCEEDED
    finally:
        release.set()
        if pending is not None and not pending.done():
            await pending
        await stream.aclose()
        other_session.close()
        session.close()


@pytest.mark.asyncio
async def test_simultaneous_continues_claim_once_and_close_releases(tmp_path, monkeypatch, registry):
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    initial = service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL)
    batch_id = (await anext(initial))[1]["task_id"]
    await initial.aclose()
    assert registry.snapshot_ids()[1] == set()
    first, second = continue_stream(service, batch_id, preset.id), continue_stream(service, batch_id, preset.id)
    results = await asyncio.gather(anext(first), anext(second), return_exceptions=True)
    try:
        assert sum(isinstance(result, tuple) for result in results) == 1
        assert_busy(next(result for result in results if isinstance(result, Exception)))
        assert batch_id in registry.snapshot_ids()[1]
        assert client.queued == []
    finally:
        await first.aclose()
        await second.aclose()
    assert registry.snapshot_ids()[1] == set()
    assert session.get(GenerationTask, batch_id).status == GenerationTaskStatus.SUSPENDED
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    assert len(client.queued) == 2
    session.close()


@pytest.mark.asyncio
async def test_preflight_failure_releases_continuation_claim(tmp_path, monkeypatch, registry):
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    initial = service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL)
    batch_id = (await anext(initial))[1]["task_id"]
    await initial.aclose()
    original = service._get_tool_preset

    def fail(_preset_id):
        raise ValueError("preflight failure")

    monkeypatch.setattr(service, "_get_tool_preset", fail)
    with pytest.raises(ValueError, match="preflight failure"):
        await anext(continue_stream(service, batch_id, preset.id))
    assert registry.snapshot_ids()[1] == set()
    assert client.queued == []
    monkeypatch.setattr(service, "_get_tool_preset", original)
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_status", [GenerationTaskStatus.RUNNING, GenerationTaskStatus.SUSPENDED])
async def test_stale_orphan_waits_for_external_completion_then_recovers_original_run(tmp_path, monkeypatch, registry, stale_status):
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    entered = asyncio.Event()
    original_wait = ComfyUIBackend.wait

    async def waiting(_backend, _submission, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ComfyUIBackend, "wait", waiting)
    stream, batch_id, run_id = await start_until_queued(service, task.id, preset.id)
    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(entered.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert registry.snapshot_ids()[1] == set()
    assert session.get(GenerationTask, batch_id).status == GenerationTaskStatus.SUSPENDED
    run = session.get(GenerationRun, run_id)
    assert run.status == GenerationRunStatus.RUNNING
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert_busy(caught.value)
    assert len(client.queued) == 1
    # 模拟重启失联并经过现有僵尸超时；历史 run 可仍处于非终态。
    run.generation_task.status = stale_status
    run.generation_task.heartbeat_at = utc_now() - timedelta(seconds=ZOMBIE_TIMEOUT_SECONDS + 1)
    session.commit()
    monkeypatch.setattr(ComfyUIBackend, "wait", original_wait)
    monkeypatch.setattr(client, "get_queue", lambda: {"queue_running": [[0, run.external_request_id, {}, {}]], "queue_pending": []})
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert_busy(caught.value)
    assert len(client.queued) == 1
    assert registry.snapshot_ids()[1] == set()
    monkeypatch.setattr(client, "get_queue", lambda: {"queue_running": [], "queue_pending": []})
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    assert len(client.queued) == 2
    assert session.get(GenerationRun, run_id).status == GenerationRunStatus.SUCCEEDED
    assert len(session.scalars(select(GenerationRun)).all()) == 2
    assert registry.snapshot_ids()[1] == set()
    session.close()


async def interrupted_batch(tmp_path, monkeypatch, *, after_image=False):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    stream, batch_id, run_id = await start_until_queued(service, task.id, preset.id)
    if after_image:
        assert (await anext(stream))[0] == "image"
    await stream.aclose()
    run = session.get(GenerationRun, run_id)
    run.generation_task.status = GenerationTaskStatus.SUSPENDED
    run.generation_task.heartbeat_at = utc_now() - timedelta(seconds=ZOMBIE_TIMEOUT_SECONDS + 1)
    session.commit()
    return session, pages, preset, client, service, batch_id, run


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unreachable", "malformed_queue", "missing_history", "incomplete_history", "pending"])
async def test_unknown_or_pending_external_request_never_resubmits(tmp_path, monkeypatch, registry, failure):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    if failure == "unreachable":
        def unavailable():
            raise ConnectionError("offline")
        monkeypatch.setattr(client, "get_queue", unavailable)
    elif failure == "malformed_queue":
        monkeypatch.setattr(client, "get_queue", lambda: {})
    elif failure == "missing_history":
        monkeypatch.setattr(client, "get_history", lambda _key: {})
    elif failure == "incomplete_history":
        monkeypatch.setattr(client, "get_history", lambda key: {key: {"status": {"completed": False, "status_str": "success"}}})
    else:
        monkeypatch.setattr(client, "get_queue", lambda: {"queue_running": [], "queue_pending": [[1, run.external_request_id, {}, {}]]})
    before = (len(client.uploads), len(client.queued))
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert caught.value.status_code == 409
    assert caught.value.code == ("image_generation.batch_busy" if failure == "pending" else "image_generation.batch_recovery_unavailable")
    assert before == (len(client.uploads), len(client.queued))
    assert session.get(GenerationRun, run.id).status == GenerationRunStatus.QUEUED
    assert registry.snapshot_ids()[1] == set()
    session.close()


@pytest.mark.asyncio
async def test_success_history_reuses_partial_artifact_and_frozen_address(tmp_path, monkeypatch, registry):
    session, pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch, after_image=True)
    original_image = session.scalar(select(ComicImage))
    original_image_id = original_image.id
    original_uploads = len(client.uploads)
    preset.comfy_base_url = "http://different-service.invalid"
    session.commit()
    calls = []
    original_history = client.get_history

    def history(key):
        calls.append((client.base_url, key))
        return original_history(key)

    monkeypatch.setattr(client, "get_history", history)
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    assert calls[0] == ("http://mock-comfy.invalid", run.external_request_id)
    assert json.loads(session.get(GenerationRun, run.id).applied_spec_json)["renderer_config"]["comfy_base_url"] == client.base_url
    assert len(client.queued) == 2
    assert len(client.uploads) == original_uploads + 3  # 只上传第二页的原图。
    images = session.scalars(select(ComicImage).where(ComicImage.page_id == pages[0].id)).all()
    assert [image.id for image in images] == [original_image_id]
    assert images[0].generation_run_id == run.id
    session.close()


def failed_history(key):
    return {key: {"status": {"completed": False, "status_str": "error", "messages": [["execution_error", {"exception_message": "failed"}]]}}}


@pytest.mark.asyncio
async def test_confirmed_execution_failure_allows_retry(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    original_history = client.get_history
    external_id = run.external_request_id
    monkeypatch.setattr(client, "get_history", lambda key: failed_history(key) if key == external_id else original_history(key))
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    assert len(client.queued) == 3  # 原请求确认失败后才允许补发第一页。
    assert session.get(GenerationRun, run.id).status == GenerationRunStatus.FAILED
    session.close()


@pytest.mark.asyncio
async def test_older_successful_history_is_not_overridden_by_newer_failure(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    fields = ("generation_task_id", "batch_task_id", "page_id", "image_spec_id", "tool_preset_id", "provider", "prompt_type", "candidate_index", "seed", "seed_strategy", "generation_mode", "bindings_json", "resolved_assets_json", "degradation_json", "applied_spec_json")
    newer = GenerationRun(**{key: getattr(run, key) for key in fields}, status=GenerationRunStatus.QUEUED, external_request_id="newer-failed")
    session.add(newer)
    session.commit()
    original_history = client.get_history
    monkeypatch.setattr(client, "get_history", lambda key: failed_history(key) if key == "newer-failed" else original_history(key))
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    assert len(client.queued) == 2
    assert session.get(GenerationRun, run.id).status == GenerationRunStatus.SUCCEEDED
    assert session.get(GenerationRun, newer.id).status == GenerationRunStatus.FAILED
    session.close()


@pytest.mark.asyncio
async def test_provider_without_request_lookup_preserves_orphan(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    run.provider = ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE
    session.commit()
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert caught.value.code == "image_generation.batch_recovery_unsupported"
    assert caught.value.status_code == 409
    assert len(client.queued) == 1
    assert session.get(GenerationRun, run.id).status == GenerationRunStatus.QUEUED
    session.close()


@pytest.mark.asyncio
async def test_timed_out_run_still_running_externally_is_not_retried(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    run.status = GenerationRunStatus.FAILED
    run.error_code = "image_generation.comfyui_timeout"
    session.commit()
    monkeypatch.setattr(client, "get_queue", lambda: {"queue_running": [[1, run.external_request_id, {}, {}]], "queue_pending": []})
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert_busy(caught.value)
    assert len(client.queued) == 1
    session.close()


@pytest.mark.asyncio
async def test_orphan_without_recorded_external_id_is_not_guessed_safe(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    run.status = GenerationRunStatus.PENDING
    run.external_request_id = None
    session.commit()
    with pytest.raises(AppError) as caught:
        await anext(continue_stream(service, batch_id, preset.id))
    assert caught.value.code == "image_generation.batch_recovery_unavailable"
    assert len(client.queued) == 1
    session.close()


@pytest.mark.asyncio
async def test_timeout_with_success_history_recovers_without_stale_error(tmp_path, monkeypatch, registry):
    session, _pages, preset, client, service, batch_id, run = await interrupted_batch(tmp_path, monkeypatch)
    run.status = GenerationRunStatus.FAILED
    run.error_code = "image_generation.comfyui_timeout"
    run.error_message = "old timeout"
    run.finished_at = utc_now()
    session.commit()
    resumed = [item async for item in continue_stream(service, batch_id, preset.id)]
    assert resumed[-1][0] == "done"
    recovered = session.get(GenerationRun, run.id)
    assert recovered.status == GenerationRunStatus.SUCCEEDED
    assert recovered.error_code is recovered.error_message is None
    assert len(client.queued) == 2
    session.close()


def test_registry_claim_is_atomic_across_threads():
    registry = RunningTaskRegistry()
    barrier = threading.Barrier(8)

    def claim(_index):
        barrier.wait()
        return registry.try_register(RuntimeTaskType.GENERATION_TASK, 42)

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(claim, range(8))) == 1
    registry.unregister(RuntimeTaskType.GENERATION_TASK, 42)
    assert registry.try_register(RuntimeTaskType.GENERATION_TASK, 42)
