"""复现场景摘要的分类失败，验证重试纠正与三类 Prompt。"""

import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.agents.reference_visual_agent import ReferenceVisualAgent
from backend.models.enums import ImagePromptType, VisualAssetRole
from backend.models.reference_visual import FixedSceneVisualExtraction, ReferenceVisualExtraction
from backend.services.reference_visual_profile_service import validate_data, validate_extraction
from backend.services.reference_visual_prompt_compiler import ReferenceVisualPromptCompiler
from backend.tests.reference_visual_fakes import fact, profile


@pytest.fixture
def scene_source():
    return {"kind": "scene_subject", "owner_id": 1, "scene_definition_version": 2,
            "fields": {"description": "木制桌面有固定刻痕；天花板为日光灯管支架。",
                       "negative_constraints": "禁止固化时段、天气、光照和氛围；禁止包含任何角色；不得增加现代显示屏。"},
            "bindings": {}}


def scene_fact(field, excerpt, natural, kind, attribute, polarity="required"):
    item = fact(field, excerpt, natural, kind, ["scene_master"], polarity)
    item["attribute"] = attribute
    return item


def scene_output():
    return {"profiles": [{"kind": "scene_subject", "owner_id": 1,
                          "data": {"human": False, "facts": [
        scene_fact("description", "木制桌面有固定刻痕", "Carved marks on wooden desk tops.", "material", "desk_surface_marks"),
        scene_fact("description", "日光灯管支架", "Ceiling-mounted fluorescent tube fixtures.", "environment", "ceiling_fixtures"),
        scene_fact("negative_constraints", "不得增加现代显示屏", "Modern display screens.", "environment", "modern_screens", "forbidden"),
    ]}}]}


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_fixed_details_and_real_exclusions_compile_without_page_conditions(scene_source, prompt_type):
    """灯具与旧刻痕保留，定义范围说明不进入任何正负 Prompt。"""
    result = FixedSceneVisualExtraction.model_validate(scene_output())
    validate_extraction(result, [scene_source])
    pair = ReferenceVisualPromptCompiler().compile(
        profiles=[profile("scene_subject", result.profiles[0].data.model_dump(mode="json")["facts"], human=False)],
        roles=[VisualAssetRole.SCENE_MASTER], prompt_type=prompt_type)["scene_master"]
    assert "Carved marks" in pair["positive"]
    assert "fluorescent tube fixtures" in pair["positive"]
    assert "Modern display screens" in pair["negative"]
    assert "Modern display screens" not in pair["positive"]
    assert "weather" not in pair["negative"]
    assert "lighting" not in pair["negative"]


@pytest.mark.parametrize("polarity", ["required", "forbidden"])
@pytest.mark.parametrize("kind", ["object_state", "identity", "lighting"])
def test_v2_rejects_nonfixed_types_in_schema_and_business_validation(scene_source, polarity, kind):
    output = scene_output()
    item = output["profiles"][0]["data"]["facts"][0]
    item.update(kind=kind, polarity=polarity)
    with pytest.raises(ValidationError):
        FixedSceneVisualExtraction.model_validate(output)
    # 人工编辑与非模型入口仍经过相同业务边界，不能绕过 schema。
    with pytest.raises(ValueError, match=r"scene_subject/1: invalid fixed-scene facts:.*desk_surface_marks"):
        validate_extraction(ReferenceVisualExtraction.model_validate(output), [scene_source])


def test_feedback_reports_all_invalid_facts_with_source_and_correction(scene_source):
    """原失败一次含多条错误，不能每次重试只提示第一条。"""
    output = scene_output()
    facts = output["profiles"][0]["data"]["facts"]
    facts[0]["kind"] = "object_state"
    facts[1]["kind"] = "lighting"
    facts.append(scene_fact("negative_constraints", "禁止包含任何角色", "Any characters.",
                            "identity", "character_presence", "forbidden"))
    with pytest.raises(ValueError) as error:
        validate_extraction(ReferenceVisualExtraction.model_validate(output), [scene_source])
    message = str(error.value)
    for value in ["object_state.desk_surface_marks", "lighting.ceiling_fixtures", "identity.character_presence",
                  "source_field=description", "禁止包含任何角色", "both required and forbidden", "definition-scope"]:
        assert value in message


def test_fixed_scene_agent_uses_restricted_schema_and_corrects_failed_output(scene_source, monkeypatch):
    import backend.agents.reference_visual_agent as module

    class Stub:
        def __init__(self):
            self.messages = []

        async def ainvoke(self, state, config=None):
            self.messages.append(state["messages"])
            output = scene_output()
            if len(self.messages) == 1:
                output["profiles"][0]["data"]["facts"][0]["kind"] = "object_state"
            return {"structured_response": output}

    generic, fixed = Stub(), Stub()
    schemas = []

    def factory(**kwargs):
        schemas.append(kwargs["response_model"])
        return fixed if kwargs["response_model"] is FixedSceneVisualExtraction else generic

    monkeypatch.setattr(module, "create_structured_agent", factory)
    agent = ReferenceVisualAgent(llm=object())
    original = deepcopy(scene_source)
    result = asyncio.run(agent.extract([scene_source], []))
    assert type(result) is ReferenceVisualExtraction
    assert schemas == [ReferenceVisualExtraction, FixedSceneVisualExtraction]
    assert len(fixed.messages) == 2 and not generic.messages
    assert "object_state" in fixed.messages[1][-1].content
    assert "material" in fixed.messages[1][-1].content
    assert scene_source == original
    validate_extraction(result, [scene_source])


@pytest.mark.parametrize("version", [None, 1])
def test_scene_definition_version_does_not_relax_extraction_schema(scene_source, monkeypatch, version):
    import backend.agents.reference_visual_agent as module
    source = deepcopy(scene_source)
    source.pop("scene_definition_version")
    if version is not None:
        source["scene_definition_version"] = version
    output = scene_output()
    schemas = []

    class Stub:
        async def ainvoke(self, state, config=None):
            return {"structured_response": output}

    def factory(**kwargs):
        schemas.append(kwargs["response_model"])
        return Stub()

    monkeypatch.setattr(module, "create_structured_agent", factory)
    result = asyncio.run(ReferenceVisualAgent(llm=object()).extract([source], []))
    assert schemas == [ReferenceVisualExtraction, FixedSceneVisualExtraction]
    validate_data(result.profiles[0].data, source, extracted=True)


def test_fixed_scene_schema_keeps_source_evidence_validation(scene_source):
    output = scene_output()
    output["profiles"][0]["data"]["facts"][0]["source_excerpt"] = "fabricated evidence"
    with pytest.raises(ValueError, match="exact source field and excerpt"):
        validate_extraction(FixedSceneVisualExtraction.model_validate(output), [scene_source])
