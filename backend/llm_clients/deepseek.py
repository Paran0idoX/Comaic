import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# 统一加载 .env，避免 API key 散落在业务代码里读取。
load_dotenv()

# strip() 可以容忍 .env 中等号后误加空格，例如 DEEPSEEK_MODEL= deepseek-v4-flash。
deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
deepseek_api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()

if not deepseek_api_key:
    raise ValueError("DEEPSEEK_API_KEY must be set in .env")


def _create_deepseek_chat_model(*, thinking_type: str) -> ChatDeepSeek:
    """创建 DeepSeek ChatModel；按业务阶段显式控制 thinking 模式。"""

    if thinking_type not in {"enabled", "disabled"}:
        raise ValueError("thinking_type must be 'enabled' or 'disabled'.")
    return ChatDeepSeek(
        model=deepseek_model,
        api_key=deepseek_api_key,
        extra_body={"thinking": {"type": thinking_type}},
    )


# 大纲阶段更偏创意与推理，引导用户补足设定时允许开启 thinking。
deepseek_thinking_chat_model = _create_deepseek_chat_model(thinking_type="enabled")

# 脚本阶段依赖 DeepAgents 工具调用和 response_format；关闭 thinking 避免 tool_choice 冲突。
deepseek_tool_chat_model = _create_deepseek_chat_model(thinking_type="disabled")

# 兼容旧导入；默认指向工具安全实例，避免未迁移代码触发 tool_choice + thinking 冲突。
deepseek_chat_model = deepseek_tool_chat_model
