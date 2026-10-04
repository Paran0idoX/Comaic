from types import SimpleNamespace

import pytest

from backend.agents.page_script_writer_agent import PageScriptWriterAgent
from backend.models.enums import PageScriptReviewStatus, ScriptGenerationTaskStatus
from backend.services.script_service import ScriptService


def _visible_character_context():
    return {
        "scenes": [{"scene_key": "bookshop"}],
        "characters": [
            {"character_key": "lin_cheng", "name": "林澄"},
            {"character_key": "chen_yan", "name": "陈砚"},
        ],
    }


def _visible_character_page(**changes):
    """保留真实 50 页验收中漏绑人物的文字，防止只验证 key 合法性。"""

    return {
        "section_no": 1,
        "page_no": 1,
        "scene_key": "bookshop",
        "character_keys": ["lin_cheng"],
        "summary": "林澄进入旧书店。",
        "characters": (
            "林澄，26岁东亚女性，送件人，安静克制，进门时神情专注，脸颊与短发带轻微雨气；"
            "陈砚，55岁东亚男性，旧书店主人，高瘦，沉稳，从书架前转身，投来询问的目光。"
        ),
        "clothing": "两人保持当前服装。",
        "scene": "旧书店。",
        "composition": "右侧为敞开的门与进入的林澄，左侧为书架前的陈砚。",
        "character_action": "两人目光相接。",
        "dialogue": "无",
        **changes,
    }


def test_visible_character_missing_binding_rejected_before_save() -> None:
    with pytest.raises(ValueError, match="入镜人物缺少 character_keys：chen_yan"):
        ScriptService._validate_page_visual_references(
            pages=[_visible_character_page()], visual_context=_visible_character_context()
        )


def test_locked_database_validation_also_rejects_missing_character_binding() -> None:
    repository = SimpleNamespace(
        list_script_scenes=lambda _task_id: [SimpleNamespace(id=10, scene_key="bookshop")],
        list_script_section_characters=lambda _section_id: [
            SimpleNamespace(id=index, **character)
            for index, character in enumerate(_visible_character_context()["characters"], 1)
        ],
    )
    service = ScriptService(repository)
    with pytest.raises(ValueError, match="chen_yan"):
        service._visual_settings_for_section(
            task_id=2, section_id=3, outline_version_id=2, pages=[_visible_character_page()]
        )
    settings = service._visual_settings_for_section(
        task_id=2, section_id=3, outline_version_id=2,
        pages=[_visible_character_page(character_keys=["lin_cheng", "chen_yan"])],
    )
    assert settings["character_ids_by_key"] == {"lin_cheng": 1, "chen_yan": 2}


@pytest.mark.parametrize("characters", [
    "林澄，站在书店门口。",
    "林澄，站在书店门口；陈砚不入镜。",
    "林澄，站在书店门口；陈砚（画外音，不入镜）。",
    "林澄，站在书店门口；陈砚，画外音。",
    "林澄，站在书店门口；陈砚本页未在画面中出现。",
    "林澄看向画面外的陈砚。",
    "林澄凝望未入镜的陈砚。",
])
def test_offscreen_or_dialogue_mentions_do_not_require_binding(characters) -> None:
    ScriptService._validate_page_visual_references(
        pages=[_visible_character_page(
            characters=characters,
            summary="陈砚曾经告诉林澄一段旧事。",
            composition="林澄独自站在门口。",
            character_action="林澄听见陈砚的声音。",
            dialogue="陈砚（画外音）：欢迎。",
        )],
        visual_context=_visible_character_context(),
    )


@pytest.mark.parametrize("characters", ["无", "无角色出场", "无人物入镜。", "无人", "陈砚（画外音）"])
def test_empty_visible_cast_is_allowed(characters) -> None:
    ScriptService._validate_page_visual_references(
        pages=[_visible_character_page(characters=characters, character_keys=[])],
        visual_context=_visible_character_context(),
    )


@pytest.mark.parametrize("characters, keys", [
    ("林澄站在门口；陈砚不入镜。", ["lin_cheng", "chen_yan"]),
    ("无角色出场", ["lin_cheng"]),
])
def test_explicitly_offscreen_characters_cannot_be_bound(characters, keys) -> None:
    with pytest.raises(ValueError):
        ScriptService._validate_page_visual_references(
            pages=[_visible_character_page(characters=characters, character_keys=keys)],
            visual_context=_visible_character_context(),
        )


