"""按页设定、局部状态与运行取消的回归测试；只使用内存数据库和假模型。"""

import asyncio

import pytest
from sqlalchemy import select

from backend.i18n.errors import AppError, error_payload
from backend.models.comic import ComicPage, OutfitVariant, ScriptCharacter, ScriptScene, ScriptSection, VisualAsset
from backend.models.enums import ApprovalStatus, GenerationMode, PageScriptReviewStatus, ScriptSectionStatus, VisualAssetRole
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.tests.test_image_spec_service import FakeShotPlannerAgent, _seed_project, _session


@pytest.fixture
def context_service(monkeypatch):
    session = _session()
    task, pages, _style = _seed_project(session)
    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", FakeShotPlannerAgent)
    service = ImageSpecService(ImageSpecRepository(session))
    yield service, task, pages
    session.close()


def _context(service, task):
    return service._prepare_context(
        task_id=task.id, style_profile_id=None,
        shot_planner_preset_id=None, negative_prompt_preset_id=None,
    )


def _stream(service, task, **kwargs):
    return service.stream_compile_task(
        task_id=task.id, style_profile_id=None,
        shot_planner_preset_id=None, negative_prompt_preset_id=None,
        generation_mode=GenerationMode.PREVIEW, **kwargs,
    )


def test_each_page_reads_its_bound_section_and_does_not_inherit_state(context_service):
    service, task, pages = context_service
    session = service.repository.session
    original = pages[0].visual_characters[0]
    second_section = ScriptSection(
        task=task, section_no=2, page_start=2, page_end=2,
        title="Home", description="Changed clothes", status=ScriptSectionStatus.COMPLETED,
    )
    session.add(second_section)
    alternate = OutfitVariant(
        project_id=task.project_id, outline_character_id=original.outline_character_id,
        key="home", version=1, name="Home clothes", status=ApprovalStatus.APPROVED,
        garment_components_json='["green sweater"]', accessories_json='["wristwatch"]',
    )
    second_character = ScriptCharacter(
        section=second_section, outline_character=original.outline_character,
        outfit_variant=alternate, character_key=original.character_key, name=original.name,
        current_hairstyle="long braid", current_state="injured later in the section",
        temporary_changes="sleeves become wet after the storm",
    )
    session.add(second_character)
    pages[1].section = second_section
    pages[1].visual_characters = [second_character]
    third = ComicPage(
        project_id=task.project_id, section=pages[0].section,
        script_scene=pages[0].script_scene, page_no=3,
        summary="Back in repair clothes", characters="Alice", clothing="repair coat",
        scene="workshop", composition="medium shot", character_action="standing", dialogue="无",
        script_review_status=pages[0].script_review_status,
        visual_characters=[original],
    )
    session.add_all([second_section, alternate, second_character, third])
    session.commit()
    states = service._build_page_contexts(_context(service, task))
    characters = [state["characters"][0] for state in states]
    assert [character["outfit"]["key"] for character in characters] == ["repair_coat", "home", "repair_coat"]
    assert [character["hairstyle"] for character in characters] == ["short black bob", "long braid", "short black bob"]
    assert all(character["identity"] == characters[0]["identity"] for character in characters)
    assert all(character["conditions"] == {} and character["held_props"] == [] for character in characters)
    assert characters[1]["section_context"]["temporary_changes"] == second_character.temporary_changes
    assert "wristwatch" in characters[1]["accessories"]["description"]
    assert "wristwatch" not in characters[2]["accessories"]["description"]


def test_unapproved_outfit_uses_section_then_outline_defaults(context_service):
    service, task, pages = context_service
    character = pages[0].visual_characters[0]
    character.outfit_variant.status = ApprovalStatus.DRAFT
    character.current_clothing = "green sweater"
    character.current_accessories = "wristwatch"
    service.repository.session.commit()
    current = service._build_page_contexts(_context(service, task))[0]["characters"][0]
    assert current["outfit"]["variant_id"] is None
    assert current["outfit"]["description"] == "green sweater"
    assert current["accessories"]["description"] == "wristwatch"
    character.current_clothing = ""
    service.repository.session.commit()
    current = service._build_page_contexts(_context(service, task))[0]["characters"][0]
    assert current["outfit"]["description"] == character.outline_character.default_clothing


@pytest.mark.parametrize("target,field,value", [
    ("outline", "appearance", "green eyes and freckles"),
    ("outline", "negative_constraints", "keep freckles"),
    ("character", "negative_constraints", "one wristwatch only"),
    ("character", "current_hairstyle", "long braid"),
    ("page", "clothing", "the sleeves are wet"),
    ("page", "character_action", "holding a closed box"),
    ("scene", "lighting", "cool daylight"),
])
def test_changed_page_inputs_invalidate_context_hash(context_service, target, field, value):
    service, task, pages = context_service
    character = pages[0].visual_characters[0]
    owners = {"outline": character.outline_character, "character": character,
              "page": pages[0], "scene": pages[0].script_scene}
    previous = service.current_page_context_source_hash(task.id)
    setattr(owners[target], field, value)
    service.repository.session.commit()
    assert service.current_page_context_source_hash(task.id) != previous


