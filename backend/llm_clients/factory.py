import os
import json
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from backend.models.comic import LLMConfig
from backend.models.database import SessionLocal
from backend.models.enums import LLMProvider
from backend.repositories.comic_repository import ComicRepository


load_dotenv()

ThinkingType = Literal["enabled", "disabled"]


@dataclass(frozen=True)
class LLMConfigInput:
    """创建临时模型实例所需的配置快照，避免测试连接时必须先落库。"""

    provider: LLMProvider
    base_url: str
    model: str
    api_key: str | None


def get_thinking_chat_model() -> ChatOpenAI:
    """读取当前配置并创建适合大纲阶段的 ChatModel。"""

    return create_chat_model_from_active_config(thinking_type="enabled")


def get_tool_chat_model() -> ChatOpenAI:
    """读取当前配置并创建适合工具调用/结构化输出阶段的 ChatModel。"""

    return create_chat_model_from_active_config(thinking_type="disabled")


def create_chat_model_from_active_config(*, thinking_type: ThinkingType = "disabled") -> ChatOpenAI:
    """从 SQLite 当前 active 配置创建模型；保存设置后后续新 Agent 会自动使用新配置。"""

    with SessionLocal() as session:
        repository = ComicRepository(session)
        ensure_llm_configs(repository)
        config = repository.get_active_llm_config()
        if config is None:
            raise ValueError("LLMConfig not found.")
        return create_chat_model(
            LLMConfigInput(
                provider=config.provider,
                base_url=config.base_url,
                model=config.default_model,
                api_key=config.api_key,
            ),
            thinking_type=thinking_type,
        )


def create_chat_model(config: LLMConfigInput, *, thinking_type: ThinkingType = "disabled") -> ChatOpenAI:
    """创建 OpenAI 兼容 ChatModel；DeepSeek 地址下按阶段附加 thinking 参数。"""

    if config.provider != LLMProvider.OPENAI_COMPATIBLE:
        raise ValueError(f"Unsupported LLM provider: {config.provider.value}")
    base_url = config.base_url.strip()
    model = config.model.strip()
    api_key = (config.api_key or "").strip()
    if not base_url:
        raise ValueError("LLMConfig base_url cannot be empty.")
    if not model:
        raise ValueError("LLMConfig model cannot be empty.")
    if not api_key:
        raise ValueError("LLMConfig API key is missing.")

    kwargs = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }
    if "deepseek.com" in base_url.lower():
        kwargs["extra_body"] = {"thinking": {"type": thinking_type}}
    return ChatOpenAI(**kwargs)


def ensure_llm_configs(repository: ComicRepository) -> list[LLMConfig]:
    """确保数据库里至少有一条 LLM 配置；首次使用时从 .env 初始化。"""

    configs = repository.list_llm_configs()
    if configs:
        return configs
    default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    config = repository.create_llm_config(
        name="Default DeepSeek",
        provider=LLMProvider.OPENAI_COMPATIBLE,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip(),
        model_names=json.dumps([default_model], ensure_ascii=False),
        default_model=default_model,
        api_key=(os.getenv("DEEPSEEK_API_KEY") or "").strip() or None,
        is_active=True,
    )
    return [config]
