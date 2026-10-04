"""用阻塞替身验证五线程上限、队列补位与两个预览入口的会话归属。"""

import asyncio
from threading import Event, Lock, current_thread

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.services.reference_prompt_runtime import ReferencePromptRuntime
from backend.tests.test_reference_image_service import catalog_fixture, _selection
from backend.tests.test_character_reference_service import reference_fixture


@pytest.mark.asyncio
async def test_five_workers_refill_on_completion_and_survive_one_failure():
    runtime = ReferencePromptRuntime()
    gates = [Event() for _ in range(8)]
    entered = [Event() for _ in range(8)]
    lock = Lock()
    active = peak = 0
    names = set()

    def prepare(index):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            names.add(current_thread().name)
        entered[index].set()
        try:
            assert gates[index].wait(5)
            if index == 2:
                raise ValueError("one object failed")
            return index
        finally:
            with lock:
                active -= 1

    tasks = [asyncio.create_task(runtime.run(lambda index=index: prepare(index))) for index in range(8)]
    try:
        for event in entered[:5]:
            assert await asyncio.to_thread(event.wait, 3)
        assert not any(event.is_set() for event in entered[5:])
        gates[2].set()
        assert await asyncio.to_thread(entered[5].wait, 3)
        # 最前面的慢请求仍阻塞时，后面完成的线程即可领取下一项。
        gates[5].set()
        assert await asyncio.to_thread(entered[6].wait, 3)
        for gate in gates:
            gate.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert isinstance(results[2], ValueError)
        assert [item for item in results if not isinstance(item, Exception)] == [0, 1, 3, 4, 5, 6, 7]
        assert peak == 5 and active == 0
        assert len(names) == 5
        assert all(name.startswith("comaic-reference-prompt") for name in names)
    finally:
        for gate in gates:
            gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        runtime.stop()


def test_both_preview_routes_create_sessions_inside_shared_prompt_pool(catalog_fixture, monkeypatch):
    """避免把主线程的 Session 传入线程池；新旧接口共用模型缓存。"""
    from backend.api import reference_images, character_reference

    fixture = catalog_fixture
    sessions = []
    factory = sessionmaker(bind=fixture["session"].bind)

    def session_factory():
        session = factory()
        sessions.append((current_thread().name, session))
        return session

    monkeypatch.setattr(reference_images, "SessionLocal", session_factory)
    monkeypatch.setattr(character_reference, "SessionLocal", session_factory)
    app = FastAPI()
    app.include_router(reference_images.router)
    app.include_router(character_reference.router)
    with TestClient(app) as client:
        payload = {key: value for key, value in _selection(fixture).items() if key != "project_id"}
        response = client.post(f"/api/reference-images/projects/{fixture['project'].id}/prompt-preview", json=payload)
        assert response.status_code == 200
        response = client.post(f"/api/character-references/outline-characters/{fixture['character'].id}/prompt-preview",
            json={"tool_preset_id": fixture["tool"].id})
        assert response.status_code == 200
    assert len(sessions) == 2 and sessions[0][1] is not sessions[1][1]
    assert all(name.startswith("comaic-reference-prompt") for name, _ in sessions)
    assert all(not session.in_transaction() for _, session in sessions)
    assert len(fixture["agent_calls"]) == 1


@pytest.mark.asyncio
async def test_whole_batch_stream_uses_five_workers_and_emits_real_started_states():
    from backend.models.enums import CompilationStatus as Status
    runtime = ReferencePromptRuntime()
    gate, first_five = Event(), Event()
    lock = Lock()
    started = []
    events = []

    def prepare(index):
        with lock:
            started.append(index)
            if len(started) == 5: first_five.set()
        assert gate.wait(5)
        if index == 1: raise ValueError("one item failed")
        return index

    async def consume():
        async for item in runtime.stream([lambda index=index: prepare(index) for index in range(8)]):
            events.append(item)

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(first_five.wait, 3)
        assert set(started) == set(range(5))
        gate.set()
        await task
        assert len([event for event in events if event[1] == Status.RUNNING]) == 8
        assert len([event for event in events if event[1] == Status.SUCCEEDED]) == 7
        assert [(index, status) for index, status, _ in events if status == Status.FAILED] == [(1, Status.FAILED)]
        for index in range(8):
            states = [status for i, status, _ in events if i == index]
            assert states[0] == Status.RUNNING and len(states) == 2
    finally:
        gate.set(); await task; runtime.stop()


def test_batch_preview_endpoint_is_one_request_with_isolated_item_errors(catalog_fixture, monkeypatch):
    from backend.api import reference_images
    from backend.i18n.errors import AppError
    from types import SimpleNamespace
    import json

    def prepare(project_id, payload):
        if payload.entity_id == 2: raise AppError("reference.owner_invalid", status_code=422)
        return SimpleNamespace(model_dump=lambda **_: {"prompts": {"identity_face": {"positive": "An adult.", "negative": ""}}})

    monkeypatch.setattr(reference_images, "prepare_preview", prepare)
    app = FastAPI(); app.include_router(reference_images.router)
    items = [{"entity_type": "character", "entity_id": index + 1, "tool_preset_id": 1, "roles": ["identity_face"]} for index in range(8)]
    with TestClient(app) as client:
        response = client.post("/api/reference-images/projects/1/prompt-preview/batch", json={"items": items})
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert frames[0] == {"project_id": 1, "total": 8, "concurrency": 5}
        assert frames[-1] == {"project_id": 1, "total": 8, "completed": 7, "failed": 1}
        failed = [event for event in frames if event.get("status") == "failed"]
        assert failed[0]["index"] == 1 and failed[0]["error"]["code"] == "reference.owner_invalid"
        assert client.post("/api/reference-images/projects/1/prompt-preview/batch", json={"items": []}).status_code == 422
        assert client.post("/api/reference-images/projects/1/prompt-preview/batch", json={"items": [items[0], items[0]]}).status_code == 422
