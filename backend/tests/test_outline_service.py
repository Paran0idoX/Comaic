"""使用临时内存数据库验证分类成功后才保存，已有版本和角色不被改写。"""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend.api.outline import outline_version_to_response, stream_outline_chat
from backend.api.schemas.outline import OutlineChatStreamRequest
from backend.i18n.errors import AppError, error_payload
from backend.i18n.errors import http_exception
from backend.models.comic import OutlineCharacter, OutlineVersion, ReferenceSubject
from backend.models.database import Base
from backend.models.enums import OutlineVersionStatus
from backend.repositories.comic_repository import ComicRepository
from backend.services.outline_service import OutlineService
from backend.tests.test_outline_character_agent import candidate, character_settings, invalid_entities, make_agent


@pytest.fixture
def context():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        repository = ComicRepository(session)
        project = repository.create_project(title="分类验证")
        service = OutlineService(repository)
        business_session = service.create_outline_session(project_id=project.id)
        yield session, factory, repository, service, business_session
    engine.dispose()


@pytest.mark.asyncio
async def test_success_preserves_history_and_only_persists_real_roles(monkeypatch, context):
    session, _, repo, service, business = context
    actor = character_settings()
    fake = character_settings("软肋（把柄载体）", "softspot", "不单独绘制形象")
    old = repo.create_outline_version(session_id=business.id, content="旧大纲", characters=[actor, fake])
    repo.confirm_outline_version(old.id)
    old_ids = [item.id for item in repo.list_outline_characters(old.id)]
    confirmed_at = old.confirmed_at
    agent, _ = make_agent(monkeypatch, [{"structured_response": {"entities": [candidate(character=actor), candidate(fake["name"], "concept")]}}])
    monkeypatch.setattr("backend.services.outline_service.OutlineCharacterAgent", lambda: agent)
    new = await service.generate_and_save_outline_snapshot(thread_id=business.thread_id, outline="新大纲", user_message="补充故事")
    assert new.status == OutlineVersionStatus.ACTIVE
    assert new.confirmed_at is None
    assert [item.character_key for item in new.characters] == ["alan"]
    assert old.status == OutlineVersionStatus.ARCHIVED
    assert old.confirmed_at == confirmed_at
    assert [item.id for item in repo.list_outline_characters(old.id)] == old_ids
    assert session.scalars(select(ReferenceSubject)).all() == []
    payload = outline_version_to_response(new).model_dump()
    assert "entities" not in payload
    assert "kind" not in payload["characters"][0]
    assert "classification_reason" not in payload["characters"][0]


@pytest.mark.asyncio
async def test_exhausted_retries_leave_active_version_characters_and_retention_unchanged(monkeypatch, context):
    session, _, repo, service, business = context
    versions = [repo.create_outline_version(session_id=business.id, content=f"大纲 {n}", characters=[character_settings()]) for n in range(5)]
    repo.confirm_outline_version(versions[-1].id)
    character_ids = [item.id for item in session.scalars(select(OutlineCharacter))]
    agent, scripted = make_agent(monkeypatch, [invalid_entities("kind_conflict")])
    monkeypatch.setattr("backend.services.outline_service.OutlineCharacterAgent", lambda: agent)
    with pytest.raises(AppError) as caught:
        await service.generate_and_save_outline_snapshot(thread_id=business.thread_id, outline="不能保存的大纲")
    assert caught.value.code == "outline.characters_invalid"
    assert caught.value.status_code == 502
    assert len(scripted.calls) == 3
    assert [item.id for item in repo.list_outline_versions(business.id)] == [item.id for item in versions]
    assert versions[-1].status == OutlineVersionStatus.ACTIVE
    assert versions[-1].confirmed_at is not None
    assert [item.id for item in session.scalars(select(OutlineCharacter))] == character_ids
    assert "本轮大纲未保存" in error_payload(caught.value, "zh")["message"]
    assert "was not saved" in error_payload(caught.value, "en")["message"]


@pytest.mark.asyncio
async def test_valid_empty_latest_version_does_not_resurrect_older_roles(monkeypatch, context):
    _, _, repo, service, business = context
    repo.create_outline_version(session_id=business.id, content="有人物", characters=[character_settings()])
    repo.create_outline_version(session_id=business.id, content="移除人物", characters=[])
    agent, scripted = make_agent(monkeypatch, [{"structured_response": {"entities": []}}])
    monkeypatch.setattr("backend.services.outline_service.OutlineCharacterAgent", lambda: agent)
    new = await service.generate_and_save_outline_snapshot(thread_id=business.thread_id, outline="继续构思")
    assert new.characters == []
    assert "alan" not in scripted.calls[0]["messages"][0].content


def test_repository_saves_version_and_roles_in_one_transaction(context):
    session, _, repo, _, business = context
    old = repo.create_outline_version(session_id=business.id, content="旧大纲", characters=[character_settings()])
    old_id = old.id
    with pytest.raises(IntegrityError):
        repo.create_outline_version(session_id=business.id, content="无效数据", characters=[character_settings(), character_settings()])
    session.rollback()
    assert [item.id for item in repo.list_outline_versions(business.id)] == [old_id]
    assert repo.get_outline_version(old_id).status == OutlineVersionStatus.ACTIVE
    assert len(repo.list_outline_characters(old_id)) == 1


@pytest.mark.asyncio
async def test_model_configuration_error_is_not_misreported_as_classification_failure(monkeypatch, context):
    _, _, repo, service, business = context

    def unconfigured_agent():
        raise ValueError("LLMConfig API key is missing.")

    monkeypatch.setattr("backend.services.outline_service.OutlineCharacterAgent", unconfigured_agent)
    with pytest.raises(ValueError) as caught:
        await service.generate_and_save_outline_snapshot(thread_id=business.thread_id, outline="未保存的大纲")
    assert http_exception(caught.value, "zh").detail["code"] == "llm.config_missing"
    assert repo.list_outline_versions(business.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [False, True])
async def test_sse_uses_validated_snapshot_flow(monkeypatch, context, success):
    _, factory, repo, _, business = context
    old = repo.create_outline_version(session_id=business.id, content="旧大纲", characters=[character_settings()])
    responses = [{"structured_response": {"entities": [candidate(character=character_settings())]}}] if success else [invalid_entities("settings_missing")]
    agent, _ = make_agent(monkeypatch, responses)
    monkeypatch.setattr("backend.services.outline_service.OutlineCharacterAgent", lambda: agent)
    monkeypatch.setattr("backend.api.outline.SessionLocal", factory)

    class Conversation:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def chat(self, **kwargs):
            yield "大纲更新"

        def consume_updated_outline(self):
            return "新大纲"

    monkeypatch.setattr("backend.api.outline.OutlineAgent", Conversation)
    request = Request({"type": "http", "headers": [(b"accept-language", b"en")]})
    response = stream_outline_chat(OutlineChatStreamRequest(thread_id=business.thread_id, message="更新故事"), request)
    events = [event async for event in response.body_iterator]
    assert events[0]["event"] == "token"
    with factory() as verify:
        versions = verify.scalars(select(OutlineVersion).order_by(OutlineVersion.id)).all()
        if success:
            assert [event["event"] for event in events] == ["token", "outline", "done"]
            assert len(versions) == 2
            assert json.loads(events[1]["data"])["characters"][0]["character_key"] == "alan"
        else:
            assert [event["event"] for event in events] == ["token", "error"]
            assert json.loads(events[-1]["data"])["code"] == "outline.characters_invalid"
            assert [item.id for item in versions] == [old.id]
            assert versions[0].status == OutlineVersionStatus.ACTIVE
