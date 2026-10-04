"""连续性编辑退役不改历史数据，新准备兼容旧客户端参数。"""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import image_specs
from backend.api.schemas.image_spec import CompileImageSpecsRequest
from backend.i18n.errors import ERROR_MESSAGES


def api_client() -> TestClient:
    """只装配目标 router，避免测试启动真实数据库或后台任务。"""
    app = FastAPI()
    app.include_router(image_specs.router)
    return TestClient(app)


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("payload", [{"events": []}, {"events": "legacy-invalid"}])
def test_event_edit_returns_localized_gone_without_opening_database(monkeypatch, locale, payload):
    def forbidden_session():
        raise AssertionError("Retired editing must not access the database")

    monkeypatch.setattr(image_specs, "SessionLocal", forbidden_session)
    response = api_client().put(
        "/api/image-specs/compilations/42/events", json=payload, headers={"X-Locale": locale}
    )
    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "image_spec.continuity_retired",
        "message": ERROR_MESSAGES[locale]["image_spec.continuity_retired"],
    }


@contextmanager
def unused_session():
    yield object()


@pytest.mark.parametrize("regenerate", [False, True])
def test_compile_ignores_deprecated_continuity_option(monkeypatch, regenerate):
    received = []

    class FakeService:
        def __init__(self, repository):
            pass

        async def stream_compile_task(self, **payload):
            received.append(payload)
            yield "done", {"image_spec_compilation_id": 12}

    monkeypatch.setattr(image_specs, "SessionLocal", unused_session)
    monkeypatch.setattr(image_specs, "ImageSpecService", FakeService)
    response = api_client().post(
        "/api/image-specs/script-tasks/11/compile/stream",
        json={"regenerate_continuity": regenerate},
    )
    assert response.status_code == 200
    assert "event: done" in response.text
    assert received[0]["task_id"] == 11
    assert received[0]["generation_mode"].value == "preview"
    assert "regenerate_continuity" not in received[0]
    assert CompileImageSpecsRequest.model_json_schema()["properties"]["regenerate_continuity"]["deprecated"]


def test_legacy_events_and_snapshots_remain_readable(monkeypatch):
    now = datetime.now(timezone.utc)
    item = SimpleNamespace(
        id=42, script_task_id=11, source_hash="legacy-source", status=SimpleNamespace(value="succeeded"),
        created_at=now,
        events=[SimpleNamespace(
            id=1, page_id=3, page=SimpleNamespace(page_no=1), sequence_no=1,
            event_type=SimpleNamespace(value="set_outfit"), target_type=SimpleNamespace(value="character"),
            target_key="hero", timing=SimpleNamespace(value="before_page"),
            payload_json='{"description": "old outfit"}', source=SimpleNamespace(value="manual"),
        )],
        snapshots=[SimpleNamespace(
            id=2, page_id=3, page=SimpleNamespace(page_no=1), state_json='{"old": true}',
            state_hash="legacy-state", warnings_json="[]", created_at=now,
        )],
    )

    class FakeRepository:
        def __init__(self, session):
            pass

        def get_script_task(self, task_id):
            return object()

        def list_compilations(self, task_id):
            return [item]

    monkeypatch.setattr(image_specs, "SessionLocal", unused_session)
    monkeypatch.setattr(image_specs, "ImageSpecRepository", FakeRepository)
    response = api_client().get("/api/image-specs/script-tasks/11/continuity")
    assert response.status_code == 200
    history = response.json()[0]
    assert history["source_hash"] == "legacy-source"
    assert history["events"][0]["payload"] == {"description": "old outfit"}
    assert history["snapshots"][0]["state"] == {"old": True}
    assert history["snapshots"][0]["state_hash"] == "legacy-state"
