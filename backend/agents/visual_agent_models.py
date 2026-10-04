from pydantic import BaseModel, Field, model_validator

from backend.models.enums import (
    SubjectReferenceFraming,
    SubjectReferenceView,
)


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
    action: str = Field(description="本页选定瞬间正在发生的可见动作，可有动势；不能串联先后动作或动作前后的状态。")
    pose: str = Field(description="与 action 同一瞬间的身体姿态、接触点和持物关系。")
    expression: str = Field(description="与 action 同一瞬间的表情，不描述先后变化。")
    visible_state: str = Field(
        default="",
        description="仅此页脚本明确、在当前镜头可见的人物或衣物临时状态，如湿污、破损、受伤或卷袖；不复述固定外貌和基础造型，不从前页推演。没有变化时为空。",
    )
    gaze: str = Field(default="", description="选定瞬间的视线方向或目标，不描述视线转移过程。")
    orientation: str = ""
    region: NormalizedBox
    depth_order: int = Field(ge=0)
    control_requirements: list[str] = Field(default_factory=list)
    reference_view: SubjectReferenceView = SubjectReferenceView.UNKNOWN
    reference_framing: SubjectReferenceFraming = SubjectReferenceFraming.UNKNOWN
    visible_prop_keys: list[str] = Field(
        default_factory=list,
        description="该人物处实际可见且属于输入 prop_catalog 的物品 key；每个 key 在全部 subject/scene 中最多出现一次。目录外物品只用 action/pose 描述。",
    )


class SceneShotPlan(BaseModel):
    framing_notes: str = Field(
        description="本页当前瞬间完整的可见环境描述：固定场景提供空间布局、地标与材质，本页 scene_conditions 提供时段、天气、光照与氛围，脚本提供普通剧情物的当前位置与容器遮挡；不列出隐藏目录物，不照搬参考图的环境条件。这是最终 Prompt 的场景描述来源。",
    )
    focal_point: str
    negative_space: str = ""
    control_requirements: list[str] = Field(default_factory=list)
    visible_prop_keys: list[str] = Field(
        default_factory=list,
        description="场景中实际可见且属于输入 prop_catalog 的物品 key；每个 key 在全部 subject/scene 中最多出现一次。目录外物品只用 framing_notes 描述。",
    )
    background_visible: bool = True


class PromptLanguageResponse(BaseModel):
    """一次转换四个组件，三种 Prompt 共用同一译文。"""

    tag_text: str = Field(min_length=1)
    natural_language_text: str = Field(min_length=1)
    negative_tag_text: str = Field(min_length=1)
    negative_natural_language_text: str = Field(min_length=1)


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
