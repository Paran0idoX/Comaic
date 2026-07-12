from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import (
    GenerationMode,
    ImageGenerationProvider,
    ImagePromptType,
    SeedStrategy,
)


class ImageGenerationToolPresetRequest(BaseModel):
    """创建或更新生图工具配置的请求体。"""

    name: str
    provider: ImageGenerationProvider = ImageGenerationProvider.COMFYUI
    prompt_type: ImagePromptType = ImagePromptType.NATURAL_LANGUAGE
    description: str | None = None
    is_default: bool = False
    capabilities: dict = Field(
        default_factory=lambda: {"features": ["txt2img"], "limits": {}}
    )
    bindings: dict = Field(
        default_factory=lambda: {"schema_version": 1, "bindings": []}
    )
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
    provider: ImageGenerationProvider
    prompt_type: ImagePromptType
    description: str | None
    is_default: bool
    capabilities: dict
    bindings: dict
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
    generation_run_id: int | None
    image_url: str | None
    local_path: str | None
    seed: int | None
    workflow_name: str | None
    prompt: str | None
    negative_prompt: str | None
    score: float | None
    sha256: str | None
    width: int | None
    height: int | None
    is_selected: bool
    created_at: datetime


class ImageGenerationPageResponse(BaseModel):
    """图片生成页面列表中的单页状态。"""

    page_id: int
    page_no: int
    prompt_type: ImagePromptType | None
    positive_prompt: str | None
    status: str
    selected_image_id: int | None
    latest_spec_id: int | None = None
    spec_warnings: list[dict] = Field(default_factory=list)
    completed_candidates: int = 0
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
    wait_timeout_seconds: float = Field(default=600.0, ge=30, le=3600)
    candidates_per_page: int = Field(default=1, ge=1, le=4)
    generation_mode: GenerationMode = GenerationMode.PREVIEW
    seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE

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


class GenerationRunResponse(BaseModel):
    """单候选生成溯源响应；JSON 快照保持原始结构。"""

    id: int
    generation_task_id: int
    page_id: int
    image_spec_id: int
    tool_preset_id: int
    provider: ImageGenerationProvider
    prompt_type: ImagePromptType
    candidate_index: int
    seed: int | None
    seed_applied: bool
    seed_strategy: str
    generation_mode: str
    status: str
    external_request_id: str | None
    workflow: dict | None
    workflow_hash: str | None
    bindings: dict
    resolved_assets: list
    degradations: list
    applied_spec: dict
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
