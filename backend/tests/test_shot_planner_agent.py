from copy import deepcopy

import pytest

from backend.agents.shot_planner_agent import ShotPlannerAgent
from backend.agents.structured_output import StructuredOutputError
from backend.agents.visual_agent_models import ShotPlanResponse


@pytest.mark.asyncio
async def test_unavailable_controls_are_dropped_with_warning(monkeypatch) -> None:
    response = ShotPlanResponse.model_validate(
        {
            "camera": {"shot_type": "medium", "angle": "eye level"},
            "subjects": [
                {
                    "character_key": "alice",
                    "action": "stands",
                    "pose": "upright",
                    "expression": "focused",
                    "region": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.8},
                    "depth_order": 1,
                    "control_requirements": ["pose", "canny"],
                }
            ],
            "scene": {
                "framing_notes": "centered",
                "focal_point": "alice",
                "control_requirements": ["depth"],
            },
            "render_text": False,
        }
    )

    async def fake_invoke(*_args, **kwargs):
        kwargs["validator"](response)
        return response

    monkeypatch.setattr(
        "backend.agents.shot_planner_agent.create_structured_agent",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "backend.agents.shot_planner_agent.ainvoke_structured_with_retries",
        fake_invoke,
    )
    planner = ShotPlannerAgent(llm=object(), system_prompt="test")

    plan = await planner.plan(
        page={"page_no": 1},
        snapshot={"characters": [{"character_key": "alice"}]},
        available_controls=["pose"],
    )

    assert plan["subjects"][0]["control_requirements"] == ["pose"]
    assert plan["scene"]["control_requirements"] == []
    assert plan["warnings"][0]["code"] == "shot_plan.control_unavailable"
    assert "canny" in plan["warnings"][0]["message"]
    assert "depth" in plan["warnings"][0]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key,valid", [("catalog_key", True), ("invented_key", False)])
async def test_shot_planner_accepts_only_catalog_visible_prop_keys(monkeypatch, key, valid) -> None:
    response = ShotPlanResponse.model_validate({
        "camera": {"shot_type": "close-up", "angle": "eye level"},
        "subjects": [{"character_key": "alice", "action": "holds an object", "pose": "upright", "expression": "focused", "region": {"x": 0, "y": 0, "width": 1, "height": 1}, "depth_order": 0, "reference_view": "side", "reference_framing": "face", "visible_prop_keys": [key]}],
        "scene": {"framing_notes": "no background", "focal_point": "face", "background_visible": False, "visible_prop_keys": []},
    })

    async def fake_invoke(*_args, **kwargs):
        kwargs["validator"](response)
        return response

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_kwargs: object())
    monkeypatch.setattr("backend.agents.shot_planner_agent.ainvoke_structured_with_retries", fake_invoke)
    planner = ShotPlannerAgent(llm=object(), system_prompt="test")
    args = dict(page={"page_no": 1}, snapshot={"characters": [{"character_key": "alice"}], "prop_catalog": [{"key": "catalog_key"}]}, available_controls=[])
    if valid:
        plan = await planner.plan(**args)
        assert plan["subjects"][0]["reference_view"] == "side"
        assert plan["subjects"][0]["reference_framing"] == "face"
        assert plan["scene"]["background_visible"] is False
    else:
        with pytest.raises(ValueError, match="unknown prop keys"):
            await planner.plan(**args)


