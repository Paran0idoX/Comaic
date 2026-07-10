import json

from langchain_core.messages import HumanMessage

from backend.i18n.errors import AppError
from backend.llm_clients.factory import LLMConfigInput, create_chat_model, ensure_llm_configs
from backend.models.comic import LLMConfig
from backend.models.enums import LLMProvider
from backend.repositories.comic_repository import ComicRepository, KEEP_EXISTING_VALUE


class SettingsService:
    """设置服务：负责多组模型 API 配置、模型名列表和测试连接。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository；配置落库仍保持在数据访问层。"""

        self.repository = repository

    def list_llm_configs(self) -> list[LLMConfig]:
        """读取全部 LLM 配置；没有配置时从 .env 初始化默认配置。"""

        ensure_llm_configs(self.repository)
        return self.repository.list_llm_configs()

    def get_app_settings(self):
        """读取应用级运行设置；不存在时使用默认值初始化。"""

        return self.repository.get_app_settings()

    def update_app_settings(self, *, script_section_max_concurrency: int):
        """更新应用级运行设置。"""

        if script_section_max_concurrency < 1 or script_section_max_concurrency > 20:
            raise ValueError("script_section_max_concurrency must be between 1 and 20.")
        return self.repository.update_app_settings(
            script_section_max_concurrency=script_section_max_concurrency,
        )

    def create_llm_config(
        self,
        *,
        name: str,
        provider: LLMProvider,
        base_url: str | None,
        model_names: list[str],
        default_model: str | None = None,
        api_key: str | None = None,
        is_active: bool = False,
    ) -> LLMConfig:
        """新增一组 LLM Provider 配置，并保存该组可用模型名列表。"""

        normalized_models, normalized_default = self._normalize_models(
            model_names=model_names,
            default_model=default_model,
        )
        return self.repository.create_llm_config(
            name=self._required_text(name, "LLM config name"),
            provider=provider,
            base_url=self._normalize_base_url(provider=provider, base_url=base_url),
            model_names=json.dumps(normalized_models, ensure_ascii=False),
            default_model=normalized_default,
            api_key=self._optional_text(api_key),
            is_active=is_active,
        )

    def update_llm_config(
        self,
        *,
        config_id: int,
        name: str,
        provider: LLMProvider,
        base_url: str | None,
        model_names: list[str],
        default_model: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
    ) -> LLMConfig:
        """更新一组 LLM 配置；空 API Key 表示保留旧值。"""

        self._get_llm_config(config_id)
        normalized_models, normalized_default = self._normalize_models(
            model_names=model_names,
            default_model=default_model,
        )
        normalized_api_key = self._optional_text(api_key)
        return self.repository.update_llm_config(
            config_id=config_id,
            name=self._required_text(name, "LLM config name"),
            provider=provider,
            base_url=self._normalize_base_url(provider=provider, base_url=base_url),
            model_names=json.dumps(normalized_models, ensure_ascii=False),
            default_model=normalized_default,
            api_key=normalized_api_key if normalized_api_key is not None else KEEP_EXISTING_VALUE,
            clear_api_key=clear_api_key,
        )

    def activate_llm_config(self, *, config_id: int) -> LLMConfig:
        """设置某组 API 配置为当前 active。"""

        self._get_llm_config(config_id)
        return self.repository.activate_llm_config(config_id)

    def delete_llm_config(self, *, config_id: int) -> None:
        """删除一组 API 配置；最后一组配置不允许删除。"""

        self._get_llm_config(config_id)
        self.repository.delete_llm_config(config_id)

    async def test_llm_config(
        self,
        *,
        config_id: int | None = None,
        provider: LLMProvider | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
    ) -> None:
        """用已保存或临时表单配置创建模型并发送一次极短请求。"""

        saved_config = self._get_llm_config(config_id) if config_id is not None else None
        effective_provider = provider or (saved_config.provider if saved_config is not None else None)
        effective_base_url = base_url if base_url is not None else (
            saved_config.base_url if saved_config is not None else None
        )
        effective_model = model or (saved_config.default_model if saved_config is not None else None)
        normalized_api_key = self._optional_text(api_key)
        effective_api_key = (
            None
            if clear_api_key
            else normalized_api_key or (saved_config.api_key if saved_config is not None else None)
        )
        config = LLMConfigInput(
            provider=effective_provider or LLMProvider.OPENAI_COMPATIBLE,
            base_url=self._normalize_base_url(
                provider=effective_provider or LLMProvider.OPENAI_COMPATIBLE,
                base_url=effective_base_url,
            ),
            model=self._required_text(effective_model or "", "LLM model"),
            api_key=effective_api_key,
        )
        try:
            model_instance = create_chat_model(config)
            await model_instance.ainvoke([HumanMessage(content="Reply with OK.")])
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - 外部模型错误统一转换为稳定业务错误
            raise AppError(
                code="llm.test_failed",
                status_code=400,
                debug_message=str(exc),
            ) from exc

    def _get_llm_config(self, config_id: int) -> LLMConfig:
        """读取单条配置；不存在时抛出稳定可映射错误。"""

        config = self.repository.get_llm_config(config_id)
        if config is None:
            raise ValueError(f"LLMConfig not found: {config_id}")
        return config

    @staticmethod
    def model_names_from_config(config: LLMConfig) -> list[str]:
        """解析 llm_config.model_names JSON 字段。"""

        try:
            value = json.loads(config.model_names or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def _normalize_models(
        cls,
        *,
        model_names: list[str],
        default_model: str | None,
    ) -> tuple[list[str], str]:
        """去重、去空模型名，并确保默认模型属于模型名列表。"""

        normalized_models: list[str] = []
        seen: set[str] = set()
        for model_name in model_names:
            normalized = str(model_name).strip()
            if normalized and normalized not in seen:
                normalized_models.append(normalized)
                seen.add(normalized)
        if not normalized_models:
            raise ValueError("LLM model names cannot be empty.")
        normalized_default = (default_model or "").strip() or normalized_models[0]
        if normalized_default not in seen:
            raise ValueError("LLM default model must be included in model names.")
        return normalized_models, normalized_default

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        """统一校验设置页必填文本。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty.")
        return normalized

    @staticmethod
    def _normalize_base_url(*, provider: LLMProvider, base_url: str | None) -> str:
        """只有 OpenAI 兼容接口要求 API Base URL，其它 Provider 可为空。"""

        normalized = (base_url or "").strip()
        if provider == LLMProvider.OPENAI_COMPATIBLE and not normalized:
            raise ValueError("LLM API Base URL cannot be empty.")
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        """清理可选文本，空字符串按 None 处理。"""

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def provider_options() -> list[dict]:
        """返回前端用于选择和自动匹配的 Provider 元信息。"""

        return [
            {
                "value": LLMProvider.OPENAI_COMPATIBLE,
                "label": "OpenAI（兼容）",
                "requires_base_url": True,
                "model_prefixes": ["gpt", "o1", "o3", "o4"],
            },
            {
                "value": LLMProvider.DEEPSEEK,
                "label": "DeepSeek",
                "requires_base_url": False,
                "model_prefixes": ["deepseek"],
            },
            {
                "value": LLMProvider.ANTHROPIC,
                "label": "Anthropic",
                "requires_base_url": False,
                "model_prefixes": ["claude"],
            },
            {
                "value": LLMProvider.GOOGLE_GENAI,
                "label": "Google GenAI",
                "requires_base_url": False,
                "model_prefixes": ["gemini"],
            },
            {
                "value": LLMProvider.MISTRALAI,
                "label": "MistralAI",
                "requires_base_url": False,
                "model_prefixes": ["mistral", "codestral"],
            },
            {
                "value": LLMProvider.GROQ,
                "label": "Groq",
                "requires_base_url": False,
                "model_prefixes": ["groq", "llama-3", "llama3", "mixtral"],
            },
            {
                "value": LLMProvider.COHERE,
                "label": "Cohere",
                "requires_base_url": False,
                "model_prefixes": ["command"],
            },
            {
                "value": LLMProvider.OLLAMA,
                "label": "Ollama",
                "requires_base_url": False,
                "model_prefixes": ["llama", "qwen", "phi", "mistral"],
            },
            {
                "value": LLMProvider.AWS_BEDROCK,
                "label": "AWS Bedrock",
                "requires_base_url": False,
                "model_prefixes": ["bedrock", "anthropic.claude", "amazon."],
            },
            {
                "value": LLMProvider.XAI,
                "label": "xAI",
                "requires_base_url": False,
                "model_prefixes": ["grok"],
            },
        ]
