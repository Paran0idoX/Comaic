"""验证退役字段不再进入创作契约，同时兼容旧输入。"""

import pytest

from backend.agents.outline_character_agent import OutlineCharacterItem
from backend.agents.script_agent_models import ScriptCharacterItem, ScriptSceneItem
from backend.api.schemas.outline import OutlineCharacterResponse
from backend.api.schemas.script import ScriptCharacterResponse, ScriptSceneResponse
from backend.models.comic import OutlineCharacter, ScriptCharacter, ScriptScene
from backend.services.outline_service import OutlineService
from backend.services.script_service import ScriptService


@pytest.mark.parametrize("schema", [OutlineCharacterItem, ScriptCharacterItem, ScriptSceneItem,
                                    OutlineCharacterResponse, ScriptCharacterResponse, ScriptSceneResponse])
def test_creation_and_api_schemas_exclude_retired_field(schema):
    """新 Agent 和 API 不再生成、要求或返回该字段。"""
    assert "visual_anchors" not in schema.model_fields


@pytest.mark.parametrize("model", [OutlineCharacter, ScriptCharacter, ScriptScene])
def test_current_tables_exclude_retired_field(model):
    assert "visual_anchors" not in model.__table__.columns


@pytest.mark.parametrize("normalize,payload", [
    (OutlineService._normalize_outline_character_payload,
     {"character_key": "hero", "name": "Hero", "appearance": "short hair"}),
    (ScriptService._normalize_scene_payload,
     {"scene_key": "room", "name": "Room", "environment_details": "wooden table"}),
    (ScriptService._normalize_character_payload,
     {"character_key": "hero", "name": "Hero", "section_role": "protagonist"}),
])
def test_normalizers_accept_settings_without_anchors_and_ignore_legacy_values(normalize, payload):
    expected = normalize(payload)
    assert "visual_anchors" not in expected
    assert normalize({**payload, "visual_anchors": "obsolete marker"}) == expected
