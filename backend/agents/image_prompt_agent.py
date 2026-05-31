from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.agents.structured_output import ainvoke_structured_with_retries


class ImagePromptResponse(BaseModel):
    """图片 Prompt Agent 的结构化输出。"""

    positive_prompt: str = Field(description="英文文生图正向 Prompt。")


class ImagePromptAgent:
    """图片 Prompt Agent：把单页脚本转换为文生图正向 Prompt，不负责落库。"""

    def __init__(self, *, llm: Any | None = None, max_structured_retries: int = 3):
        """初始化结构化输出 Agent，避免从自然语言回复中解析 Prompt。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
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
        page_description: str,
    ) -> str:
        """为结构化单页脚本生成英文正向 Prompt。"""

        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content="\n\n".join(
                        [
                            f"Page number: {page_no}",
                            "Comic page structured description:",
                            page_description,
                            "Generate one image positive prompt for this full-page comic image.",
                        ]
                    )
                ),
            ],
            response_model=ImagePromptResponse,
            operation=f"image_prompt_page_{page_no}",
            max_retries=self.max_structured_retries,
            validator=self._validate_response,
        )
        return response.positive_prompt.strip()

    @staticmethod
    def _validate_response(response: ImagePromptResponse) -> None:
        """图片 Prompt 必须返回非空正向 Prompt。"""

        if not response.positive_prompt.strip():
            raise ValueError("ImagePromptAgent returned empty positive_prompt.")

    @staticmethod
    def _default_llm() -> Any:
        """图片 Prompt 生成使用关闭 thinking 的模型实例。"""

        from backend.llm_clients.deepseek import deepseek_tool_chat_model

        return deepseek_tool_chat_model
