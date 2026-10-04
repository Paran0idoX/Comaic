"""固定地点、逐页条件与人工关联的离线回归，沿用真实 ORM 和模型替身。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from backend.api.schemas.script import UpdatePageScriptRequest
from backend.api.scripts import page_to_response
from backend.i18n.errors import AppError
from backend.models.comic import ComicImage, ComicProject, ScriptCharacter, ScriptGenerationTask, ScriptScene, ScriptSection
from backend.models.enums import PageScriptReviewStatus, ScriptGenerationMode, ScriptSectionStatus, VisualEntityType
from backend.models.scene_conditions import page_scene_conditions
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.reference_subject_repository import ReferenceSubjectRepository
from backend.services.reference_subject_service import ReferenceSubjectService
from backend.services.script_service import ScriptService
from backend.tests.test_page_visual_context import context_service, _context, _stream


DAY = {"time_of_day": "day", "weather": "clear", "lighting": "diffuse daylight", "atmosphere": "quiet"}
NIGHT = {"time_of_day": "night", "weather": "rain", "lighting": "warm desk lamp", "atmosphere": "tense"}


def text_payload(page):
    return {name: getattr(page, name) for name in ("summary", "characters", "clothing", "scene", "composition", "character_action", "dialogue")}


def neutralize(service, task, pages):
    """把夹具标记成新任务；旧列故意保留条件以检测新路径是否错误消费。"""
    task.scene_definition_version = 2
    subjects = ReferenceSubjectService(ReferenceSubjectRepository(service.repository.session))
    subjects.sync_script_scenes(task.project_id)
    page_scene = pages[0].script_scene
    assets = service.repository.list_project_assets(task.project_id, approved_only=True)
    for asset in assets:
        if asset.entity_type == VisualEntityType.SCENE:
            asset.entity_id = None
            asset.reference_subject_id = page_scene.reference_subject_id
    for page, conditions in zip(pages, (DAY, NIGHT)):
        page.scene_conditions_json = json.dumps(conditions)
    service.repository.session.commit()
    return page_scene.reference_subject


@pytest.mark.asyncio
async def test_same_fixed_location_shares_reference_but_has_different_conditions(context_service):
    service, task, pages = context_service
    subject = neutralize(service, task, pages)
    assert subject.scene_definition_version == 2
    assert "warm desk lamp" not in subject.description
    assert "rain" not in subject.description
    contexts = service._build_page_contexts(_context(service, task))
    assert contexts[0]["scene_conditions"] == DAY
    assert contexts[1]["scene_conditions"] == NIGHT
    assert contexts[0]["scene"]["reference_subject_id"] == contexts[1]["scene"]["reference_subject_id"]
    assert contexts[0]["scene"]["light_states"] == {}
    assert contexts[0]["scene"]["object_states"] == {}
    assert contexts[0]["scene"]["time"] == contexts[0]["scene"]["weather"] == contexts[0]["scene"]["lighting"] == ""
    events = [event async for event in _stream(service, task)]
    assert events[-1][0] == "done"
    refs = []
    for page, conditions in zip(pages, (DAY, NIGHT)):
        specs = [spec for spec in service.repository.list_latest_specs(task_id=task.id) if spec.page_id == page.id]
        assert len(specs) == 3
        for spec in specs:
            assert all(value in spec.positive_prompt for value in conditions.values())
            refs.append([item["asset_id"] for item in json.loads(spec.spec_json)["reference_plan"]["items"]
                         if item["owner"]["category"] == "scene"])
    assert all(value == refs[0] and value for value in refs)


@pytest.mark.asyncio
async def test_numeric_time_and_color_temperature_survive_all_prompt_forms(context_service):
    service, task, pages = context_service
    neutralize(service, task, pages)
    conditions = {**DAY, "time_of_day": "18:30", "lighting": "2700 K desk light"}
    pages[0].scene_conditions_json = json.dumps(conditions)
    service.repository.session.commit()
    events = [event async for event in _stream(service, task)]
    assert events[-1][0] == "done"
    specs = [spec for spec in service.repository.list_latest_specs(task_id=task.id) if spec.page_id == pages[0].id]
    assert len(specs) == 3
    for spec in specs:
        assert "18:30" in spec.positive_prompt and "2700 K desk light" in spec.positive_prompt


def test_manual_edit_updates_one_page_and_preserves_omitted_bindings(context_service):
    service, task, pages = context_service
    neutralize(service, task, pages)
    before = service.current_page_context_hashes(task.id)
    repository = ComicRepository(service.repository.session)
    writer = ScriptService(repository)
    original_character_ids = [item.id for item in pages[0].visual_characters]
    candidates = [ComicImage(page=page, is_selected=True, local_path=f"candidate-{page.id}.png") for page in pages]
    service.repository.session.add_all(candidates); service.repository.session.flush()
    for page, candidate in zip(pages, candidates):
        page.selected_image_id = candidate.id
    service.repository.session.commit()
    saved = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                           scene_conditions=NIGHT, **text_payload(pages[0]))
    assert saved.script_review_status == PageScriptReviewStatus.UNREVIEWED
    assert saved.selected_image_id is None and not candidates[0].is_selected
    assert pages[1].selected_image_id == candidates[1].id and candidates[1].is_selected
    assert len(saved.images) == 1
    assert [item.id for item in saved.visual_characters] == original_character_ids
    assert page_scene_conditions(pages[1]) == NIGHT
    # 查询有效性不应因为一页待复审而拒绝整个工作台；实际编译仍检查审查状态。
    after = service.current_page_context_hashes(task.id)
    assert before[pages[0].id] != after[pages[0].id]
    assert before[pages[1].id] == after[pages[1].id]
    response = page_to_response(saved)
    assert response.character_bindings[0].name == "Alice"
    assert response.reference_subject_name == saved.script_scene.reference_subject.name
    assert ScriptService._page_to_payload(saved)["scene_conditions"] == NIGHT


def test_legacy_fallback_and_explicit_empty_conditions(context_service):
    service, task, pages = context_service
    assert page_scene_conditions(pages[0]) == {**NIGHT, "atmosphere": ""}
    writer = ScriptService(ComicRepository(service.repository.session))
    page = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                           scene_conditions={}, **text_payload(pages[0]))
    assert set(page_scene_conditions(page).values()) == {""}
    context = service._build_page_contexts(_context_after_review(service, task, page))[0]
    assert context["scene"]["lighting"] == ""
    assert context["scene"]["light_states"] == {}
    assert page_scene_conditions(pages[1])["lighting"] == "warm desk lamp"


def _context_after_review(service, task, page):
    page.script_review_status = PageScriptReviewStatus.PASSED
    service.repository.session.commit()
    return _context(service, task)


def test_manual_binding_validation_and_create_require_scene(context_service):
    service, task, pages = context_service
    session = service.repository.session
    writer = ScriptService(ComicRepository(session))
    other_section = ScriptSection(task=task, section_no=2, page_start=3, page_end=3, status=ScriptSectionStatus.COMPLETED)
    other_character = ScriptCharacter(section=other_section, character_key="other", name="Other")
    session.add_all([other_section, other_character]); session.commit()
    original = [item.id for item in pages[0].visual_characters]
    for change, code in (({"scene_id": 999999}, "script.scene_binding_invalid"),
                         ({"character_ids": [other_character.id]}, "script.character_binding_invalid"),
                         ({"character_ids": original * 2}, "script.character_binding_invalid")):
        with pytest.raises(AppError) as error:
            writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                             **change, **text_payload(pages[0]))
        assert error.value.code == code
        assert [item.id for item in pages[0].visual_characters] == original
    with pytest.raises(AppError, match="script.scene_required"):
        writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=3, **text_payload(pages[0]))
    saved = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                           character_ids=[], **{**text_payload(pages[0]), "characters": "无人物"})
    assert saved.visual_characters == []


def test_manual_rebind_uses_other_locked_scene_in_same_batch(context_service):
    service, task, pages = context_service
    room = ScriptScene(task=task, scene_key="library", name="Library", environment_details="fixed bookshelves")
    service.repository.session.add(room); service.repository.session.commit()
    writer = ScriptService(ComicRepository(service.repository.session))
    saved = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                           scene_id=room.id, **text_payload(pages[0]))
    assert saved.scene_id == room.id
    assert page_scene_conditions(saved)["lighting"] == "warm desk lamp"
    assert pages[1].scene_id != room.id


def test_api_forbids_explicit_null_but_accepts_empty_cast():
    payload = {name: "text" for name in ("summary", "characters", "clothing", "scene", "composition", "character_action", "dialogue")}
    for name in ("scene_id", "character_ids", "scene_conditions"):
        with pytest.raises(ValidationError):
            UpdatePageScriptRequest(**payload, **{name: None})
    assert UpdatePageScriptRequest(**payload, character_ids=[]).character_ids == []


def test_manual_create_empty_cast_and_reject_foreign_scenes(context_service):
    service, task, pages = context_service
    session = service.repository.session
    writer = ScriptService(ComicRepository(session))
    other_project = ComicProject(title="other")
    session.add(other_project); session.flush()
    other_tasks = [ScriptGenerationTask(project_id=project_id, mode=ScriptGenerationMode.BATCH, total_pages=2)
                   for project_id in (task.project_id, other_project.id)]
    foreign_scenes = [ScriptScene(task=item, scene_key="foreign", name="Foreign") for item in other_tasks]
    session.add_all(foreign_scenes); session.commit()
    for scene in foreign_scenes:
        with pytest.raises(AppError) as rejected:
            writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                             scene_id=scene.id, **text_payload(pages[0]))
        assert rejected.value.code == "script.scene_binding_invalid"
    task.total_pages = 3
    session.add(ScriptSection(task=task, section_no=2, page_start=3, page_end=3, title="Empty", description="Empty"))
    session.commit()
    saved = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=3,
                                             scene_id=pages[0].scene_id, character_ids=[], scene_conditions=DAY,
                                             **{**text_payload(pages[0]), "characters": "无人物"})
    response = page_to_response(saved)
    assert response.scene_id == pages[0].scene_id and response.scene_name == pages[0].script_scene.name
    assert response.character_bindings == [] and response.scene_conditions.model_dump() == DAY
    assert response.script_review_status == "unreviewed"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_page_plan", [False, True])
async def test_reviewer_reads_actual_rebinding_and_sse_names(context_service, monkeypatch, with_page_plan):
    service, task, pages = context_service
    neutralize(service, task, pages)
    writer = ScriptService(ComicRepository(service.repository.session))
    original = pages[0].script_scene
    page_plan = [{"page_no": 1, "scene_key": original.scene_key, "beat": "repair"}] if with_page_plan else []
    task.section_plan = json.dumps([{"section_no": 1, "scenes": [{"scene_key": original.scene_key}],
                                    **({"page_plan": page_plan} if with_page_plan else {})}])
    room = ScriptScene(task=task, scene_key="library", name="Library", environment_details="fixed shelves")
    service.repository.session.add(room); service.repository.session.commit()
    saved = writer.upsert_manual_page_script(project_id=task.project_id, task_id=task.id, page_no=1,
                                             scene_id=room.id, scene_conditions=NIGHT, **text_payload(pages[0]))
    locked = writer._section_visual_context(task_id=task.id, section=saved.section, outline_version_id=task.outline_version_id)
    assert room.scene_key not in {scene["scene_key"] for scene in locked["scenes"]}

    class Reviewer:
        async def review_section_pages(self, **kwargs):
            assert room.scene_key in {scene["scene_key"] for scene in kwargs["section_scenes"]}
            assert kwargs["pages"][0]["scene_key"] == room.scene_key
            assert kwargs["pages"][0]["scene_conditions"] == NIGHT
            assert kwargs["current_section"]["page_plan"] == page_plan
            return {"passed": True, "reviews": [{"page_no": 1, "passed": True, "summary": "ok"}]}

    monkeypatch.setattr("backend.services.script_service.ScriptSupervisorAgent", lambda: Reviewer())
    events = [event async for event in writer.stream_review_script_pages(task_id=task.id, page_nos=[1])]
    updated = [payload["page"] for name, payload in events if name == "page"][-1]
    assert updated["scene_name"] == "Library" and updated["scene_conditions"] == NIGHT
    assert updated["character_bindings"][0]["name"] == "Alice"
    assert saved.script_review_status == PageScriptReviewStatus.PASSED


def test_planning_reuses_explicit_catalog_key_and_rejects_changed_identity(context_service):
    service, task, pages = context_service
    subject = neutralize(service, task, pages)
    writer = ScriptService(ComicRepository(service.repository.session))
    scene = {"scene_key": "fixed_room", "name": "Room", "environment_details": "fixed shelves",
             "reference_subject_key": subject.key}
    sections = [{"section_no": index, "page_start": index, "page_end": index, "scenes": [dict(scene)],
                 "characters": [{"character_key": "alice", "name": "Alice", "section_role": "mechanic"}]}
                for index in (1, 2)]
    writer._validate_neutral_scene_plan(sections, project_id=task.project_id)
    writer._persist_section_plan(task_id=task.id, outline_version_id=task.outline_version_id, normalized_sections=[
        {**section, "title": "Room", "description": "Room"} for section in sections])
    locked = writer.repository.get_script_scene_by_key(task_id=task.id, scene_key="fixed_room")
    assert locked.reference_subject_id == subject.id and locked.environment_details == subject.description
    assert locked.time_of_day == locked.weather == locked.lighting == ""
    assert len([scene for scene in writer.repository.list_script_scenes(task.id) if scene.scene_key == "fixed_room"]) == 1
    for change in ({"reference_subject_key": "unknown"}, {"scene_key": "different_key"}):
        invalid = [{**sections[0]}, {**sections[1], "scenes": [{**scene, **change}]}]
        with pytest.raises(ValueError):
            writer._validate_neutral_scene_plan(invalid, project_id=task.project_id)
    new_place = {**scene, "reference_subject_key": None}
    with pytest.raises(ValueError, match="definition changed"):
        writer._validate_neutral_scene_plan([{**sections[0], "scenes": [new_place]},
                                             {**sections[1], "scenes": [{**new_place, "environment_details": "changed layout"}]}],
                                            project_id=task.project_id)


def test_http_queries_and_edits_share_names_and_preserve_omitted_fields(context_service, monkeypatch):
    import backend.api.scripts as api
    import backend.api.image_generation as generation_api

    service, task, pages = context_service
    neutralize(service, task, pages)
    factory = sessionmaker(bind=service.repository.session.bind)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(generation_api, "SessionLocal", factory)
    app = FastAPI(); app.include_router(api.project_pages_router); app.include_router(generation_api.router)
    with TestClient(app) as client:
        url = f"/api/projects/{task.project_id}/pages/1/script"
        result = client.put(url, json={"task_id": task.id, **text_payload(pages[0]), "scene_conditions": NIGHT})
        assert result.status_code == 200
        page = result.json()
        assert page["scene_conditions"] == NIGHT and page["script_review_status"] == "unreviewed"
        assert page["character_bindings"][0]["name"] == "Alice" and page["reference_subject_name"]
        saved = client.put(url, json={"task_id": task.id, **text_payload(pages[0])})
        assert saved.status_code == 200 and saved.json()["scene_conditions"] == NIGHT
        assert saved.json()["character_bindings"] == page["character_bindings"]
        rejected = client.put(url, json={"task_id": task.id, **text_payload(pages[0]), "scene_id": 999999})
        assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "script.scene_binding_invalid"
        listed = client.get(f"/api/projects/{task.project_id}/pages").json()["items"]
        assert listed[0]["scene_name"] == page["scene_name"] and listed[0]["scene_conditions"] == NIGHT
        # 一页待审查不会阻止出图工作台查询其它页面的当前准备状态。
        generation = client.get(f"/api/image-generation/script-tasks/{task.id}/pages")
        assert generation.status_code == 200 and len(generation.json()["items"]) == 2
