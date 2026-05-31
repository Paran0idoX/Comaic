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
    page_goal: str = Field(description="本页叙事目标。")
    scene: str = Field(description="本页整张漫画页的画面内容。")
    character_action: str = Field(description="本页最核心的人物动作或状态。")
    dialogue_or_caption: str = Field(description="本页需要出现的对白或旁白。")
    script: str = Field(description="可直接展示给用户的完整中文页面脚本。")
    is_revision: bool = Field(default=False, description="是否为监督意见后的修订脚本。")
    revision_note: str = Field(default="", description="修订脚本对应的监督校正意见。")


class PageScriptWriterResponse(BaseModel):
    """分页脚本编写子 Agent 的结构化输出。"""

    pages: list[PageScriptItem] = Field(description="本次生成或修订的页面脚本列表。")


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

    reviews: list[ScriptReviewItem] = Field(
        default_factory=list,
        description="本轮最终审查结果。",
    )
    pages: list[PageScriptItem] = Field(
        default_factory=list,
        description="本轮最终生成或修订的页面脚本。",
    )
