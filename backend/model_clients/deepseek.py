import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# 统一加载 .env，避免 API key 散落在业务代码里读取。
load_dotenv()

deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

if not deepseek_api_key:
    raise ValueError("DEEPSEEK_API_KEY must be set in .env")

# ChatModel：create_agent 需要 chat model 风格的模型实例。
deepseek_chat_model = ChatDeepSeek(
    model=deepseek_model,
    api_key=deepseek_api_key,
)
