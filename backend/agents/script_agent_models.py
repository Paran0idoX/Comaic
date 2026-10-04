from pydantic import BaseModel, ConfigDict, Field
from backend.models.scene_conditions import SceneConditions


class ScriptSceneItem(BaseModel):
    """当前脚本任务内的中心化场景设定。"""

    model_config = ConfigDict(extra="forbid")
    scene_key: str = Field(description="固定地点 key，同一地点跨分段复用，不包含天气、时段、光照或氛围。")
    name: str = Field(description="固定地点名称，不包含天气、时段、光照或氛围。")
    location_type: str = Field(description="地点类型。")
    reference_subject_key: str | None = Field(default=None, description="复用输入目录的准确 key；新地点返回 null。")
    environment_details: str = Field(description="建筑、空间布局、材质和固定陈设，不包含剧情环境条件或临时物件状态。")
    color_palette: str = Field(description="建筑、材质、固定陈设的固有颜色，不描述光照色调。")
    negative_constraints: str = Field(description="仅限制地点建筑、布局等固定身份；不把编写范围说明写成禁止人物、剧情物品、天气或光照的画面禁令。没有固定禁止项时为空。")


class ScriptCharacterItem(BaseModel):
    """当前分段内的角色细化设定。"""

    character_key: str = Field(description="稳定角色 key，必须优先复用大纲角色基准中的 key。")
    name: str = Field(description="角色名称。")
    section_role: str = Field(description="该角色在当前分段中的叙事功能或状态。")
    current_hairstyle: str = Field(
        description="当前分段的基础发型版本；未改变发型时原样沿用默认值，湿乱等写 temporary_changes。"
    )
    current_clothing: str = Field(
        description="当前分段的基础服装版本；未换装时原样沿用大纲默认值，湿污破损等写 temporary_changes。"
    )
    current_accessories: str = Field(
        description="当前分段的基础配件版本；手持/收起等位置状态写 temporary_changes。"
    )
    current_state: str = Field(description="当前分段内的身体状态、伤痕、疲惫程度等。")
    emotion: str = Field(description="当前分段的主要情绪状态。")
    temporary_changes: str = Field(description="只在当前分段出现的临时变化；没有则写“无”。")
    negative_constraints: str = Field(description="当前分段禁止改变或禁止出现的元素。")


class SectionPagePlanItem(BaseModel):
    """逐页锁定可用地点和核心剧情，提前发现缺少承载地点的节奏规划。"""

    model_config = ConfigDict(extra="forbid")
    page_no: int = Field(gt=0, description="整部漫画中的全局绝对页码。")
    scene_key: str = Field(description="本段 scenes 中能够承载该页画面的地点 key。")
    beat: str = Field(description="该页一个瞬间能够呈现的核心剧情落点，与 scene_key 的地点一致，不写先后动作链。")


class SectionPlanItem(BaseModel):
    """故事节奏分段；同时锁定该分段的视觉设定。"""

    section_no: int = Field(description="分段编号。", gt=0)
    page_start: int = Field(description="该分段起始全局页码。", gt=0)
    page_end: int = Field(description="该分段结束全局页码。", gt=0)
    title: str = Field(description="分段标题。")
    description: str = Field(description="该分段的剧情功能、主要内容和按页推进的关键落点；每页对应一个可独立成画的瞬间，不把先后动作压在同一页。")
    page_plan: list[SectionPagePlanItem] = Field(description="按页列出 scene_key 和核心剧情落点，完整覆盖本段页码；先补齐实际需要的地点，再锁定规划。")
    scenes: list[ScriptSceneItem] = Field(description="该分段涉及的中心化场景设定。")
    characters: list[ScriptCharacterItem] = Field(description="该分段涉及的角色细化设定。")


class StoryPacingResponse(BaseModel):
    """故事节奏划分 Agent 的结构化输出。"""

    sections: list[SectionPlanItem] = Field(description="覆盖全部目标页数的故事节奏分段。")


class PageScriptItem(BaseModel):
    """单页脚本的各画面字段描述同一瞬间，允许动作但不串联先后动作。"""

    section_no: int = Field(description="当前页面所属分段编号。", gt=0)
    page_no: int = Field(description="整部漫画中的全局绝对页码。", gt=0)
    scene_key: str = Field(description="本页绑定的中心化场景 key，必须能在 scenes 中找到。")
    scene_conditions: SceneConditions | None = Field(default=None, description="本页实际时段、天气、光照、氛围；新脚本必须填写对象，未指定项为空字符串。")
    character_keys: list[str] = Field(
        default_factory=list,
        description="本页出现的中心化角色 key 列表，必须能在 characters 中找到。",
    )
    summary: str = Field(description="本页选定瞬间的可见画面与核心剧情落点，不串联先后动作，不写创作说明。")
    characters: str = Field(description="选定瞬间的出场人物、身份、表情和状态，不描述先后变化。")
    clothing: str = Field(description="选定瞬间实际穿戴的服装、发型、配件、辨识特征和临时状态，不描述穿脱过程。")
    scene: str = Field(description="选定瞬间的单一地点、时间、环境元素、氛围和物件当前状态，不描述变化过程。")
    composition: str = Field(description="选定瞬间整张漫画页的统一构图、视角、景别、光线和空间关系，不切换镜头或时刻。")
    character_action: str = Field(description="选定瞬间各人物可同时成立的动作、姿态、交互、接触点和动势，不能包含先后动作或动作前后状态。")
    dialogue: str = Field(description="与选定瞬间对应的少量对白或旁白，不压入完整多轮对话或动作过程；无文字时写“无”。")
    is_revision: bool = Field(default=False, description="是否为监督意见后的修订脚本。")
    revision_note: str = Field(default="", description="修订脚本对应的监督校正意见。")


class PageScriptWriterResponse(BaseModel):
    """分页脚本编写子 Agent 的结构化输出。"""

    pages: list[PageScriptItem] = Field(description="本次生成或修订的页面脚本列表。")


class ScriptReviewItem(BaseModel):
    """监督子 Agent 针对单页脚本输出的审查意见。"""

    page_no: int = Field(description="被审查的全局绝对页码。", gt=0)
    passed: bool = Field(description="没有明确阻断画面成立、固定设定或核心剧情的错误时为 true；措辞优化、可选细节和假设风险不能作为不通过依据。")
    summary: str = Field(description="简洁的审查结论；不通过时指出具体字段、原文与阻断错误，不罗列已经正确的内容或假设问题。")
    revision_suggestions: list[str] = Field(
        default_factory=list,
        description="只列出消除明确阻断错误的最小修改；通过时为空，不把编辑偏好作为重试要求。",
    )


class ScriptSupervisorResponse(BaseModel):
    """监督子 Agent 的结构化输出。"""

    reviews: list[ScriptReviewItem] = Field(description="按单页组织的结构化审查意见列表。")
