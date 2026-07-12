from collections import defaultdict
from copy import deepcopy
from typing import Any

from backend.models.enums import (
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
)


IMMUTABLE_PAYLOAD_KEYS = {
    "identity",
    "appearance",
    "fixed_appearance",
    "eye_color",
    "height",
    "body_type",
    "scar_position",
    "visual_anchors",
}


class VisualStateReducer:
    """把受控事件归约为逐页视觉状态；相同输入必须产生相同快照。"""

    VERSION = "1"

    def __init__(
        self,
        *,
        character_baselines: dict[str, dict[str, Any]],
        scene_baselines: dict[str, dict[str, Any]],
    ):
        self.character_baselines = deepcopy(character_baselines)
        self.scene_baselines = deepcopy(scene_baselines)

    def reduce(
        self,
        *,
        pages: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按 before→快照→after 的固定顺序生成全部页面状态。"""

        characters = deepcopy(self.character_baselines)
        scenes = deepcopy(self.scene_baselines)
        prop_owners: dict[str, str] = {}
        grouped: dict[tuple[int, ContinuityEventTiming], list[dict[str, Any]]] = defaultdict(list)
        page_nos = {int(page["page_no"]) for page in pages}
        for event in events:
            page_no = int(event["page_no"])
            if page_no not in page_nos:
                raise ValueError(f"continuity event references unknown page_no: {page_no}")
            timing = ContinuityEventTiming(event.get("timing", "after_page"))
            grouped[(page_no, timing)].append(event)
        for values in grouped.values():
            values.sort(key=lambda item: int(item.get("sequence_no", 0)))

        snapshots: list[dict[str, Any]] = []
        for page in sorted(pages, key=lambda item: int(item["page_no"])):
            page_no = int(page["page_no"])
            before_events = grouped[(page_no, ContinuityEventTiming.BEFORE_PAGE)]
            after_events = grouped[(page_no, ContinuityEventTiming.AFTER_PAGE)]
            for event in before_events:
                self._apply_event(event, characters, scenes, prop_owners)

            scene_key = str(page.get("scene_key", "")).strip()
            if scene_key not in scenes:
                raise ValueError(f"page {page_no} references unknown scene_key: {scene_key}")
            page_character_keys = [str(value) for value in page.get("character_keys", [])]
            unknown_characters = set(page_character_keys) - set(characters)
            if unknown_characters:
                raise ValueError(
                    f"page {page_no} references unknown characters: {sorted(unknown_characters)}"
                )
            snapshots.append(
                {
                    "schema_version": 1,
                    "page_id": int(page["page_id"]),
                    "page_no": page_no,
                    "characters": [deepcopy(characters[key]) for key in page_character_keys],
                    "scene": deepcopy(scenes[scene_key]),
                    # ShotPlanner 可以看到本页发生的转变，但不能把它写回状态。
                    "page_events": deepcopy(before_events + after_events),
                }
            )

            for event in after_events:
                self._apply_event(event, characters, scenes, prop_owners)
        return snapshots

    def _apply_event(
        self,
        event: dict[str, Any],
        characters: dict[str, dict[str, Any]],
        scenes: dict[str, dict[str, Any]],
        prop_owners: dict[str, str],
    ) -> None:
        event_type = ContinuityEventType(event["event_type"])
        target_type = ContinuityTargetType(event["target_type"])
        target_key = str(event.get("target_key", "")).strip()
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("continuity event payload must be an object")
        forbidden = IMMUTABLE_PAYLOAD_KEYS & set(payload)
        if forbidden:
            raise ValueError(
                f"continuity event cannot modify immutable fields: {sorted(forbidden)}"
            )

        character_events = {
            ContinuityEventType.SET_HAIRSTYLE,
            ContinuityEventType.SET_OUTFIT,
            ContinuityEventType.SET_ACCESSORY,
            ContinuityEventType.SET_GARMENT_STATE,
            ContinuityEventType.SET_CLOTHING_CONDITION,
            ContinuityEventType.SET_CHARACTER_CONDITION,
            ContinuityEventType.PICK_UP_PROP,
            ContinuityEventType.DROP_PROP,
            ContinuityEventType.TRANSFER_PROP,
        }
        scene_events = {
            ContinuityEventType.SET_LIGHT_STATE,
            ContinuityEventType.SET_DOOR_STATE,
            ContinuityEventType.SET_OBJECT_STATE,
            ContinuityEventType.BREAK_OBJECT,
            ContinuityEventType.SET_WEATHER,
            ContinuityEventType.ADVANCE_TIME,
        }
        if event_type in character_events:
            if target_type != ContinuityTargetType.CHARACTER or target_key not in characters:
                raise ValueError(f"character continuity target not found: {target_key}")
            self._apply_character_event(
                event_type,
                target_key,
                payload,
                characters,
                prop_owners,
            )
            return
        if event_type in scene_events:
            if target_type != ContinuityTargetType.SCENE or target_key not in scenes:
                raise ValueError(f"scene continuity target not found: {target_key}")
            self._apply_scene_event(event_type, payload, scenes[target_key])
            return
        raise ValueError(f"unsupported continuity event: {event_type.value}")

    @staticmethod
    def _apply_character_event(
        event_type: ContinuityEventType,
        target_key: str,
        payload: dict[str, Any],
        characters: dict[str, dict[str, Any]],
        prop_owners: dict[str, str],
    ) -> None:
        state = characters[target_key]
        if event_type == ContinuityEventType.SET_HAIRSTYLE:
            state["hairstyle"] = str(payload.get("value", "")).strip()
            return
        if event_type == ContinuityEventType.SET_OUTFIT:
            state["outfit"] = {
                "variant_id": payload.get("outfit_variant_id"),
                "key": str(payload.get("outfit_key", "")).strip(),
                "name": str(payload.get("name", "")).strip(),
                "description": str(payload.get("description", "")).strip(),
                "garment_components": list(payload.get("garment_components", [])),
                "layer_order": list(payload.get("layer_order", [])),
                "colors": list(payload.get("colors", [])),
                "materials": list(payload.get("materials", [])),
                "patterns": list(payload.get("patterns", [])),
                "accessories": list(payload.get("accessories", [])),
                "trigger_tokens": list(payload.get("trigger_tokens", [])),
                "negative_constraints": str(
                    payload.get("negative_constraints", "")
                ).strip(),
                "garment_states": {},
                "conditions": {},
                "assets": list(payload.get("assets", [])),
            }
            if "character_negative_constraints" in payload:
                state["negative_constraints"] = str(
                    payload.get("character_negative_constraints", "")
                ).strip()
            if "character_visual_anchors" in payload:
                state["visual_anchors"] = str(
                    payload.get("character_visual_anchors", "")
                ).strip()
            return
        if event_type == ContinuityEventType.SET_ACCESSORY:
            accessory_key = str(payload.get("accessory_key") or payload.get("value") or "").strip()
            if not accessory_key:
                raise ValueError("set_accessory requires accessory_key")
            if accessory_key == "__description__":
                state.setdefault("accessories", {})["description"] = str(
                    payload.get("value", "")
                ).strip()
                return
            state.setdefault("accessories", {}).setdefault("states", {})[accessory_key] = str(
                payload.get("state", "present")
            )
            return
        if event_type == ContinuityEventType.SET_GARMENT_STATE:
            garment_key = str(payload.get("garment_key", "")).strip()
            if not garment_key:
                raise ValueError("set_garment_state requires garment_key")
            state.setdefault("outfit", {}).setdefault("garment_states", {})[
                garment_key
            ] = payload.get("value")
            return
        if event_type == ContinuityEventType.SET_CLOTHING_CONDITION:
            condition_key = str(payload.get("condition_key", "")).strip()
            if not condition_key:
                raise ValueError("set_clothing_condition requires condition_key")
            state.setdefault("outfit", {}).setdefault("conditions", {})[
                condition_key
            ] = payload.get("value", True)
            return
        if event_type == ContinuityEventType.SET_CHARACTER_CONDITION:
            condition_key = str(payload.get("condition_key", "")).strip()
            if not condition_key:
                raise ValueError("set_character_condition requires condition_key")
            state.setdefault("conditions", {})[condition_key] = payload.get("value")
            return

        prop_key = str(payload.get("prop_key", "")).strip()
        if not prop_key:
            raise ValueError(f"{event_type.value} requires prop_key")
        held_props = state.setdefault("held_props", [])
        if event_type == ContinuityEventType.PICK_UP_PROP:
            current_owner = prop_owners.get(prop_key)
            if current_owner and current_owner != target_key:
                raise ValueError(
                    f"prop {prop_key} is already held by {current_owner}; use transfer_prop"
                )
            prop_owners[prop_key] = target_key
            if prop_key not in held_props:
                held_props.append(prop_key)
            held_props.sort()
            return
        if prop_owners.get(prop_key) != target_key or prop_key not in held_props:
            raise ValueError(f"character {target_key} does not hold prop {prop_key}")
        held_props.remove(prop_key)
        if event_type == ContinuityEventType.DROP_PROP:
            prop_owners.pop(prop_key, None)
            return
        to_character_key = str(payload.get("to_character_key", "")).strip()
        if to_character_key not in characters:
            raise ValueError(f"transfer target character not found: {to_character_key}")
        prop_owners[prop_key] = to_character_key
        receiver_props = characters[to_character_key].setdefault("held_props", [])
        if prop_key not in receiver_props:
            receiver_props.append(prop_key)
            receiver_props.sort()

    @staticmethod
    def _apply_scene_event(
        event_type: ContinuityEventType,
        payload: dict[str, Any],
        scene: dict[str, Any],
    ) -> None:
        if event_type == ContinuityEventType.SET_LIGHT_STATE:
            key = str(payload.get("light_key", "main_light")).strip()
            scene.setdefault("light_states", {})[key] = payload.get("value")
            return
        if event_type == ContinuityEventType.SET_DOOR_STATE:
            key = str(payload.get("door_key", "")).strip()
            if not key:
                raise ValueError("set_door_state requires door_key")
            scene.setdefault("object_states", {})[key] = payload.get("value")
            return
        if event_type in {
            ContinuityEventType.SET_OBJECT_STATE,
            ContinuityEventType.BREAK_OBJECT,
        }:
            key = str(payload.get("object_key", "")).strip()
            if not key:
                raise ValueError(f"{event_type.value} requires object_key")
            scene.setdefault("object_states", {})[key] = (
                "broken"
                if event_type == ContinuityEventType.BREAK_OBJECT
                else payload.get("value")
            )
            return
        if event_type == ContinuityEventType.SET_WEATHER:
            scene["weather"] = payload.get("value")
            return
        if event_type == ContinuityEventType.ADVANCE_TIME:
            scene["time"] = payload.get("value")
            return
