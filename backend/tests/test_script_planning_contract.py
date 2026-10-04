"""规划地点覆盖、锁定快照和审查修订的离线回归，不调用真实模型。"""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.agents.page_script_writer_agent import PageScriptWriterAgent
from backend.agents.script_supervisor_agent import ScriptSupervisorAgent
from backend.models.enums import ScriptGenerationMode, ScriptGenerationTaskStatus
from backend.repositories.comic_repository import ComicRepository
from backend.services.script_service import ScriptService
from backend.tests.test_page_visual_context import context_service


def _section_plan():
    return {
        "section_no": 1, "page_start": 1, "page_end": 2,
        "title": "Campus", "description": "Establish the campus, then show a student in the classroom.",
        "scenes": [
            {"scene_key": "campus", "name": "Campus", "environment_details": "open lawn and campus buildings",
             "reference_subject_key": None},
            {"scene_key": "classroom", "name": "Classroom", "environment_details": "fixed desks and blackboard",
             "reference_subject_key": None},
        ],
        "characters": [],
        "page_plan": [
            {"page_no": 2, "scene_key": "classroom", "beat": "A student sits beside a notebook."},
            {"page_no": 1, "scene_key": "campus", "beat": "The rain-soaked campus is empty."},
        ],
    }


def _planning_service():
    service = ScriptService(SimpleNamespace())
    service._neutral_scene_catalog = lambda _project_id: []
    return service


def test_page_plan_survives_normalization_and_new_locations_are_allowed():
    sections = ScriptService._normalize_section_plan(sections=[_section_plan()], total_pages=2)
    _planning_service()._validate_neutral_scene_plan(sections, project_id=1, require_page_plan=True)
    assert [item["page_no"] for item in sections[0]["page_plan"]] == [1, 2]
    assert [item["scene_key"] for item in sections[0]["page_plan"]] == ["campus", "classroom"]
    assert all(scene["reference_subject_key"] is None for scene in sections[0]["scenes"])


@pytest.mark.parametrize("invalid_plan,error", [
    (None, "must define page_plan"),
    ([], "must define page_plan"),
    ({"page_no": 1}, "must be a list"),
    (["campus"], "must be an object"),
    ([{"page_no": 1, "scene_key": "campus", "beat": "rain"}], "missing pages"),
    ([{"page_no": 1, "scene_key": "campus", "beat": "rain"}] * 2, "duplicate page_plan"),
    ([{"page_no": 3, "scene_key": "campus", "beat": "rain"}], "outside section range"),
    ([{"page_no": 1, "scene_key": "missing_campus", "beat": "rain"}], "not defined in section"),
    ([{"page_no": 1, "scene_key": "campus", "beat": "  "}], "missing core beat"),
])
def test_invalid_page_plan_is_rejected_before_locking(invalid_plan, error):
    section = {**_section_plan(), "page_plan": invalid_plan}
    with pytest.raises(ValueError, match=error):
        _planning_service()._validate_neutral_scene_plan([section], project_id=1, require_page_plan=True)


def test_legacy_plan_without_page_plan_keeps_compatible_context():
    section = _section_plan()
    section.pop("page_plan")
    normalized = ScriptService._normalize_section_plan(sections=[section], total_pages=2)
    service = _planning_service()
    service._validate_neutral_scene_plan(normalized, project_id=1)
    service._section_to_payload = lambda _section: {"section_no": 1}
    assert service._section_agent_context(SimpleNamespace(), {"scenes": [], "characters": []})["page_plan"] == []


