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


class ScriptPageResponse(BaseModel):
    """页面脚本响应体。"""

    id: int
    project_id: int
    page_no: int
    script: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SinglePageScriptResponse(BaseModel):
    """单页生成完成后的响应体。"""

    task_id: int
    page_id: int
    page_no: int
    script: str
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
