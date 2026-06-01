from datetime import datetime

from pydantic import BaseModel, Field


class ComfyWorkflowPresetRequest(BaseModel):
    """创建或更新 ComfyUI workflow 配置的请求体。"""

    name: str
    workflow_json: str
    positive_node_id: str
    positive_input_name: str = "text"
    description: str | None = None
    is_default: bool = False
    negative_node_id: str | None = None
    negative_input_name: str | None = None
    seed_node_id: str | None = None
    seed_input_name: str | None = None


class ComfyWorkflowPresetResponse(BaseModel):
    """ComfyUI workflow 配置响应体。"""

    id: int
    name: str
    description: str | None
    workflow_json: str
    is_default: bool
    positive_node_id: str
    positive_input_name: str
    negative_node_id: str | None
    negative_input_name: str | None
    seed_node_id: str | None
    seed_input_name: str | None
    created_at: datetime
    updated_at: datetime


class ComfyWorkflowPresetListResponse(BaseModel):
    """ComfyUI workflow 配置列表响应体。"""

    items: list[ComfyWorkflowPresetResponse]


class ComicImageResponse(BaseModel):
    """生成图片响应体。"""

    id: int
    page_id: int
    image_url: str | None
    local_path: str | None
    seed: int | None
    workflow_name: str | None
    prompt: str | None
    negative_prompt: str | None
    score: float | None
    is_selected: bool
    created_at: datetime


class ImageGenerationPageResponse(BaseModel):
    """图片生成页面列表中的单页状态。"""

    page_id: int
    page_no: int
    image_prompt: str | None
    status: str
    selected_image_id: int | None
    images: list[ComicImageResponse]


class ImageGenerationPageListResponse(BaseModel):
    """脚本任务下可生成图片页面的响应。"""

    task_id: int
    project_id: int
    items: list[ImageGenerationPageResponse]


class GenerateImagesRequest(BaseModel):
    """批量或单页图片生成请求体。"""

    workflow_preset_id: int = Field(gt=0)
    poll_interval_seconds: float = Field(default=2.0, ge=0.5, le=20)
    candidates_per_page: int = Field(default=1, ge=1, le=4)
    negative_prompt: str | None = None


class GenerationTaskResponse(BaseModel):
    """ComfyUI 生成任务响应体。"""

    id: int
    project_id: int
    page_id: int | None
    comfy_prompt_id: str | None
    status: str
    batch_size: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