def test_context_hash_does_not_depend_on_llm_or_old_reducer_configuration(context_service):
    service, task, _pages = context_service
    context = _context(service, task)
    original = service._page_context_source_payload(context)
    context.update(llm_config_id=999, llm_model="other-model")
    assert service._page_context_source_payload(context) == original
    assert original["context_builder_version"] == service.PAGE_CONTEXT_VERSION
    assert "agent" not in original and "reducer_version" not in original


@pytest.mark.parametrize("field,default_field,slot", [
    ("current_hairstyle", "default_hairstyle", "hairstyle"),
    ("current_clothing", "default_clothing", "outfit"),
    ("current_accessories", "default_accessories", "accessories"),
])
def test_section_features_preserve_changes_after_same_prefix(context_service, field, default_field, slot):
    service, task, pages = context_service
    character = pages[0].visual_characters[0]
    character.outfit_variant = None
    setattr(character.outline_character, default_field, "same base, original detail")
    setattr(character, field, "same base, first section detail")
    service.repository.session.commit()
    before = service.current_page_context_source_hash(task.id)
    state = service._build_page_contexts(_context(service, task))[0]["characters"][0]
    actual = state[slot] if slot == "hairstyle" else state[slot]["description"]
    assert actual == "same base, first section detail"
    setattr(character, field, "same base, second section detail")
    service.repository.session.commit()
    assert service.current_page_context_source_hash(task.id) != before


@pytest.mark.parametrize("owner_kind", ["outfit", "scene"])
def test_selected_version_revision_invalidates_context(context_service, owner_kind):
    service, task, pages = context_service
    owner = (pages[0].visual_characters[0].outfit_variant if owner_kind == "outfit"
             else pages[0].script_scene.selected_visual_version)
    previous = service.current_page_context_source_hash(task.id)
    owner.version += 1
    service.repository.session.commit()
    assert service.current_page_context_source_hash(task.id) != previous


@pytest.mark.asyncio
async def test_local_visible_state_reaches_three_prompts_without_reference_images(context_service, monkeypatch):
    service, task, pages = context_service
    pages[0].clothing = "Alice's sleeves are soaked"
    pages[1].clothing = "Alice's sleeves are dry"
    for asset in service.repository.session.scalars(select(VisualAsset)):
        asset.status = ApprovalStatus.DRAFT
    service.repository.session.commit()

    class LocalPlanner(FakeShotPlannerAgent):
        async def plan(self, *, page, **kwargs):
            plan = await super().plan(**kwargs)
            plan["subjects"][0]["visible_state"] = "soaked sleeves" if "soaked" in page["clothing"] else "dry sleeves"
            plan["subjects"][0]["visible_prop_keys"] = []
            plan["scene"].update(visible_prop_keys=[], framing_notes="workshop with an open north door")
            return plan

    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", LocalPlanner)
    events = [event async for event in _stream(service, task)]
    assert events[-1][0] == "done"
    specs = service.list_task_specs(task_id=task.id)
    assert len(specs) == 6
    for spec in specs:
        assert spec["spec"]["reference_plan"]["items"] == []
        assert "amber eyes and a small left-eyebrow scar" in spec["positive_prompt"]
        assert "open north door" in spec["positive_prompt"]
        if spec["page_no"] == 1:
            assert "soaked sleeves" in spec["positive_prompt"]
        else:
            assert "dry sleeves" in spec["positive_prompt"]
            assert "soaked sleeves" not in spec["positive_prompt"]


@pytest.mark.asyncio
async def test_deprecated_regenerate_flag_reuses_context_without_events(context_service):
    service, task, _pages = context_service
    first = [event async for event in _stream(service, task)]
    second = [event async for event in _stream(service, task, regenerate_continuity=True)]
    assert first[-1][0] == second[-1][0] == "done"
    records = service.repository.list_compilations(task.id)
    assert len(records) == 1 and records[0].events == []
    assert records[0].source_hash == service.current_page_context_source_hash(task.id)
    assert any(name == "resume" for name, _ in second)


@pytest.mark.asyncio
@pytest.mark.parametrize("close_generator", [False, True])
async def test_page_planning_cancel_cleans_up_pending_work(context_service, monkeypatch, close_generator):
    service, task, _pages = context_service
    started, finished = asyncio.Event(), asyncio.Event()

    class WaitingPlanner(FakeShotPlannerAgent):
        async def plan(self, *, page, **kwargs):
            if page["page_no"] == 2:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.set()
            return await super().plan(**kwargs)

    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", WaitingPlanner)
    stream = _stream(service, task)
    if close_generator:
        async for name, _ in stream:
            if name == "shot_plan":
                break
        await asyncio.wait_for(started.wait(), 1)
        await stream.aclose()
    else:
        async def consume():
            async for _ in stream:
                pass
        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 1)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    assert finished.is_set()
    attempt = service.list_image_spec_compilations(task.id)[0]
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == "image_spec.compilation_interrupted"
    assert service.repository.list_compilations(task.id)[0].status.value == "succeeded"


