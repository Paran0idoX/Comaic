from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai import GoogleGenerativeAI
import os

# 统一加载 .env，避免 API key 散落在业务代码里读取。
load_dotenv()

gemini_model = os.getenv("GEMINI_MODEL")
gemini_key = os.getenv("GEMINI_KEY")

if not gemini_model or not gemini_key:
    raise ValueError("GEMINI_MODEL and GEMINI_KEY must be set in .env")

# 普通文本 LLM：保留给不需要 chat messages 的简单链路使用。
gemini_client = GoogleGenerativeAI(
    model=gemini_model,
    google_api_key=gemini_key,
)

# ChatModel：create_agent 需要 chat model 风格的模型实例。
gemini_chat_model = ChatGoogleGenerativeAI(
    model=gemini_model,
    google_api_key=gemini_key,
)
