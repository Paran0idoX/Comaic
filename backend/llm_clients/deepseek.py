import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

from backend.llm_clients.factory import get_thinking_chat_model, get_tool_chat_model


load_dotenv()

# 兼容旧代码里读取的模块变量；真实运行配置优先使用 SQLite 中的 llm_config。
deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
deepseek_api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()


class LazyChatModel:
    """旧全局模型实例的懒代理；真正调用时才读取当前设置页配置。"""

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory

    def __getattr__(self, item: str) -> Any:
        return getattr(self._factory(), item)


deepseek_thinking_chat_model = LazyChatModel(get_thinking_chat_model)
deepseek_tool_chat_model = LazyChatModel(get_tool_chat_model)
deepseek_chat_model = deepseek_tool_chat_model