def test_similar_names_are_not_matched_as_substrings() -> None:
    ScriptService._validate_page_visual_references(
        pages=[_visible_character_page(characters="林澄，站在门口。")],
        visual_context={
            "scenes": [{"scene_key": "bookshop"}],
            "characters": _visible_character_context()["characters"] + [
                {"character_key": "lin", "name": "林"},
            ],
        },
    )


@pytest.mark.asyncio
async def test_writer_retries_only_invalid_page_with_missing_character_feedback(monkeypatch) -> None:
    """缺失绑定进入现有单页重试闭环，不生成其它页，也不静默补入猜测的角色。"""

    calls = []
    class Writer:
        async def generate_page(self, **kwargs):
            calls.append(kwargs)
            keys = ["lin_cheng"] if len(calls) == 1 else ["lin_cheng", "chen_yan"]
            return [_visible_character_page(character_keys=keys)]

    service = ScriptService(SimpleNamespace())
    monkeypatch.setattr(service, "_is_script_task_suspended", lambda _task_id: False)
    monkeypatch.setattr(service, "_section_to_payload", lambda section: {"section_no": section.section_no})
    async def complete(_task_id, operation):
        return False, await operation
    monkeypatch.setattr(service, "_await_agent_or_suspended", complete)
    suspended, page, events = await service._generate_page_payload(
        writer_agent=Writer(), task_id=2, outline="测试大纲", total_pages=50,
        section=SimpleNamespace(section_no=1, page_start=1, page_end=10, title="书店", description="到访"),
        page_no=1, visual_context=_visible_character_context(), outline_characters=[],
        previous_context={}, user_requirement="", current_pages=[], is_revision=False, feedback="",
    )
    assert not suspended
    assert page["character_keys"] == ["lin_cheng", "chen_yan"]
    assert len(calls) == 2
    assert all(call["target_page_no"] == 1 for call in calls)
    assert "chen_yan" in calls[1]["feedback"]
    assert any(payload.get("code") == "script.page.validation_failed" for _name, payload in events)


def test_writer_input_lists_exact_allowed_visual_keys() -> None:
    """把允许 key 放在输入前部，降低模型沿用上一分段场景的概率。"""

    prompt = PageScriptWriterAgent._build_section_input(
        outline="测试大纲",
        total_pages=50,
        current_section={"section_no": 8, "page_start": 36, "page_end": 40},
        target_page_no=36,
        section_scenes=[
            {"scene_key": "hidden_staircase", "name": "隐藏楼梯"},
            {"scene_key": "corridor_outside", "name": "走廊"},
        ],
        section_characters=[{"character_key": "lin_lan", "name": "林岚"}],
        previous_context={},
        outline_characters=[],
        user_requirement="",
        feedback="",
        is_revision=False,
        current_pages=[],
    )

    assert "本页 scene_key 允许值（只能逐字复制其中一个）：hidden_staircase、corridor_outside" in prompt
    assert "本页 character_keys 允许值（只能逐字复制，或无角色时返回空数组）：lin_lan" in prompt


