import pytest

from backend.agents.shot_planner_agent import ShotPlannerAgent
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
