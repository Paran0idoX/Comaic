from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import ImageGenerationToolKind


class ImageGenerationToolPresetRequest(BaseModel):
    """创建或更新生图工具配置的请求体。"""

    name: str
    kind: ImageGenerationToolKind = ImageGenerationToolKind.COMFYUI
    description: str | None = None
    is_default: bool = False
    comfy_base_url: str | None = None
    workflow_json: str | None = None
    positive_node_id: str | None = None
    positive_input_name: str | None = "text"
    negative_node_id: str | None = None
    negative_input_name: str | None = None
    seed_node_id: str | None = None
    seed_input_name: str | None = None
    api_base_url: str | None = None
    endpoint_path: str | None = "/images/generations"
    api_key: str | None = None
    model: str | None = None
    size: str | None = "1024x1024"
    response_format: str | None = "b64_json"
    seed_field_name: str | None = None
    negative_prompt_field_name: str | None = None
    extra_body_json: str | None = None


class ImageGenerationToolPresetResponse(BaseModel):
    """生图工具配置响应体。"""

    id: int
    name: str
    kind: ImageGenerationToolKind
    description: str | None
    is_default: bool
    comfy_base_url: str | None
    workflow_json: str | None
    positive_node_id: str | None
    positive_input_name: str | None
    negative_node_id: str | None
    negative_input_name: str | None
    seed_node_id: str | None
    seed_input_name: str | None
    api_base_url: str | None
    endpoint_path: str | None
    api_key: str | None
    model: str | None
    size: str | None
    response_format: str | None
    seed_field_name: str | None
    negative_prompt_field_name: str | None
    extra_body_json: str | None
    created_at: datetime
    updated_at: datetime


class ImageGenerationToolPresetListResponse(BaseModel):
    """生图工具配置列表响应体。"""

    items: list[ImageGenerationToolPresetResponse]


ComfyWorkflowPresetRequest = ImageGenerationToolPresetRequest
ComfyWorkflowPresetResponse = ImageGenerationToolPresetResponse
ComfyWorkflowPresetListResponse = ImageGenerationToolPresetListResponse


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

    tool_preset_id: int | None = Field(default=None, gt=0)
    workflow_preset_id: int | None = Field(default=None, gt=0)
    poll_interval_seconds: float = Field(default=2.0, ge=0.5, le=20)
    candidates_per_page: int = Field(default=1, ge=1, le=4)
    negative_prompt: str | None = None

    @model_validator(mode="after")
    def validate_preset_id(self):
        """新字段 tool_preset_id 优先，兼容旧 workflow_preset_id。"""

        if self.tool_preset_id is None and self.workflow_preset_id is None:
            raise ValueError("tool_preset_id is required")
        return self

    @property
    def effective_tool_preset_id(self) -> int:
        """读取实际使用的工具配置 id。"""

        return self.tool_preset_id or self.workflow_preset_id or 0


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
