from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import (
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
)


CHARACTER_EVENT_TYPES = {
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
SCENE_EVENT_TYPES = {
    ContinuityEventType.SET_LIGHT_STATE,
    ContinuityEventType.SET_DOOR_STATE,
    ContinuityEventType.SET_OBJECT_STATE,
    ContinuityEventType.BREAK_OBJECT,
    ContinuityEventType.SET_WEATHER,
    ContinuityEventType.ADVANCE_TIME,
}
FORBIDDEN_EVENT_PAYLOAD_KEYS = {
    "identity",
    "appearance",
    "fixed_appearance",
    "eye_color",
    "height",
    "body_type",
    "scar_position",
    "visual_anchors",
    "character_visual_anchors",
    "character_negative_constraints",
    "assets",
}


class ContinuityEventItem(BaseModel):
    """LLM 提取的单个受控连续性事件。"""

    page_no: int = Field(gt=0)
    sequence_no: int = Field(gt=0)
    event_type: ContinuityEventType
    target_type: ContinuityTargetType
    target_key: str
    timing: ContinuityEventTiming = ContinuityEventTiming.AFTER_PAGE
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_contract(self):
        """在结构化重试阶段拦截目标类型和关键 payload 缺失。"""

        if self.event_type in CHARACTER_EVENT_TYPES:
            expected_target = ContinuityTargetType.CHARACTER
        elif self.event_type in SCENE_EVENT_TYPES:
            expected_target = ContinuityTargetType.SCENE
        else:  # pragma: no cover - 枚举新增后必须显式归类
            raise ValueError(f"unsupported continuity event type: {self.event_type.value}")
        if self.target_type != expected_target:
            raise ValueError(
                f"{self.event_type.value} requires target_type={expected_target.value}"
            )
        forbidden = FORBIDDEN_EVENT_PAYLOAD_KEYS & set(self.payload)
        if forbidden:
            raise ValueError(
                f"continuity event cannot modify protected fields: {sorted(forbidden)}"
            )

        def present(key: str) -> bool:
            value = self.payload.get(key)
            return value is not None and (not isinstance(value, str) or bool(value.strip()))

        required_keys = {
            ContinuityEventType.SET_HAIRSTYLE: ("value",),
            ContinuityEventType.SET_GARMENT_STATE: ("garment_key", "value"),
            ContinuityEventType.SET_CLOTHING_CONDITION: ("condition_key",),
            ContinuityEventType.SET_CHARACTER_CONDITION: ("condition_key", "value"),
            ContinuityEventType.PICK_UP_PROP: ("prop_key",),
            ContinuityEventType.DROP_PROP: ("prop_key",),
            ContinuityEventType.TRANSFER_PROP: ("prop_key", "to_character_key"),
            ContinuityEventType.SET_LIGHT_STATE: ("value",),
            ContinuityEventType.SET_DOOR_STATE: ("door_key", "value"),
            ContinuityEventType.SET_OBJECT_STATE: ("object_key", "value"),
            ContinuityEventType.BREAK_OBJECT: ("object_key",),
            ContinuityEventType.SET_WEATHER: ("value",),
            ContinuityEventType.ADVANCE_TIME: ("value",),
        }
        missing = [key for key in required_keys.get(self.event_type, ()) if not present(key)]
        if missing:
            raise ValueError(
                f"{self.event_type.value} payload is missing: {', '.join(missing)}"
            )
        if self.event_type == ContinuityEventType.SET_OUTFIT and not any(
            present(key) for key in ("outfit_variant_id", "outfit_key", "description")
        ):
            raise ValueError("set_outfit requires an outfit id, key, or description")
        if self.event_type == ContinuityEventType.SET_ACCESSORY:
            missing = [key for key in ("accessory_key", "value") if not present(key)]
            if missing:
                raise ValueError(
                    "set_accessory requires a stable accessory_key and value"
                )
        return self


class ContinuityEventResponse(BaseModel):
    events: list[ContinuityEventItem] = Field(default_factory=list)


class NormalizedBox(BaseModel):
    """0-1 归一化主体区域。"""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("subject region must remain inside the normalized canvas")
        return self


class CameraPlan(BaseModel):
    shot_type: str
    angle: str
    azimuth: float | None = None
    elevation: float | None = None
    lens_mm: float | None = Field(default=None, gt=0)
    camera_height: str = ""
    depth_of_field: str = ""


class SubjectShotPlan(BaseModel):
    character_key: str
    action: str
    pose: str
    expression: str
    gaze: str = ""
    orientation: str = ""
    region: NormalizedBox
    depth_order: int = Field(ge=0)
    control_requirements: list[str] = Field(default_factory=list)


class SceneShotPlan(BaseModel):
    framing_notes: str
    focal_point: str
    negative_space: str = ""
    control_requirements: list[str] = Field(default_factory=list)


class ShotPlanResponse(BaseModel):
    """ShotPlanner 的模型无关结构化输出。"""

    camera: CameraPlan
    subjects: list[SubjectShotPlan] = Field(default_factory=list)
    scene: SceneShotPlan
    render_text: bool = False

    @model_validator(mode="after")
    def reject_model_drawn_text(self):
        if self.render_text:
            raise ValueError("P0 shot plans must set render_text=false")
        keys = [subject.character_key for subject in self.subjects]
        if len(keys) != len(set(keys)):
            raise ValueError("shot plan contains duplicate character_key")
        return self
