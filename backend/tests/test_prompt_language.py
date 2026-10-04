"""最终漫画提示词的语言切换、复用和冻结输入，不调用真实模型或 Provider。"""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.schemas.image_spec import CompileImageSpecsRequest
from backend.models.comic import ImageSpec, GenerationTask
from backend.models.enums import GenerationMode, PromptLanguage
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.services.reference_inputs import prepare_renderer_spec
from backend.tests.test_image_spec_service import FakeShotPlannerAgent, _seed_project, _session
from backend.tests.test_reference_batch_snapshot import BatchShotPlanner, _setup_batch
from backend.i18n.errors import AppError


TRANSLATIONS = {
    PromptLanguage.CHINESE: {
        "tag_text": "琥珀色眼睛，左眉小伤疤，蓝色工作服，检查发电机，湿衣，背面，门已打开",
        "natural_language_text": "角色的琥珀色眼睛和左眉小伤疤保持固定，穿蓝色工作服检查发电机，湿衣清晰可见。背面镜头不露出脸，门已打开。",
        "negative_tag_text": "多余人物，额外窗户，文字，水印",
        "negative_natural_language_text": "避免多余人物、额外窗户、文字和水印。",
    },
    PromptLanguage.ENGLISH: {
        "tag_text": "amber eyes, small left-eyebrow scar, blue work shirt, checks generator, wet clothing, rear view, open door",
        "natural_language_text": "Keep amber eyes and a small left-eyebrow scar. Wear a blue work shirt and check the generator with visible wet clothing. The rear view hides the face. The door is open.",
        "negative_tag_text": "extra people, extra windows, text, watermark",
        "negative_natural_language_text": "Avoid extra people, extra windows, text and watermarks.",
    },
}


class LanguagePlanner(FakeShotPlannerAgent):
    plans = []
    translations = []
    fail_translation = False

    async def plan(self, **kwargs):
        self.plans.append(kwargs["page"]["page_id"])
        plan = await super().plan(**kwargs)
        for subject in plan["subjects"]:
            subject["visible_state"] = "wet clothing"
        plan["scene"]["framing_notes"] += "; the door is open"
        return plan

    async def translate_prompt_components(self, components, language):
        self.translations.append((deepcopy(components), language))
        if self.fail_translation:
            raise ValueError("mock conversion failed")
        return deepcopy(TRANSLATIONS[language])


@pytest.fixture
def language_planner(monkeypatch):
    LanguagePlanner.plans, LanguagePlanner.translations = [], []
    LanguagePlanner.fail_translation = False
    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", LanguagePlanner)
    return LanguagePlanner


async def compile_task(service, task, language):
    return [item async for item in service.stream_compile_task(
        task_id=task.id, style_profile_id=None, shot_planner_preset_id=None,
        negative_prompt_preset_id=None, generation_mode=GenerationMode.PREVIEW,
        prompt_language=language,
    )]


@pytest.mark.asyncio
async def test_language_change_reuses_shots_and_translates_four_components_once_per_page(language_planner):
    with _session() as session:
        task, pages, _ = _seed_project(session)
        service = ImageSpecService(ImageSpecRepository(session))
        await compile_task(service, task, PromptLanguage.ORIGINAL)
        assert len(language_planner.plans) == 2
        assert not language_planner.translations
        baseline = {spec.page_id: spec.shot_plan_id for spec in service.repository.list_latest_specs(task_id=task.id)}
        for language in (PromptLanguage.CHINESE, PromptLanguage.ENGLISH):
            events = await compile_task(service, task, language)
            assert len([1 for event, _ in events if event == "image_spec"]) == 6
            for spec in service.repository.list_latest_specs(task_id=task.id):
                data = json.loads(spec.spec_json)
                assert data["prompt_language"] == language.value
                assert spec.shot_plan_id == baseline[spec.page_id]
                assert spec.source_hash == service.current_image_spec_source_hash(spec)
                for key, value in TRANSLATIONS[language].items():
                    assert data["prompt"][key] == value
                if spec.prompt_type.value == "hybrid":
                    assert spec.positive_prompt == TRANSLATIONS[language]["natural_language_text"] + "\n" + TRANSLATIONS[language]["tag_text"]
                    assert spec.negative_prompt == TRANSLATIONS[language]["negative_natural_language_text"] + "\n" + TRANSLATIONS[language]["negative_tag_text"]
                assert data["subjects"][0]["identity"]["appearance"] == "amber eyes and a small left-eyebrow scar"
        assert len(language_planner.plans) == 2
        assert len(language_planner.translations) == 4
        assert all("wet clothing" in source["natural_language_text"] and "door is open" in source["natural_language_text"] for source, _ in language_planner.translations)
        events = await compile_task(service, task, PromptLanguage.ENGLISH)
        assert any(event == "resume" for event, _ in events)
        assert len(language_planner.translations) == 4