def _prop_plan(*, subject_keys=(), scene_keys=()) -> dict:
    return {
        "camera": {"shot_type": "medium", "angle": "eye level"},
        "subjects": [{
            "character_key": "alice", "action": "holds ordinary clock repair tools beside the compass",
            "pose": "seated", "expression": "focused",
            "region": {"x": 0, "y": 0, "width": 1, "height": 1}, "depth_order": 0,
            "visible_prop_keys": list(subject_keys),
        }],
        "scene": {
            "framing_notes": "an old mechanical diagram lies on the desk",
            "focal_point": "alice", "visible_prop_keys": list(scene_keys),
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog,invalid,corrected", [
    ([{"key": "brass_compass"}],
     _prop_plan(subject_keys=["brass_compass", "clock_repair_tools"]),
     _prop_plan(subject_keys=["brass_compass"])),
    ([], _prop_plan(scene_keys=["old_mechanical_diagram"]), _prop_plan()),
])
async def test_catalog_protocol_and_retry_keep_ordinary_props_as_text(
    monkeypatch, catalog, invalid, corrected,
) -> None:
    """真实重试封装反馈合法目录，普通剧情物件仍保留在镜头文本中。"""

    calls = []
    factory_args = {}

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state["messages"])
            return {"structured_response": deepcopy(invalid if len(calls) == 1 else corrected)}

    def fake_factory(**kwargs):
        factory_args.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", fake_factory)
    planner = ShotPlannerAgent(llm=object(), system_prompt="custom saved preset without catalog guidance")
    plan = await planner.plan(
        page={"page_no": 29},
        snapshot={
            "characters": [{"character_key": "alice", "held_props": ["clock_repair_tools"]}],
            "prop_catalog": catalog,
        },
        available_controls=[],
    )

    assert factory_args["system_prompt"] == "custom saved preset without catalog guidance"
    assert len(calls) == 2  # 未知 key 必须进入重试，不能在本地静默剔除。
    guard = calls[0][-1].content.split("本次请求的参考目录协议", 1)[1]
    assert "唯一合法的 visible_prop_keys 列表是：" in guard
    assert ('["brass_compass"]' if catalog else '列表是：[]') in guard
    assert "不根据历史 held_props、prop_owners 或前页事件推演归属" in guard
    feedback = calls[1][-1].content
    assert "unknown prop keys" in feedback
    assert ("allowed visible_prop_keys (prop_catalog): ['brass_compass']" if catalog
            else "allowed visible_prop_keys (prop_catalog): []") in feedback
    assert plan["subjects"][0]["visible_prop_keys"] == corrected["subjects"][0]["visible_prop_keys"]
    assert plan["scene"]["visible_prop_keys"] == corrected["scene"]["visible_prop_keys"]
    assert "clock repair tools" in plan["subjects"][0]["action"]
    assert "mechanical diagram" in plan["scene"]["framing_notes"]


@pytest.mark.asyncio
async def test_custom_planner_preset_receives_page_local_state_protocol(monkeypatch) -> None:
    """数据库自定义 Prompt 仍收到页内状态协议，且结构化结果原样保留局部变化。"""
    calls = []
    response = _prop_plan()
    response["subjects"][0]["visible_state"] = "rain-soaked coat and a bandaged wrist"
    response["scene"]["framing_notes"] = "Workshop door remains open; tools lie on the bench"

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state["messages"])
            return {"structured_response": deepcopy(response)}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="custom saved preset")
    result = await planner.plan(
        page={"page_no": 4, "clothing": "Alice wears a rain-soaked coat", "scene": "Workshop door remains open"},
        snapshot={"characters": [{"character_key": "alice", "section_context": {"temporary_changes": "a later injury"}}]},
        available_controls=[],
    )
    message = calls[0][-1].content
    assert "本页只读角色基准、当前造型和场景设定" in message
    assert "本页局部状态协议始终适用" in message
    assert "subjects.visible_state" in message
    assert "不得直接当作本页已经发生的状态" in message
    assert "rain-soaked coat" in message
    assert result["subjects"][0]["visible_state"] == "rain-soaked coat and a bandaged wrist"
    assert result["scene"]["framing_notes"] == response["scene"]["framing_notes"]


def test_legacy_shot_plan_defaults_to_empty_page_local_state() -> None:
    assert ShotPlanResponse.model_validate(_prop_plan()).subjects[0].visible_state == ""