def test_visual_reference_feedback_lists_allowed_scene_keys() -> None:
    """校验失败反馈必须给出可用 key，才能让同页重试形成有效闭环。"""

    with pytest.raises(ValueError) as exc_info:
        ScriptService._validate_page_visual_references(
            pages=[
                {
                    "page_no": 36,
                    "scene_key": "hidden_office",
                    "character_keys": ["lin_lan"],
                    "characters": "林岚",
                }
            ],
            visual_context={
                "scenes": [
                    {"scene_key": "hidden_staircase"},
                    {"scene_key": "corridor_outside"},
                ],
                "characters": [{"character_key": "lin_lan"}],
            },
        )

    message = str(exc_info.value)
    assert "hidden_office" in message
    assert "corridor_outside、hidden_staircase" in message
    assert "重写整页" in message


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_first_plan", [False, True])
async def test_single_page_generation_saves_supervisor_passed_status(monkeypatch, invalid_first_plan) -> None:
    """单页已通过 Supervisor 后应直接可进入后续链路，不能再次落成未审查。"""

    class Repository:
        def __init__(self):
            self.task = SimpleNamespace(
                id=7,
                project_id=1,
                status=ScriptGenerationTaskStatus.RUNNING,
            )
            self.saved_kwargs = None

        def create_script_task(self, **_kwargs):
            return self.task

        def upsert_page_script(self, **kwargs):
            self.saved_kwargs = kwargs
            return SimpleNamespace(id=9, page_no=3)

        def update_script_task(self, *, status=None, section_plan=None, **_kwargs):
            if status is not None:
                self.task.status = status
            if section_plan is not None:
                self.task.section_plan = section_plan
            return self.task

        def get_script_task(self, _task_id):
            return self.task

    class Writer:
        async def generate_page(self, **kwargs):
            assert kwargs["current_section"]["page_plan"] == page_plan
            return [{"page_no": 3}]

    class Supervisor:
        async def review_section_pages(self, **kwargs):
            assert kwargs["current_section"]["page_plan"] == page_plan
            return {"passed": True, "reviews": [{"page_no": 3, "passed": True}]}

    repository = Repository()
    service = ScriptService(repository)
    planning_calls = []
    page_plan = [{"page_no": 3, "scene_key": "single_scene", "beat": "stands"}]
    class Planner:
        async def generate_section_plan(self, **kwargs):
            assert kwargs["target_page_no"] == 3
            planning_calls.append(kwargs)
            if invalid_first_plan and len(planning_calls) == 1:
                planned_pages = [{**page_plan[0], "scene_key": "missing_campus"}]
            else:
                planned_pages = page_plan
            return [{"section_no": 1, "page_start": 3, "page_end": 3,
                     "scenes": [{"scene_key": "single_scene", "name": "Room", "environment_details": "fixed desk"}],
                     "characters": [], "page_plan": planned_pages}]
    monkeypatch.setattr("backend.services.script_service.ScriptPlanningAgent", lambda: Planner())
    monkeypatch.setattr(service, "_neutral_scene_catalog", lambda _project_id: [])
    monkeypatch.setattr(service, "_section_visual_context", lambda **_kwargs: {
        "scenes": [{"scene_key": "single_scene", "scene_definition_version": 2}],
        "characters": [{"character_key": "hero", "name": "hero"}],
        "page_plan": page_plan,
    })
    section = SimpleNamespace(id=8, task_id=7, page_start=3, page_end=3)
    page_payload = {
        "page_no": 3,
        "scene_conditions": {"time_of_day": "day", "weather": "", "lighting": "", "atmosphere": ""},
        "scene_key": "single_scene",
        "character_keys": ["hero"],
        "summary": "summary",
        "characters": "hero",
        "clothing": "coat",
        "scene": "room",
        "composition": "medium shot",
        "character_action": "stands",
        "dialogue": "none",
    }

    monkeypatch.setattr(
        "backend.services.script_service.PageScriptWriterAgent", lambda: Writer()
    )
    monkeypatch.setattr(
        "backend.services.script_service.ScriptSupervisorAgent", lambda: Supervisor()
    )
    monkeypatch.setattr(
        service,
        "_resolve_outline_version",
        lambda **_kwargs: SimpleNamespace(id=2, content="outline"),
    )
    monkeypatch.setattr(service, "_create_single_page_section", lambda **_kwargs: section)
    monkeypatch.setattr(service, "_section_to_payload", lambda _section: {})
    monkeypatch.setattr(service, "_outline_characters_context", lambda _id: [])
    monkeypatch.setattr(service, "_save_section_visual_settings", lambda **_kwargs: None)
    monkeypatch.setattr(service, "_normalize_single_page", lambda **_kwargs: [page_payload])
    monkeypatch.setattr(
        service,
        "_visual_settings_for_section",
        lambda **_kwargs: {
            "scene_ids_by_key": {"single_scene": 11},
            "character_ids_by_key": {"hero": 12},
        },
    )

    task, _page = await service.generate_single_page_script(
        project_id=1,
        page_no=3,
        total_pages=5,
        outline_version_id=2,
    )

    assert task.status == ScriptGenerationTaskStatus.SUCCEEDED
    assert repository.saved_kwargs["script_review_status"] == PageScriptReviewStatus.PASSED
    assert len(planning_calls) == (2 if invalid_first_plan else 1)
    if invalid_first_plan:
        assert "missing_campus" in planning_calls[1]["feedback"]
