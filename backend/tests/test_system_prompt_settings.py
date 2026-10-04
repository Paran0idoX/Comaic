"""设置隔离、恢复默认和请求边界注入的离线回归，不调用真实模型。"""

import pytest
import httpx
import importlib
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.i18n.errors import AppError
from backend.llm_clients.factory import LLMConfigInput, create_chat_model
from backend.models.comic import ImagePromptPreset
from backend.models.database import Base
from backend.models.enums import LLMProvider, SystemPromptKey, ImagePromptPresetKind
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.services.settings_service import SettingsService
from backend.utils.prompt_loader import PromptLoader


@pytest.fixture
def settings_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    import backend.models.database as database
    import backend.llm_clients.factory as factory
    import backend.api.settings as settings_api
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(factory, "SessionLocal", sessions)
    monkeypatch.setattr(settings_api, "SessionLocal", sessions)
    with sessions() as session:
        yield session, SettingsService(ComicRepository(session))
    engine.dispose()


def create_config(service, *, provider=LLMProvider.OPENAI_COMPATIBLE, name="API", active=False):
    return service.create_llm_config(name=name, provider=provider, base_url="http://localhost/v1",
        model_names=["same/model", "other-model"], default_model="same/model", api_key="test-only", is_active=active)


def test_task_override_restores_live_markdown_and_keeps_other_settings(settings_db, monkeypatch):
    _, service = settings_db
    key = SystemPromptKey.SCRIPT_WRITER
    default = PromptLoader.load("script_writer_prompt.md")
    service.update_app_settings(script_section_max_concurrency=5)
    service.update_system_prompt(key=key, content="CUSTOM WRITER")
    assert PromptLoader.load_system("script_writer_prompt.md") == "CUSTOM WRITER"
    assert PromptLoader.load("script_writer_prompt.md") == default
    service.update_system_prompt(key=SystemPromptKey.SCRIPT_PLANNING, content="CUSTOM PLANNING")
    item = service.update_system_prompt(key=key, content=None)
    assert item["content"] == default and not item["is_overridden"]
    assert PromptLoader.load_system("script_planning_prompt.md") == "CUSTOM PLANNING"
    assert service.get_app_settings().script_section_max_concurrency == 5
    with pytest.raises(AppError) as error:
        service.update_system_prompt(key=key, content="  ")
    assert error.value.code == "settings.prompt_empty"


@pytest.mark.parametrize("module_name,class_name,key", [
    ("outline_update_agent", "OutlineUpdateAgent", SystemPromptKey.OUTLINE_UPDATE),
    ("outline_character_agent", "OutlineCharacterAgent", SystemPromptKey.OUTLINE_CHARACTER),
    ("script_planning_agent", "ScriptPlanningAgent", SystemPromptKey.SCRIPT_PLANNING),
    ("page_script_writer_agent", "PageScriptWriterAgent", SystemPromptKey.SCRIPT_WRITER),
    ("script_supervisor_agent", "ScriptSupervisorAgent", SystemPromptKey.SCRIPT_SUPERVISOR),
    ("shot_planner_agent", "ShotPlannerAgent", SystemPromptKey.SHOT_PLANNER),
])
def test_agent_constructors_consume_task_settings(settings_db, monkeypatch, module_name, class_name, key):
    _, service = settings_db
    service.update_system_prompt(key=key, content="CUSTOM TASK SYSTEM")
    module = importlib.import_module(f"backend.agents.{module_name}")
    creator = "create_agent" if module_name == "outline_update_agent" else "create_structured_agent"
    monkeypatch.setattr(module, creator, lambda **kwargs: object())
    agent = getattr(module, class_name)(llm=object())
    assert agent.prompt.startswith("CUSTOM TASK SYSTEM")
    if module_name in {"script_planning_agent", "page_script_writer_agent", "script_supervisor_agent"}:
        assert PromptLoader.load("script_visual_context_protocol.md") in agent.prompt


