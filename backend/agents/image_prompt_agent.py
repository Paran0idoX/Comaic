from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class ImagePromptResponse(BaseModel):
    """图片 Prompt Agent 的结构化输出。"""

    positive_prompt: str = Field(description="英文文生图正向 Prompt。")


class ImagePromptAgent:
    """图片 Prompt Agent：把单页脚本转换为文生图正向 Prompt，不负责落库。"""

    def __init__(self, *, llm: Any | None = None):
        """初始化结构化输出 Agent，避免从自然语言回复中解析 Prompt。"""

        self.llm = llm or self._default_llm()
        self._agent = create_agent(
            model=self.llm,
            tools=[],
            response_format=ImagePromptResponse,
            name="image_prompt_agent",
        )

    async def generate(
        self,
        *,
        system_prompt: str,
        page_no: int,
        script: str,
    ) -> str:
        """为单页脚本生成英文正向 Prompt。"""

        result = await self._agent.ainvoke(
            {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content="\n\n".join(
                            [
                                f"Page number: {page_no}",
                                "Comic page script:",
                                script,
                                "Generate one image positive prompt for this full-page comic image.",
                            ]
                        )
                    ),
                ]
            }
        )
        structured_response = result.get("structured_response")
        if isinstance(structured_response, ImagePromptResponse):
            return structured_response.positive_prompt.strip()
        if isinstance(structured_response, dict):
            return str(structured_response.get("positive_prompt", "")).strip()
        if hasattr(structured_response, "model_dump"):
            return str(structured_response.model_dump().get("positive_prompt", "")).strip()
        raise ValueError("ImagePromptAgent returned no positive_prompt.")

    @staticmethod
    def _default_llm() -> Any:
        """图片 Prompt 生成使用关闭 thinking 的模型实例。"""

        from backend.llm_clients.deepseek import deepseek_tool_chat_model

        return deepseek_tool_chat_model