@pytest.mark.asyncio
async def test_translation_failure_saves_no_partial_prompts(language_planner):
    with _session() as session:
        task, _, _ = _seed_project(session)
        language_planner.fail_translation = True
        with pytest.raises(AppError) as exc:
            await compile_task(ImageSpecService(ImageSpecRepository(session)), task, PromptLanguage.CHINESE)
        assert exc.value.code == "image_spec.prompt_language_failed"
        assert not session.scalars(select(ImageSpec)).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("single_page", [False, True])
@pytest.mark.parametrize("language", [PromptLanguage.CHINESE, PromptLanguage.ENGLISH])
async def test_generation_consumes_prepared_language_without_converting_again(tmp_path, monkeypatch, single_page, language):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    monkeypatch.setattr(BatchShotPlanner, "translate_prompt_components", LanguagePlanner.translate_prompt_components, raising=False)
    BatchShotPlanner.translations, BatchShotPlanner.fail_translation = [], False
    spec_service = ImageSpecService(ImageSpecRepository(session))
    _prepared = [item async for item in spec_service.stream_compile_task(
        task_id=task.id, page_ids=[pages[1].id], style_profile_id=None,
        shot_planner_preset_id=None, negative_prompt_preset_id=None,
        generation_mode=GenerationMode.FINAL, prompt_language=language,
    )]
    BatchShotPlanner.fail_translation = True
    common = dict(tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL)
    stream = service.stream_generate_for_page(page_id=pages[1].id, **common) if single_page else service.stream_generate_for_script_task(task_id=task.id, page_ids=[pages[1].id], **common)
    events = [item async for item in stream]
    assert not any(event.startswith("preparation_") for event, _ in events)
    assert len(BatchShotPlanner.translations) == 1
    assert len(client.queued) == 1
    batch = session.scalar(select(GenerationTask).where(GenerationTask.parent_task_id.is_(None)))
    frozen = json.loads(batch.input_snapshot_json)
    assert frozen["page_order"] == [pages[1].id]
    spec = frozen["pages"][str(pages[1].id)]["spec"]
    assert spec["prompt_language"] == language.value
    assert TRANSLATIONS[language]["natural_language_text"] in spec["prompt"]["positive"]
    if language == PromptLanguage.CHINESE:
        assert "reference sources" not in spec["prompt"]["positive"]
    assert spec["prompt"]["negative"] == TRANSLATIONS[language]["negative_natural_language_text"]
    # 冻结输入重复准备不会追加说明或重新翻译。
    assert prepare_renderer_spec(spec, preset, GenerationMode.FINAL) == spec
    session.close()


def test_language_request_validation_and_legacy_default():
    assert CompileImageSpecsRequest().prompt_language == PromptLanguage.ORIGINAL
    assert CompileImageSpecsRequest(prompt_language="en").prompt_language == PromptLanguage.ENGLISH
    with pytest.raises(ValidationError):
        CompileImageSpecsRequest(prompt_language="unsupported")


@pytest.mark.asyncio
async def test_conversion_uses_selected_language_and_retries_only_structured_response(monkeypatch):
    from backend.agents.shot_planner_agent import ShotPlannerAgent
    from backend.agents.visual_agent_models import PromptLanguageResponse

    calls = []

    class FakeAgent:
        async def ainvoke(self, payload, **_kwargs):
            calls.append(payload)
            if len(calls) == 1:
                return {"messages": ["A natural-language answer must not be parsed."]}
            return {"structured_response": PromptLanguageResponse(**TRANSLATIONS[PromptLanguage.ENGLISH])}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_kwargs: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), max_structured_retries=2)
    output = await planner.translate_prompt_components(TRANSLATIONS[PromptLanguage.CHINESE], PromptLanguage.ENGLISH)
    assert output == TRANSLATIONS[PromptLanguage.ENGLISH]
    assert len(calls) == 2
    content = json.loads(calls[0]["messages"][0].content)
    assert content["output_language"] == "en"
    assert content["components"]["negative_tag_text"] == TRANSLATIONS[PromptLanguage.CHINESE]["negative_tag_text"]
