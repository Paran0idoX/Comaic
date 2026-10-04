"""页面环境条件及关联摘要；固定地点与当前时刻的条件分别读取。"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict


SCENE_DEFINITION_VERSION = 2


class SceneConditions(BaseModel):
    """自由文本条件，不把天气、时段或光照固化成地点身份。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    time_of_day: str = ""
    weather: str = ""
    lighting: str = ""
    atmosphere: str = ""


def page_scene_conditions(page: Any) -> dict[str, str]:
    """显式页面记录优先；只有未保存过条件的历史页读取原场景。"""
    stored = getattr(page, "scene_conditions_json", None)
    if stored is not None:
        return SceneConditions.model_validate(json.loads(stored)).model_dump()
    scene = page.script_scene
    if getattr(getattr(scene, "task", None), "scene_definition_version", 1) >= SCENE_DEFINITION_VERSION:
        return SceneConditions().model_dump()
    return SceneConditions(**{
        name: getattr(scene, name, "") or ""
        for name in ("time_of_day", "weather", "lighting")
    }).model_dump()


def page_binding_payload(page: Any) -> dict[str, Any]:
    """HTTP 与 SSE 共用关联摘要，前端无需通过 key 猜测条目归属。"""
    scene = page.script_scene
    subject = scene.reference_subject if scene is not None else None
    return {
        "scene_name": scene.name if scene is not None else None,
        "reference_subject_id": scene.reference_subject_id if scene is not None else None,
        "reference_subject_name": subject.name if subject is not None else None,
        "scene_conditions": page_scene_conditions(page),
        "character_bindings": [{
            "id": character.id,
            "name": character.name,
            "outline_character_id": character.outline_character_id,
            "outfit_variant_id": character.outfit_variant_id,
        } for character in sorted(page.visual_characters, key=lambda item: item.character_key)],
    }
