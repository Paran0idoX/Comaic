from pydantic import BaseModel, Field


class SectionPlanItem(BaseModel):
    """故事节奏分段；页码必须使用整部漫画的全局绝对页码。"""

    section_no: int = Field(description="分段编号。", gt=0)
    page_start: int = Field(description="该分段起始全局页码。", gt=0)
    page_end: int = Field(description="该分段结束全局页码。", gt=0)
    title: str = Field(description="分段标题。")
    description: str = Field(description="该分段的大致内容。")


class StoryPacingResponse(BaseModel):
    """故事节奏划分 Agent 的结构化输出。"""

    sections: list[SectionPlanItem] = Field(description="覆盖全部目标页数的故事节奏分段。")


class PageScriptItem(BaseModel):
    """分页脚本编写子 Agent 输出的单页脚本。"""

    section_no: int = Field(description="当前页面所属分段编号。", gt=0)
    page_no: int = Field(description="整部漫画中的全局绝对页码。", gt=0)
    scene_key: str = Field(description="本页绑定的中心化场景 key，必须能在 scenes 中找到。")
    character_keys: list[str] = Field(
        default_factory=list,
        description="本页出现的中心化角色 key 列表，必须能在 characters 中找到。",
    )
    summary: str = Field(description="本页内容摘要。")
    characters: str = Field(description="本页出场人物、身份、表情和状态。")
    clothing: str = Field(description="本页人物服装、发型、配件和辨识特征。")
    scene: str = Field(description="本页地点、时间、环境元素和氛围。")
    composition: str = Field(description="本页整张漫画页的构图、视角、景别、光线和空间关系。")
    character_action: str = Field(description="本页人物核心动作、姿态、交互和动态。")
    dialogue: str = Field(description="本页需要出现的对白或旁白；无文字时写“无”。")
    is_revision: bool = Field(default=False, description="是否为监督意见后的修订脚本。")
    revision_note: str = Field(default="", description="修订脚本对应的监督校正意见。")


class PageScriptWriterResponse(BaseModel):
    """分页脚本编写子 Agent 的结构化输出。"""

    pages: list[PageScriptItem] = Field(description="本次生成或修订的页面脚本列表。")


class ScriptSceneItem(BaseModel):
    """当前脚本任务内的中心化场景设定。"""

    scene_key: str = Field(description="稳定场景 key，同一场景跨页必须复用。")
    name: str = Field(description="场景名称。")
    location_type: str = Field(description="地点类型。")
    time_of_day: str = Field(description="时间段。")
    lighting: str = Field(description="固定光线设定。")
    weather: str = Field(description="天气或空气状态。")
    environment_details: str = Field(description="稳定环境细节。")
    color_palette: str = Field(description="场景主色调。")
    visual_anchors: str = Field(description="跨页必须保留的视觉锚点。")
    negative_constraints: str = Field(description="同场景禁止出现或禁止改变的元素。")


class ScriptCharacterItem(BaseModel):
    """当前分段内的角色细化设定。"""

    character_key: str = Field(description="稳定角色 key，必须优先复用大纲角色基准中的 key。")
    name: str = Field(description="角色名称。")
    section_role: str = Field(description="该角色在当前分段中的叙事功能或状态。")
    current_hairstyle: str = Field(description="当前分段内的发型；未变化时沿用大纲默认值。")
    current_clothing: str = Field(description="当前分段内的服装；未变化时沿用大纲默认值。")
    current_accessories: str = Field(description="当前分段内的配件；未变化时沿用大纲默认值。")
    current_state: str = Field(description="当前分段内的身体状态、伤痕、疲惫程度等。")
    emotion: str = Field(description="当前分段的主要情绪状态。")
    temporary_changes: str = Field(description="只在当前分段出现的临时变化；没有则写“无”。")
    visual_anchors: str = Field(description="当前分段必须保留的角色视觉锚点，不能违背大纲基准。")
    negative_constraints: str = Field(description="当前分段禁止改变或禁止出现的元素。")


class ScriptReviewItem(BaseModel):
    """监督子 Agent 针对单页脚本输出的审查意见。"""

    page_no: int = Field(description="被审查的全局绝对页码。", gt=0)
    passed: bool = Field(description="该页脚本是否通过。")
    summary: str = Field(description="该页审查结论摘要。")
    revision_suggestions: list[str] = Field(
        default_factory=list,
        description="该页需要修改的具体意见；通过时可以为空。",
    )


class ScriptSupervisorResponse(BaseModel):
    """监督子 Agent 的结构化输出。"""

    passed: bool = Field(description="本轮审查整体是否通过。")
    reviews: list[ScriptReviewItem] = Field(description="按单页组织的结构化审查意见列表。")


class ScriptDeepAgentResponse(BaseModel):
    """分页脚本主 Agent 的最终结构化输出，避免主 Agent 用自然语言收尾。"""

    scenes: list[ScriptSceneItem] = Field(
        default_factory=list,
        description="本轮涉及的中心化场景设定。",
    )
    characters: list[ScriptCharacterItem] = Field(
        default_factory=list,
        description="本轮当前分段涉及的角色细化设定。",
    )
    reviews: list[ScriptReviewItem] = Field(
        default_factory=list,
        description="本轮最终审查结果。",
    )
    pages: list[PageScriptItem] = Field(
        default_factory=list,
        description="本轮最终生成或修订的页面脚本。",
    )
