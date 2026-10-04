"""在模型请求边界添加全局上下文，不写入 Agent checkpoint 或替换任务提示词。"""

from functools import lru_cache
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.prompt_values import ChatPromptValue, PromptValue


class GlobalSystemPromptMixin:
    """兼容原生 ChatModel 的工具绑定、结构化输出、流式与批量请求。"""

    def _system_prompt_prefix(self) -> str:
        return self.global_system_prompt or ""

    def _convert_input(self, model_input: LanguageModelInput) -> PromptValue:
        converted = super()._convert_input(model_input)
        prefix = self._system_prompt_prefix().strip()
        if not prefix:
            return converted
        messages = list(converted.to_messages())
        system_index = next((index for index, message in enumerate(messages)
            if isinstance(message, SystemMessage) and isinstance(message.content, str)), None)
        if system_index is None:
            messages.insert(0, SystemMessage(content=prefix))
        else:
            system = messages[system_index]
            # LangChain invoke/generate/请求转换可能经过多次入口，只添加一次。
            if system.content != prefix and not system.content.startswith(prefix + "\n\n"):
                messages[system_index] = system.model_copy(update={"content": prefix + "\n\n" + system.content})
        return ChatPromptValue(messages=messages)

    def generate(self, messages: list[list[BaseMessage]], *args: Any, **kwargs: Any):
        """直接批量调用也在追踪回调前完成注入。"""
        return super().generate(
            [self._convert_input(batch).to_messages() for batch in messages], *args, **kwargs
        )

    async def agenerate(self, messages: list[list[BaseMessage]], *args: Any, **kwargs: Any):
        """异步批量调用与其它调用保持同一份模型配置快照。"""
        return await super().agenerate(
            [self._convert_input(batch).to_messages() for batch in messages], *args, **kwargs
        )


@lru_cache(maxsize=None)
def system_prompt_model_class(model_class: type) -> type:
    """为各 Provider 的原生类添加同一注入能力，保留原生协议转换。"""
    if issubclass(model_class, GlobalSystemPromptMixin):
        return model_class
    return type(f"SystemPrompt{model_class.__name__}", (GlobalSystemPromptMixin, model_class), {
        "__module__": __name__,
        "__annotations__": {"global_system_prompt": str | None},
        "global_system_prompt": None,
    })