@pytest.mark.asyncio
async def test_persistent_non_catalog_key_fails_instead_of_being_filtered(monkeypatch) -> None:
    calls = []

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state)
            return {"structured_response": _prop_plan(subject_keys=["brown_messenger_bag"])}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="saved preset", max_structured_retries=2)
    with pytest.raises(StructuredOutputError, match="unknown prop keys.*brown_messenger_bag"):
        await planner.plan(
            page={"page_no": 4},
            snapshot={"characters": [{"character_key": "alice"}], "prop_catalog": [{"key": "brass_compass"}]},
            available_controls=[],
        )
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_at,expected_paths", [
    ("scene", ["subjects[0](character_key=alice).visible_prop_keys[0]", "scene.visible_prop_keys[0]"]),
    ("other_subject", ["subjects[0](character_key=alice).visible_prop_keys[0]", "subjects[1](character_key=bob).visible_prop_keys[0]"]),
    ("same_list", ["subjects[0](character_key=alice).visible_prop_keys[0]", "subjects[0](character_key=alice).visible_prop_keys[1]"]),
])
async def test_catalog_prop_has_one_location_with_precise_retry_feedback(
    monkeypatch, duplicate_at, expected_paths,
) -> None:
    """跨人物、人物与场景、单个列表内的重复都不能被集合去重掩盖。"""

    invalid = _prop_plan(subject_keys=["brass_compass"])
    corrected = deepcopy(invalid)
    if duplicate_at == "scene":
        invalid["scene"]["visible_prop_keys"] = ["brass_compass"]
        # 真正的画面位置由重试规划：本例保留场景而非盲目保留首个 subject。
        corrected["subjects"][0]["visible_prop_keys"] = []
        corrected["scene"]["visible_prop_keys"] = ["brass_compass"]
    elif duplicate_at == "other_subject":
        bob = deepcopy(invalid["subjects"][0])
        bob["character_key"] = "bob"
        invalid["subjects"].append(bob)
        corrected["subjects"].append({**bob, "visible_prop_keys": []})
    else:
        invalid["subjects"][0]["visible_prop_keys"].append("brass_compass")
    calls = []

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state["messages"])
            return {"structured_response": deepcopy(invalid if len(calls) == 1 else corrected)}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="saved preset")
    result = await planner.plan(
        page={"page_no": 11},
        snapshot={
            "characters": [{"character_key": item["character_key"], "held_props": []} for item in invalid["subjects"]],
            "prop_catalog": [{"key": "brass_compass"}],
        },
        available_controls=[],
    )

    assert len(calls) == 2
    feedback = calls[1][-1].content
    assert "multiple locations" in feedback
    assert "brass_compass" in feedback
    assert all(path in feedback for path in expected_paths)
    assert result["subjects"] == ShotPlanResponse.model_validate(corrected).model_dump()["subjects"]
    assert result["scene"]["visible_prop_keys"] == corrected["scene"]["visible_prop_keys"]


@pytest.mark.asyncio
async def test_transient_prop_action_is_not_rejected_for_empty_held_state(monkeypatch) -> None:
    """当前页短暂摆放不必产生持续持有事件，空 held_props 不能硬否定动作。"""

    response = _prop_plan(subject_keys=["brass_compass"])
    response["subjects"][0]["action"] = "briefly steadies the compass while placing it on the table"

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            return {"structured_response": response}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="saved preset")
    result = await planner.plan(
        page={"page_no": 31},
        snapshot={"characters": [{"character_key": "alice", "held_props": []}], "prop_catalog": [{"key": "brass_compass"}]},
        available_controls=[],
    )
    assert result["subjects"][0]["visible_prop_keys"] == ["brass_compass"]


@pytest.mark.asyncio
async def test_duplicate_character_is_rejected_before_accepting_corrected_plan(monkeypatch) -> None:
    """同一人物重复实例由既有 schema 校验进入真实结构化重试。"""

    valid = _prop_plan()
    invalid = deepcopy(valid)
    invalid["subjects"].append(deepcopy(invalid["subjects"][0]))
    calls = []

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state["messages"])
            return {"structured_response": invalid if len(calls) == 1 else valid}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="saved preset")
    result = await planner.plan(
        page={"page_no": 1}, snapshot={"characters": [{"character_key": "alice"}]}, available_controls=[],
    )
    assert len(calls) == 2
    assert "duplicate character_key" in calls[1][-1].content
    assert [subject["character_key"] for subject in result["subjects"]] == ["alice"]


@pytest.mark.asyncio
async def test_empty_visible_environment_retries_instead_of_silently_losing_scene(monkeypatch) -> None:
    invalid, valid = _prop_plan(), _prop_plan()
    invalid["scene"]["framing_notes"] = " "
    valid["scene"]["framing_notes"] = "Arched stone window, oak desk and rain outside under warm lamplight"
    calls = []

    class FakeAgent:
        async def ainvoke(self, state, config=None):
            calls.append(state["messages"])
            return {"structured_response": invalid if len(calls) == 1 else valid}

    monkeypatch.setattr("backend.agents.shot_planner_agent.create_structured_agent", lambda **_: FakeAgent())
    planner = ShotPlannerAgent(llm=object(), system_prompt="saved preset")
    result = await planner.plan(
        page={"page_no": 1}, snapshot={"characters": [{"character_key": "alice"}]}, available_controls=[],
    )
    assert len(calls) == 2
    assert "nonempty framing_notes" in calls[1][-1].content
    assert result["scene"]["framing_notes"] == valid["scene"]["framing_notes"]
