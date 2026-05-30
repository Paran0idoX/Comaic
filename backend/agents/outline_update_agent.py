from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.utils.prompt_loader import PromptLoader


class OutlineUpdateAgent:
    """大纲更新子 Agent：只根据当前大纲和本轮输入产出新的大纲文本。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "outline_update_prompt.md",
    ):
        """初始化子 Agent；不挂 checkpoint，避免污染主对话历史。"""

        self.llm = llm or self._default_llm()
        self.prompt = PromptLoader.load(prompt_name)
        self._agent = create_agent(
            model=self.llm,
            tools=[],
            system_prompt=self.prompt,
            name="outline_update_agent",
        )

    async def update_outline(
        self,
        *,
        current_outline: str,
        user_prompt: str,
        update_reason: str,
        conversation_context: str = "",
    ) -> str:
        """调用子 Agent 更新大纲，调用方负责保存返回结果。"""

        user_content = self._build_user_content(
            current_outline=current_outline,
            user_prompt=user_prompt,
            update_reason=update_reason,
            conversation_context=conversation_context,
        )
        result = await self._agent.ainvoke(
            {"messages": [HumanMessage(content=user_content)]},
        )
        return self._last_ai_message(result["messages"])

    @staticmethod
    def _build_user_content(
        *,
        current_outline: str,
        user_prompt: str,
        update_reason: str,
        conversation_context: str,
    ) -> str:
        """把子 Agent 需要的上下文整理为单次输入，便于 prompt 稳定解析。"""

        return "\n\n".join(
            [
                "当前大纲：",
                current_outline or "暂无大纲，请根据用户输入创建第一版阶段性大纲。",
                "本轮用户输入：",
                user_prompt,
                "主 Agent 判断的更新原因：",
                update_reason,
                "最近对话上下文：",
                conversation_context or "暂无额外上下文。",
            ]
        )

    @staticmethod
    def _last_ai_message(messages: list[BaseMessage]) -> str:
        """从子 Agent 输出中提取纯文本，兼容 Gemini 的结构化 content。"""

        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return OutlineUpdateAgent._message_text(message).strip()
        raise ValueError("OutlineUpdateAgent returned no AI message.")

    @staticmethod
    def _message_text(message: BaseMessage) -> str:
        """兼容字符串和结构化消息内容，提取用户可见文本。"""

        if isinstance(message.content, str):
            return message.content
        if isinstance(message.content, list):
            return "".join(
                item.get("text", "")
                for item in message.content
                if isinstance(item, dict)
            )
        return str(message.content)

    @staticmethod
    def _default_llm() -> Any:
        """懒加载默认 Gemini ChatModel，避免导入模块时立刻校验 .env。"""

        from backend.model_clients.gemini import gemini_chat_model

        return gemini_chat_model