def test_historical_continuity_error_remains_readable():
    error = AppError("image_spec.continuity_timeout", status_code=504, params={"seconds": 1800})
    chinese, english = error_payload(error, "zh"), error_payload(error, "en")
    assert chinese["code"] == english["code"] == "image_spec.continuity_timeout"
    assert "1800" in chinese["message"] and "1800" in english["message"]


@pytest.mark.asyncio
async def test_page_edit_recompiles_only_changed_page_and_keeps_other_spec_ids(context_service, monkeypatch):
    service, task, pages = context_service
    planned = []

    class CountingPlanner(FakeShotPlannerAgent):
        async def plan(self, *, page, **kwargs):
            planned.append(page["page_id"])
            return await super().plan(**kwargs)

    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", CountingPlanner)
    _ = [event async for event in _stream(service, task)]
    original_specs = {(row["page_id"], row["prompt_type"]): row["id"] for row in service.list_task_specs(task_id=task.id)}
    original_hashes = service.current_page_context_hashes(task.id)
    planned.clear()
    pages[0].clothing = "wet sleeves on this page"
    service.repository.session.commit()
    hashes = service.current_page_context_hashes(task.id)
    assert hashes[pages[0].id] != original_hashes[pages[0].id]
    assert hashes[pages[1].id] == original_hashes[pages[1].id]
    events = [event async for event in _stream(service, task)]
    assert planned == [pages[0].id]
    assert next(data for name, data in events if name == "resume")["page_nos"] == [2]
    for spec in service.list_task_specs(task_id=task.id):
        assert (spec["id"] == original_specs[(spec["page_id"], spec["prompt_type"])]) == (spec["page_id"] == pages[1].id)


@pytest.mark.parametrize("change", ["appearance", "outfit", "asset", "scene"])
def test_live_hash_changes_only_for_pages_bound_to_changed_settings(context_service, change):
    service, task, pages = context_service
    session = service.repository.session
    # 第二页独立场景且没有此角色，不能被第一页面的设定/参考图修改连带失效。
    pages[1].visual_characters = []
    pages[1].script_scene = ScriptScene(task=task, scene_key="outside", name="Outside")
    session.commit()
    previous = service.current_page_context_hashes(task.id)
    character = pages[0].visual_characters[0]
    if change == "appearance":
        character.outline_character.appearance = "green eyes"
    elif change == "outfit":
        character.outfit_variant.garment_components_json = '["green coat"]'
    elif change == "asset":
        asset = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.IDENTITY_FACE))
        asset.version += 1
    else:
        pages[0].script_scene.lighting = "bright daylight"
    session.commit()
    current = service.current_page_context_hashes(task.id)
    assert current[pages[0].id] != previous[pages[0].id]
    assert current[pages[1].id] == previous[pages[1].id]


@pytest.mark.asyncio
async def test_compile_subset_then_whole_task_reuses_same_page_input(context_service, monkeypatch):
    service, task, pages = context_service
    events = [event async for event in _stream(service, task, page_ids=[pages[0].id, pages[0].id])]
    assert events[0][1]["total_pages"] == 1
    first_specs = {row["id"] for row in service.list_task_specs(task_id=task.id)}
    events = [event async for event in _stream(service, task)]
    assert next(data for name, data in events if name == "resume")["page_nos"] == [1]
    assert first_specs <= {row["id"] for row in service.list_task_specs(task_id=task.id)}

    class UnavailablePlanner(FakeShotPlannerAgent):
        def __init__(self, **kwargs):
            raise AssertionError("Unchanged inputs must not initialize an LLM")

    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", UnavailablePlanner)
    events = [event async for event in _stream(service, task, page_ids=[pages[1].id])]
    assert events[-1][0] == "done"
    assert next(data for name, data in events if name == "resume")["page_nos"] == [2]


def test_page_hash_query_accepts_unreviewed_pages_but_compilation_still_requires_review(context_service):
    service, task, pages = context_service
    for ids in ([], [99999], [pages[0].id, 99999]):
        with pytest.raises(AppError) as error:
            service.current_page_context_hashes(task.id, ids)
        assert error.value.code == "image_generation.page_scope_invalid"
    pages[1].script_review_status = PageScriptReviewStatus.UNREVIEWED
    service.repository.session.commit()
    assert set(service.current_page_context_hashes(task.id, [pages[0].id])) == {pages[0].id}
    assert set(service.current_page_context_hashes(task.id)) == {page.id for page in pages}
    with pytest.raises(AppError) as error:
        _context(service, task)
    assert error.value.code == "script.pages_not_reviewed"
