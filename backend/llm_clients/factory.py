import os
import json
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_cohere import ChatCohere
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_xai import ChatXAI

from backend.models.comic import LLMConfig
from backend.models.database import SessionLocal
from backend.models.enums import LLMProvider
from backend.repositories.comic_repository import ComicRepository


load_dotenv()


@dataclass(frozen=True)
class LLMConfigInput:
    """创建临时模型实例所需的配置快照，避免测试连接时必须先落库。"""

    provider: LLMProvider
    base_url: str | None
    model: str
    api_key: str | None
    thinking_enabled: bool | None = None


def get_thinking_chat_model() -> BaseChatModel:
    """读取当前配置并创建适合大纲阶段的 ChatModel。"""

    return create_chat_model_from_active_config(thinking_enabled=True)


def get_tool_chat_model() -> BaseChatModel:
    """读取当前配置并创建适合工具调用/结构化输出阶段的 ChatModel。"""

    return create_chat_model_from_active_config(thinking_enabled=False)


def create_chat_model_from_active_config(*, thinking_enabled: bool | None = None) -> BaseChatModel:
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
                thinking_enabled=thinking_enabled,
            )
        )


def create_chat_model(config: LLMConfigInput) -> BaseChatModel:
    """按设置页选择的 Provider 显式创建对应 ChatModel。"""

    base_url = (config.base_url or "").strip()
    model = config.model.strip()
    api_key = (config.api_key or "").strip()
    if not model:
        raise ValueError("LLMConfig model cannot be empty.")

    if config.provider == LLMProvider.OPENAI_COMPATIBLE:
        if not base_url:
            raise ValueError("LLMConfig base_url cannot be empty.")
        return ChatOpenAI(model=model, api_key=_required_api_key(api_key), base_url=base_url)

    if config.provider == LLMProvider.DEEPSEEK:
        return ChatDeepSeek(
            model=model,
            api_key=_required_api_key(api_key),
            **_deepseek_thinking_kwargs(config.thinking_enabled),
        )
    if config.provider == LLMProvider.ANTHROPIC:
        return ChatAnthropic(model_name=model, api_key=_required_api_key(api_key))
    if config.provider == LLMProvider.GOOGLE_GENAI:
        return ChatGoogleGenerativeAI(model=model, api_key=_required_api_key(api_key))
    if config.provider == LLMProvider.MISTRALAI:
        return ChatMistralAI(model_name=model, api_key=_required_api_key(api_key))
    if config.provider == LLMProvider.GROQ:
        return ChatGroq(model=model, api_key=_required_api_key(api_key))
    if config.provider == LLMProvider.COHERE:
        return ChatCohere(model=model, cohere_api_key=_required_api_key(api_key))
    if config.provider == LLMProvider.OLLAMA:
        return ChatOllama(model=model, **_base_url_kwargs(base_url))
    if config.provider == LLMProvider.AWS_BEDROCK:
        return ChatBedrockConverse(
            model=model,
            api_key=_required_api_key(api_key),
            **_base_url_kwargs(base_url),
        )
    if config.provider == LLMProvider.XAI:
        return ChatXAI(model=model, api_key=_required_api_key(api_key))

    raise ValueError(f"Unsupported LLM provider: {config.provider.value}")


def _required_api_key(api_key: str) -> str:
    """强制使用设置页/数据库中的 API Key，避免 LangChain Provider 从环境变量兜底。"""

    if not api_key:
        raise ValueError("LLMConfig API key is missing.")
    return api_key


def _base_url_kwargs(base_url: str) -> dict[str, str]:
    """部分 Provider 支持可选 base_url；为空时不覆盖其默认行为。"""

    return {"base_url": base_url} if base_url else {}


def _deepseek_thinking_kwargs(thinking_enabled: bool | None) -> dict[str, dict[str, dict[str, str]]]:
    """DeepSeek 思考模式开关；None 表示不覆盖 Provider 默认行为。"""

    if thinking_enabled is None:
        return {}
    thinking_type = "enabled" if thinking_enabled else "disabled"
    return {"extra_body": {"thinking": {"type": thinking_type}}}


def ensure_llm_configs(repository: ComicRepository) -> list[LLMConfig]:
    """确保数据库里至少有一条 LLM 配置；首次使用时从 .env 初始化。"""

    configs = repository.list_llm_configs()
    if configs:
        return configs
    default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    config = repository.create_llm_config(
        name="Default DeepSeek",
        provider=LLMProvider.DEEPSEEK,
        base_url="",
        model_names=json.dumps([default_model], ensure_ascii=False),
        default_model=default_model,
        api_key=None,
        is_active=True,
    )
    return [config]