def test_locked_page_plan_reaches_writer_and_supervisor_after_reload(context_service):
    image_service, old_task, _pages = context_service
    session = image_service.repository.session
    repository = ComicRepository(session)
    service = ScriptService(repository)
    task = repository.create_script_task(
        project_id=old_task.project_id, outline_version_id=old_task.outline_version_id,
        mode=ScriptGenerationMode.BATCH, status=ScriptGenerationTaskStatus.RUNNING,
        total_pages=2, scene_definition_version=2,
    )
    normalized = service._normalize_section_plan(sections=[_section_plan()], total_pages=2)
    service._validate_neutral_scene_plan(normalized, project_id=task.project_id, require_page_plan=True)
    service._persist_section_plan(task_id=task.id, outline_version_id=task.outline_version_id,
                                  normalized_sections=normalized)
    session.expire_all()
    section = repository.list_script_sections(task.id)[0]
    locked = service._section_visual_context(task_id=task.id, section=section, outline_version_id=task.outline_version_id)
    assert locked["page_plan"] == json.loads(task.section_plan)[0]["page_plan"] == normalized[0]["page_plan"]
    current_section = service._section_agent_context(section, locked)
    writer_input = PageScriptWriterAgent._build_section_input(
        outline="Campus story", total_pages=2, current_section=current_section, target_page_no=1,
        section_scenes=locked["scenes"], section_characters=[], outline_characters=[],
        previous_context={}, user_requirement="", feedback="", is_revision=False, current_pages=[],
    )
    supervisor_input = ScriptSupervisorAgent._build_review_input(
        outline="Campus story", current_section=current_section,
        section_scenes=locked["scenes"], section_characters=[], outline_characters=[], pages=[],
    )
    for content in (writer_input, supervisor_input):
        assert "第 1 页，场景 key：campus" in content
        assert "The rain-soaked campus is empty." in content
        assert "第 2 页，场景 key：classroom" in content


def test_revision_feedback_only_targets_failed_pages_and_preserves_passed_reviews():
    reviews = [
        {"page_no": 1, "passed": True, "summary": "Single moment; optional prose shortening.",
         "revision_suggestions": ["Shorten the description if desired."]},
        {"page_no": 2, "passed": False, "summary": "The glasses are both worn and being put on.",
         "revision_suggestions": ["Keep the glasses already worn."]},
    ]
    original = deepcopy(reviews)
    feedback = ScriptService._review_feedback_by_page_no(reviews)
    assert set(feedback) == {2}
    assert "Keep the glasses already worn." in feedback[2]
    assert "Shorten the description" not in feedback[2]
    assert ScriptService._revision_page_nos_from_reviews(reviews) == [2]
    assert ScriptService._section_review_passed({"reviews": reviews[:1]})
    assert reviews == original


@pytest.mark.asyncio
@pytest.mark.parametrize("always_invalid", [False, True])
async def test_batch_retries_missing_location_before_lock_or_writer(context_service, monkeypatch, always_invalid):
    """复现目录只有室内却规划校园的死循环，校验失败不能进入页面生成阶段。"""

    image_service, old_task, _pages = context_service
    repository = ComicRepository(image_service.repository.session)
    service = ScriptService(repository)
    task = repository.create_script_task(
        project_id=old_task.project_id, outline_version_id=old_task.outline_version_id,
        mode=ScriptGenerationMode.BATCH, status=ScriptGenerationTaskStatus.RUNNING,
        total_pages=2, scene_definition_version=2,
    )
    calls = []
    workers_started = []

    class Planner:
        async def generate_section_plan(self, **kwargs):
            calls.append(kwargs)
            plan = _section_plan()
            if always_invalid or len(calls) == 1:
                plan["scenes"] = [scene for scene in plan["scenes"] if scene["scene_key"] != "campus"]
            return [plan]

    async def start_workers(**kwargs):
        workers_started.append(kwargs)
        section = kwargs["persisted_sections"][0]
        locked = service._section_visual_context(task_id=task.id, section=section, outline_version_id=task.outline_version_id)
        assert {scene["scene_key"] for scene in locked["scenes"]} == {"campus", "classroom"}
        assert locked["page_plan"][0]["scene_key"] == "campus"
        yield "phase", {"code": "test.workers.started"}

    monkeypatch.setattr("backend.services.script_service.ScriptPlanningAgent", lambda: Planner())
    monkeypatch.setattr(service, "_stream_concurrent_sections", start_workers)
    events = [event async for event in service._stream_batch_task(
        task=task, outline_version=old_task.outline_version, user_requirement="", is_continue=False,
    )]
    assert "campus" in calls[1]["feedback"]
    if always_invalid:
        assert len(calls) == 3 and not workers_started
        assert task.status == ScriptGenerationTaskStatus.FAILED
        assert repository.list_script_sections(task.id) == []
        assert task.section_plan is None
        assert events[-1][0] == "error"
    else:
        assert len(calls) == 2 and len(workers_started) == 1
        assert task.status == ScriptGenerationTaskStatus.SUCCEEDED
        assert events[-1][0] == "done"
        assert any(payload.get("code") == "script.planning.locked" for _name, payload in events)