def test_model_prompts_are_isolated_and_new_models_freeze_current_text(settings_db):
    from backend.llm_clients.factory import get_tool_chat_model
    _, service = settings_db
    first = create_config(service, active=True)
    second = create_config(service, name="Other API")
    service.update_model_system_prompt(config_id=first.id, model="same/model", content="FIRST GLOBAL")
    service.update_model_system_prompt(config_id=first.id, model="other-model", content="OTHER GLOBAL")
    service.update_model_system_prompt(config_id=second.id, model="same/model", content="SECOND GLOBAL")
    original = get_tool_chat_model()
    service.update_model_system_prompt(config_id=first.id, model="same/model", content="UPDATED GLOBAL")
    assert original.global_system_prompt == "FIRST GLOBAL"
    assert get_tool_chat_model().global_system_prompt == "UPDATED GLOBAL"
    assert service.list_model_system_prompts(config_id=second.id)[0]["content"] == "SECOND GLOBAL"
    service.update_model_system_prompt(config_id=first.id, model="same/model", content="")
    assert get_tool_chat_model()._convert_input([HumanMessage(content="user")]).to_messages()[0].type == "human"
    restored = service.update_model_system_prompt(config_id=first.id, model="same/model", content=None)
    assert restored["content"] == "" and not restored["is_overridden"]
    assert service.list_model_system_prompts(config_id=first.id)[1]["content"] == "OTHER GLOBAL"
    with pytest.raises(AppError) as error:
        service.update_model_system_prompt(config_id=first.id, model="unknown", content="bad")
    assert error.value.code == "settings.prompt_model_invalid"


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI_COMPATIBLE, LLMProvider.DEEPSEEK, LLMProvider.ANTHROPIC])
def test_native_provider_injection_preserves_tools_schema_and_memory(provider):
    model = create_chat_model(LLMConfigInput(provider=provider, model="example", api_key="test-only",
        base_url="http://localhost/v1", global_system_prompt="GLOBAL"))
    messages = [SystemMessage(content="TASK"), HumanMessage(content="USER"),
        AIMessage(content="", tool_calls=[{"name": "tool", "args": {}, "id": "call1", "type": "tool_call"}]),
        ToolMessage(content="RESULT", tool_call_id="call1")]
    converted = model._convert_input(messages).to_messages()
    assert converted[0].content == "GLOBAL\n\nTASK"
    assert messages[0].content == "TASK"
    assert converted[2:] == messages[2:]
    assert model._convert_input(converted).to_messages() == converted
    assert model.bind_tools([{"name": "tool", "description": "Tool", "parameters": {"type": "object", "properties": {}}}])


def test_deepseek_markdown_is_default_data_and_appears_once(settings_db):
    from backend.llm_clients.factory import get_tool_chat_model
    _, service = settings_db
    config = create_config(service, provider=LLMProvider.DEEPSEEK, active=True)
    item = service.list_model_system_prompts(config_id=config.id)[0]
    source = PromptLoader.load("deepseek_infinite_gen_4_1_flash.md").strip()
    assert item["content"].count(source) == 1
    assert not item["is_overridden"]
    payload = get_tool_chat_model()._get_request_payload([SystemMessage(content="TASK")])
    assert payload["messages"][0]["content"] == item["content"] + "\n\nTASK"


def test_shot_settings_affect_real_prompt_and_hash_and_restore_legacy_default(settings_db):
    session, service = settings_db
    preset = ImagePromptPreset(name="Legacy default", kind=ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT,
        content="LEGACY SHOT", is_default=True)
    session.add(preset)
    session.commit()
    spec_service = ImageSpecService(ImageSpecRepository(session))
    previous_hash = spec_service._shot_plan_source_hash(plan={}, planner_preset=preset, planner_model="model")
    assert next(item for item in service.list_system_prompts() if item["key"] == "shot_planner")["content"] == "LEGACY SHOT"
    service.update_system_prompt(key=SystemPromptKey.SHOT_PLANNER, content="NEW SHOT")
    assert spec_service._planner_system_prompt(preset) == "NEW SHOT"
    assert spec_service._shot_plan_source_hash(plan={}, planner_preset=preset, planner_model="model") != previous_hash
    restored = service.update_system_prompt(key=SystemPromptKey.SHOT_PLANNER, content=None)
    assert not restored["is_overridden"]
    assert spec_service._planner_system_prompt(preset) == PromptLoader.load("shot_planner_prompt.md")


def test_global_and_language_settings_change_preparation_sources(settings_db):
    session, service = settings_db
    config = create_config(service, active=True)
    spec_service = ImageSpecService(ImageSpecRepository(session))
    original_global_hash = spec_service._global_system_prompt_hash()
    service.update_model_system_prompt(config_id=config.id, model="same/model", content="NEW GLOBAL")
    assert spec_service._global_system_prompt_hash() != original_global_hash
    service.update_system_prompt(key=SystemPromptKey.SHOT_LANGUAGE, content="NEW LANGUAGE RULES")
    assert spec_service._language_system_prompt() == "NEW LANGUAGE RULES"


@pytest.mark.asyncio
async def test_settings_http_routes_validate_keys_and_model_names(settings_db):
    from backend.main import app
    _, service = settings_db
    config = create_config(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert len((await client.get("/api/settings/system-prompts")).json()) == len(SystemPromptKey)
        assert (await client.put("/api/settings/system-prompts/script_writer", json={"content": "CUSTOM"})).json()["content"] == "CUSTOM"
        assert (await client.put("/api/settings/system-prompts/not_a_prompt", json={"content": "bad"})).status_code == 422
        response = await client.put("/api/settings/system-prompts/script_writer", json={"content": " "})
        assert response.status_code == 400 and response.json()["detail"]["code"] == "settings.prompt_empty"
        path = f"/api/settings/llm/configs/{config.id}/system-prompts"
        assert (await client.put(path, json={"model": "same/model", "content": "GLOBAL"})).json()["content"] == "GLOBAL"
        assert (await client.put(path, json={"model": "missing", "content": "bad"})).json()["detail"]["code"] == "settings.prompt_model_invalid"
        assert (await client.put(path, json={"model": "same/model", "content": None})).json()["content"] == ""
