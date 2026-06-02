from collections.abc import Mapping
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class ImagePromptAgent:
    """图片 Prompt Agent：把单页脚本转换为文生图正向 Prompt，不负责落库。"""

    def __init__(self, *, llm: Any | None = None):
        """初始化普通文本输出 Agent；图片 Prompt 直接使用模型最终回复。"""

        self.llm = llm or self._default_llm()
        self._agent = create_agent(
            model=self.llm,
            tools=[],
            name="image_prompt_agent",
        )

    async def generate(
        self,
        *,
        system_prompt: str,
        page_no: int,
        page_description: str,
    ) -> str:
        """为结构化单页脚本生成正向 Prompt。"""

        result = await self._agent.ainvoke(
            {
                "messages": [
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
                ]
            }
        )
        prompt = self._last_ai_text(result["messages"]).strip()
        if not prompt:
            raise ValueError(f"ImagePromptAgent returned empty output for page {page_no}.")
        return prompt

    @staticmethod
    def _last_ai_text(messages: list[BaseMessage]) -> str:
        """从 Agent 返回消息中提取最后一条 AI 文本，兼容字符串和文本块内容。"""

        for message in reversed(messages):
            if isinstance(message, AIMessage):
                if isinstance(message.content, str):
                    return message.content
                parts: list[str] = []
                for block in message.content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, Mapping) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                return "\n".join(part for part in parts if part)
        raise ValueError("ImagePromptAgent returned no AI message.")

    @staticmethod
    def _default_llm() -> Any:
        """图片 Prompt 生成使用关闭 thinking 的模型实例。"""

        from backend.llm_clients.deepseek import deepseek_thinking_chat_model

        return deepseek_thinking_chat_model
