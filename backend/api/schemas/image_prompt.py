from datetime import datetime

from pydantic import BaseModel, Field


class ImagePromptPresetRequest(BaseModel):
    """创建或更新图片 Prompt 配置的请求体。"""

    name: str
    kind: str
    content: str
    description: str | None = None
    is_default: bool = False


class ImagePromptPresetResponse(BaseModel):
    """图片 Prompt 配置响应体。"""

    id: int
    name: str
    description: str | None
    kind: str
    content: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ImagePromptPresetListResponse(BaseModel):
    """图片 Prompt 配置列表响应体。"""

    items: list[ImagePromptPresetResponse]


class GenerateImagePromptsRequest(BaseModel):
    """按脚本任务生成图片 Prompt 的请求体。"""

    system_prompt_preset_id: int = Field(gt=0)
    concurrency: int = Field(default=20, ge=1, le=50)


class ImagePromptGenerationItemResponse(BaseModel):
    """单页图片 Prompt 生成结果。"""

    page_id: int
    page_no: int
    image_prompt: str | None
    status: str
    scene_key: str | None = None
    character_keys: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None


class GenerateImagePromptsResponse(BaseModel):
    """脚本任务图片 Prompt 批量生成结果。"""

    task_id: int
    total: int
    succeeded: int
    failed: int
    items: list[ImagePromptGenerationItemResponse]
