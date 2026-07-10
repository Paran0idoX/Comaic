from datetime import datetime

from pydantic import BaseModel, Field

from backend.models.enums import LLMProvider


class LLMConfigResponse(BaseModel):
    """单组模型 API 配置响应；本地 MVP 设置页允许回显明文 API Key。"""

    id: int
    name: str
    provider: LLMProvider
    base_url: str
    model_names: list[str]
    default_model: str
    api_key: str | None
    api_key_set: bool
    is_active: bool
    updated_at: datetime


class LLMConfigListResponse(BaseModel):
    """模型配置列表响应；active_config_id 表示当前实际使用的配置。"""

    items: list[LLMConfigResponse]
    active_config_id: int | None


class LLMProviderResponse(BaseModel):
    """设置页可选 LangChain Provider。"""

    value: LLMProvider
    label: str
    requires_base_url: bool
    model_prefixes: list[str] = Field(default_factory=list)


class CreateLLMConfigRequest(BaseModel):
    """新增模型 API 配置请求。"""

    name: str = Field(min_length=1, max_length=255)
    provider: LLMProvider = LLMProvider.OPENAI_COMPATIBLE
    base_url: str | None = Field(default=None, max_length=1024)
    model_names: list[str] = Field(min_length=1)
    default_model: str | None = None
    api_key: str | None = None
    is_active: bool = False


class UpdateLLMConfigRequest(BaseModel):
    """更新模型 API 配置请求；api_key 为空表示保留旧值。"""

    name: str = Field(min_length=1, max_length=255)
    provider: LLMProvider = LLMProvider.OPENAI_COMPATIBLE
    base_url: str | None = Field(default=None, max_length=1024)
    model_names: list[str] = Field(min_length=1)
    default_model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False


class TestLLMConfigRequest(BaseModel):
    """测试连接请求；可测试已保存配置，也可测试未保存表单配置。"""

    config_id: int | None = None
    provider: LLMProvider | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False


class TestLLMConfigResponse(BaseModel):
    """测试连接结果。"""

    ok: bool


class AppSettingsResponse(BaseModel):
    """应用全局设置响应。"""

    script_section_max_concurrency: int = Field(ge=1, le=20)


class UpdateAppSettingsRequest(BaseModel):
    """更新应用全局设置请求。"""

    script_section_max_concurrency: int = Field(ge=1, le=20)
