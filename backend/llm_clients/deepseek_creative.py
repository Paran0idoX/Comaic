"""保留历史 import 路径；新代码通过 factory 使用统一的模型全局提示词注入。"""

from langchain_deepseek import ChatDeepSeek
from backend.llm_clients.system_prompt import system_prompt_model_class

# 兼容名称不再带有 DeepSeek 专用注入行为，默认文本由 API 模型配置提供。
CreativeChatDeepSeek = system_prompt_model_class(ChatDeepSeek)
