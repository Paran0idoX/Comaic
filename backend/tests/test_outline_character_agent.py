"""离线验证角色分类、历史候选和结构化重试，不创建真实模型。"""

from copy import deepcopy

import pytest

from backend.agents.outline_character_agent import OutlineCharacterAgent
from backend.agents.structured_output import StructuredOutputError


def character_settings(name="阿岚", key="alan", appearance="成年人，黑色短发"):
    return {
        "character_key": key, "name": name, "role": "独立参与故事的角色",
        "background": "", "appearance": appearance, "negative_constraints": "",
        "default_hairstyle": "", "default_clothing": "", "default_accessories": "",
        "default_color_palette": "",
    }


def candidate(name="阿岚", kind="character", character=None):
    return {
        "name": name, "kind": kind, "classification_reason": "具有独立身份和形象" if kind == "character" else "不是独立故事参与者",
        "character": character,
    }


def valid_response():
    return {"entities": [candidate(character=character_settings())]}


class ScriptedAgent:
    """依次提供预设结构化响应并记录重试反馈。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def ainvoke(self, state, config=None):
        self.calls.append(state)
        return deepcopy(self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


def make_agent(monkeypatch, responses):
    scripted = ScriptedAgent(responses)
    monkeypatch.setattr("backend.agents.outline_character_agent.create_structured_agent", lambda **kwargs: scripted)
    return OutlineCharacterAgent(llm=object()), scripted


@pytest.mark.asyncio
async def test_independent_nonhuman_roles_are_kept_and_other_entities_excluded(monkeypatch):
    actors = [
        character_settings(),
        character_settings("小狗", "dog", "白色小狗，左耳有黑斑"),
        character_settings("机器人", "robot", "蓝色金属外壳，方形头部"),
        character_settings("会说话的茶壶", "teapot", "红色茶壶，有独立人格并主动帮助主角"),
    ]
    others = [candidate("手机", "prop"), candidate("办公室", "scene"), candidate("软肋（把柄载体）", "concept")]
    agent, scripted = make_agent(monkeypatch, [{"structured_response": {"entities": [
        *[candidate(item["name"], character=item) for item in actors], *others,
    ]}}])
    result = await agent.generate_characters(outline="人物、动物、机器人和拟人茶壶参与故事。")
    assert result == actors
    assert len(scripted.calls) == 1
    assert all("kind" not in item and "classification_reason" not in item for item in result)


@pytest.mark.asyncio
async def test_history_is_reclassified_and_only_real_character_keeps_key(monkeypatch):
    actor = character_settings()
    fake = character_settings("某人的软肋（把柄载体）", "old_softspot", "不单独绘制形象")
    agent, scripted = make_agent(monkeypatch, [{"structured_response": {"entities": [
        candidate(character=actor), candidate(fake["name"], "concept"),
    ]}}])
    previous = [actor, fake]
    result = await agent.generate_characters(outline="阿岚掌握一个秘密。", previous_characters=previous)
    assert result == [actor]
    text = scripted.calls[0]["messages"][0].content
    assert "待重新判断的候选，不保证都是合法角色" in text
    assert "old_softspot" in text  # 保留原文供语义判断，不靠关键词预先删记录。
    assert previous == [actor, fake]


def invalid_entities(case):
    response = valid_response()
    entity = response["entities"][0]
    if case == "kind_conflict":
        entity["kind"] = "concept"
    elif case == "settings_missing":
        entity["character"] = None
    elif case == "duplicate_key":
        response["entities"].append(candidate("另一个人", character=character_settings("另一个人", " alan ")))
    elif case == "name_mismatch":
        entity["name"] = "另一个人"
    elif case in {"character_key", "name", "appearance"}:
        entity["character"][case] = " "
    elif case == "reason_missing":
        entity["classification_reason"] = " "
    elif case == "candidate_name_missing":
        entity["name"] = " "
    elif case == "invalid_kind":
        entity["kind"] = "unknown"
    return {"structured_response": response}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["kind_conflict", "settings_missing", "duplicate_key", "name_mismatch",
                                 "character_key", "name", "appearance", "reason_missing", "candidate_name_missing", "invalid_kind"])
async def test_invalid_classification_and_settings_retry_with_feedback(monkeypatch, case):
    agent, scripted = make_agent(monkeypatch, [invalid_entities(case), {"structured_response": valid_response()}])
    assert await agent.generate_characters(outline="一个故事") == [character_settings()]
    assert len(scripted.calls) == 2
    assert "上一次失败原因" in scripted.calls[1]["messages"][-1].content


@pytest.mark.asyncio
async def test_exhausted_retries_reject_natural_language_json_fallback(monkeypatch):
    agent, scripted = make_agent(monkeypatch, [{"messages": [{"content": '{"entities": []}'}]}])
    with pytest.raises(StructuredOutputError):
        await agent.generate_characters(outline="一个故事")
    assert len(scripted.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"entities": []}, {"entities": [candidate("未公开的秘密", "concept")] }])
async def test_outline_without_characters_is_valid(monkeypatch, response):
    agent, scripted = make_agent(monkeypatch, [{"structured_response": response}])
    assert await agent.generate_characters(outline="早期设想") == []
    assert len(scripted.calls) == 1


@pytest.mark.asyncio
async def test_old_response_shape_does_not_silently_remove_all_characters(monkeypatch):
    agent, scripted = make_agent(monkeypatch, [{"structured_response": {"characters": []}}, {"structured_response": valid_response()}])
    assert await agent.generate_characters(outline="一个故事") == [character_settings()]
    assert len(scripted.calls) == 2
