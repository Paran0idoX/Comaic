from datetime import datetime

from pydantic import BaseModel, Field


class GenerateSinglePageScriptRequest(BaseModel):
    """单页脚本生成请求体。"""

    project_id: int = Field(gt=0)
    page_no: int = Field(gt=0)
    total_pages: int = Field(gt=0)
    outline_version_id: int | None = Field(default=None, gt=0)
    user_requirement: str | None = None


class GenerateBatchScriptRequest(BaseModel):
    """批量脚本生成请求体。"""

    project_id: int = Field(gt=0)
    total_pages: int = Field(gt=0)
    outline_version_id: int | None = Field(default=None, gt=0)
    user_requirement: str | None = None


class ContinueBatchScriptRequest(BaseModel):
    """继续批量脚本生成请求体。"""

    user_requirement: str | None = None


class CreatePageScriptRequest(BaseModel):
    """人工新增页面脚本请求体。"""

    page_no: int = Field(gt=0)
    task_id: int | None = Field(default=None, gt=0)
    summary: str
    characters: str
    clothing: str
    scene: str
    composition: str
    character_action: str
    dialogue: str


class UpdatePageScriptRequest(BaseModel):
    """人工更新页面脚本请求体。"""

    task_id: int | None = Field(default=None, gt=0)
    summary: str
    characters: str
    clothing: str
    scene: str
    composition: str
    character_action: str
    dialogue: str


class ScriptPageResponse(BaseModel):
    """页面脚本响应体。"""

    id: int
    project_id: int
    section_id: int | None = None
    section_no: int | None = None
    task_id: int | None = None
    scene_id: int | None = None
    scene_key: str | None = None
    character_keys: list[str] = Field(default_factory=list)
    page_no: int
    summary: str | None
    characters: str | None
    clothing: str | None
    scene: str | None
    composition: str | None
    character_action: str | None
    dialogue: str | None
    image_prompt: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ScriptSectionResponse(BaseModel):
    """脚本分段响应体。"""

    id: int
    task_id: int
    section_no: int
    page_start: int
    page_end: int
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    pages: list[ScriptPageResponse] = Field(default_factory=list)


class SinglePageScriptResponse(BaseModel):
    """单页生成完成后的响应体。"""

    task_id: int
    page_id: int
    page_no: int
    summary: str
    characters: str
    clothing: str
    scene: str
    composition: str
    character_action: str
    dialogue: str
    status: str


class ScriptTaskResponse(BaseModel):
    """分页脚本生成任务响应体。"""

    id: int
    project_id: int
    outline_version_id: int | None
    status: str
    mode: str
    total_pages: int
    target_page_no: int | None
    user_requirement: str | None
    section_plan: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ScriptPageListResponse(BaseModel):
    """项目页面脚本列表响应体。"""

    items: list[ScriptPageResponse]


class ScriptSectionListResponse(BaseModel):
    """脚本任务分段列表响应体。"""

    items: list[ScriptSectionResponse]


class ScriptSceneResponse(BaseModel):
    """脚本任务内的中心化场景设定响应体。"""

    id: int
    task_id: int
    scene_key: str
    name: str
    location_type: str
    time_of_day: str
    lighting: str
    weather: str
    environment_details: str
    color_palette: str
    visual_anchors: str
    negative_constraints: str
    created_at: datetime
    updated_at: datetime


class ScriptSceneListResponse(BaseModel):
    """脚本任务场景设定列表响应体。"""

    items: list[ScriptSceneResponse]


class ScriptCharacterResponse(BaseModel):
    """脚本分段内的角色细化设定响应体。"""

    id: int
    task_id: int | None
    section_id: int
    section_no: int | None = None
    outline_character_id: int | None = None
    character_key: str
    name: str
    section_role: str
    current_hairstyle: str
    current_clothing: str
    current_accessories: str
    current_state: str
    emotion: str
    temporary_changes: str
    visual_anchors: str
    negative_constraints: str
    outline_character: dict | None = None
    created_at: datetime
    updated_at: datetime


class ScriptCharacterListResponse(BaseModel):
    """脚本任务角色设定列表响应体。"""

    items: list[ScriptCharacterResponse]
