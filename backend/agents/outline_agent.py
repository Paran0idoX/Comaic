from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.agents.outline_update_agent import OutlineUpdateAgent
from backend.utils.prompt_loader import PromptLoader


USER_PROMPT_START = "<user_prompt>"
USER_PROMPT_END = "</user_prompt>"
logger = logging.getLogger(__name__)


class OutlineAgent:
    """大纲主 Agent：负责对话，并按需调用子 Agent 更新大纲。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        memory_path: str | Path = "data/outline_agent_memory.sqlite3",
        conversation_prompt_name: str = "outline_conversation_prompt.md",
        finalize_prompt_name: str = "outline_finalize_prompt.md",
        snapshot_prompt_name: str = "outline_snapshot_prompt.md",
    ):
        """初始化 Agent 配置；真正的记忆连接在 async with 中打开。"""

        self.llm = llm or self._default_llm()
        self.memory_path = Path(memory_path)
        logger.info("Initializing OutlineAgent memory_path=%s", self.memory_path)
        self.conversation_prompt = PromptLoader.load(conversation_prompt_name)
        self.finalize_prompt = PromptLoader.load(finalize_prompt_name)
        self.snapshot_prompt = PromptLoader.load(snapshot_prompt_name)
        self._memory_context: AsyncIterator[AsyncSqliteSaver] | None = None
        self._checkpointer: AsyncSqliteSaver | None = None
        self._agent = None
        self._tools = []
        self._current_outline = ""
        self._current_user_prompt = ""
        self._last_updated_outline: str | None = None

    async def __aenter__(self) -> "OutlineAgent":
        """打开 SQLite checkpoint，并基于 create_agent 构建可对话 Agent。"""

        logger.info("Opening OutlineAgent checkpoint memory_path=%s", self.memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_context = AsyncSqliteSaver.from_conn_string(str(self.memory_path))
        self._checkpointer = await self._memory_context.__aenter__()
        await self._checkpointer.setup()
        self._tools = [
            StructuredTool.from_function(
                coroutine=self._update_outline_tool,
                name="update_outline",
                description=(
                    "当用户提供新设定、修改、确认或纠偏，会改变漫画大纲时调用。"
                    "输入 update_reason，说明为什么需要更新以及本轮要改什么。"
                ),
            )
        ]
        self._agent = self._create_agent()
        logger.info("OutlineAgent ready tools=%s", [tool.name for tool in self._tools])
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """退出上下文时关闭 SQLite checkpoint 连接。"""

        if self._memory_context is not None:
            await self._memory_context.__aexit__(exc_type, exc_value, traceback)
        logger.info("OutlineAgent checkpoint closed memory_path=%s", self.memory_path)

    async def chat(
        self,
        *,
        thread_id: str,
        user_message: str,
        current_outline: str = "",
    ) -> AsyncIterator[str]:
        """继续大纲讨论，并以 token/chunk 的形式流式返回回复。"""

        self._current_outline = current_outline
        self._current_user_prompt = user_message
        self._last_updated_outline = None
        logger.info(
            "OutlineAgent chat started thread_id=%s user_message_chars=%s current_outline_chars=%s",
            thread_id,
            len(user_message),
            len(current_outline),
        )
        # 当前大纲作为本轮临时 system context 注入，不写入 checkpoint 的普通对话历史。
        self._agent = self._create_agent(current_outline=current_outline)

        chunk_count = 0
        async for chunk in self._stream(thread_id=thread_id, user_message=user_message):
            chunk_count += 1
            yield chunk
        logger.info(
            "OutlineAgent chat completed thread_id=%s chunks=%s outline_updated=%s",
            thread_id,
            chunk_count,
            self._last_updated_outline is not None,
        )

    def consume_updated_outline(self) -> str | None:
        """取出本轮子 Agent 生成的大纲；取出后清空，避免跨轮误用。"""

        updated_outline = self._last_updated_outline
        self._last_updated_outline = None
        logger.info("OutlineAgent consumed updated outline present=%s", updated_outline is not None)
        return updated_outline

    def _create_agent(self, *, current_outline: str = ""):
        """创建主 Agent；当前大纲只作为临时 system prompt 上下文传入。"""

        self._ensure_checkpointer_ready()
        system_prompt = self.conversation_prompt
        if current_outline:
            system_prompt = (
                f"{system_prompt}\n\n"
                "当前大纲如下，请结合本轮用户输入判断是否需要调用 update_outline：\n"
                f"{current_outline}"
            )
        else:
            system_prompt = (
                f"{system_prompt}\n\n"
                "当前大纲：暂无。请结合本轮用户输入判断是否需要调用 update_outline 创建第一版阶段性大纲。"
            )
        return create_agent(
            model=self.llm,
            tools=self._tools,
            system_prompt=system_prompt,
            checkpointer=self._checkpointer,
            name="outline_agent",
        )

    async def finalize(self, *, thread_id: str) -> str:
        """在用户确认后，基于同一 thread_id 的上下文输出最终大纲文本。"""

        return await self._invoke(
            thread_id=thread_id,
            user_message=self.finalize_prompt,
        )

    async def generate_outline_snapshot(self, *, thread_id: str) -> str:
        """基于当前对话历史生成展示用大纲快照，不污染原会话记忆。"""

        self._ensure_ready()
        logger.info("OutlineAgent snapshot generation started thread_id=%s", thread_id)
        messages = await self._get_thread_messages(thread_id=thread_id)
        conversation = self._format_messages(messages)

        # 快照生成使用独立 agent 且不挂 checkpointer，避免写回聊天历史。
        snapshot_agent = create_agent(
            model=self.llm,
            tools=[],
            system_prompt=self.snapshot_prompt,
            name="outline_snapshot_agent",
        )
        result = await snapshot_agent.ainvoke(
            {"messages": [HumanMessage(content=conversation)]},
        )
        outline = self._last_ai_message(result["messages"])
        logger.info(
            "OutlineAgent snapshot generation completed thread_id=%s message_count=%s outline_chars=%s",
            thread_id,
            len(messages),
            len(outline),
        )
        return outline

    async def get_conversation_messages(self, *, thread_id: str) -> list[dict[str, str]]:
        """读取 checkpoint 中的历史对话，供前端重新进入页面时恢复聊天记录。"""

        self._ensure_ready()
        logger.info("OutlineAgent loading conversation messages thread_id=%s", thread_id)
        messages = await self._get_thread_messages(thread_id=thread_id)
        conversation_messages = self._conversation_messages(messages)
        logger.info(
            "OutlineAgent loaded conversation messages thread_id=%s count=%s",
            thread_id,
            len(conversation_messages),
        )
        return conversation_messages

    @classmethod
    async def load_conversation_messages(
        cls,
        *,
        thread_id: str,
        memory_path: str | Path = "data/outline_agent_memory.sqlite3",
    ) -> list[dict[str, str]]:
        """不创建 LLM Agent，直接读取 checkpoint，避免恢复页面时强制要求 API Key。"""

        checkpoint_path = Path(memory_path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Loading OutlineAgent checkpoint messages thread_id=%s", thread_id)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            checkpoint = await checkpointer.aget(
                {"configurable": {"thread_id": thread_id}},
            )

        channel_values = checkpoint.get("channel_values", {}) if checkpoint else {}
        raw_messages = channel_values.get("messages", []) if isinstance(channel_values, dict) else []
        messages = [message for message in raw_messages if isinstance(message, BaseMessage)]
        conversation_messages = cls._conversation_messages(messages)
        logger.info(
            "Loaded OutlineAgent checkpoint messages thread_id=%s count=%s",
            thread_id,
            len(conversation_messages),
        )
        return conversation_messages

    @classmethod
    def _conversation_messages(cls, messages: list[BaseMessage]) -> list[dict[str, str]]:
        """把 checkpoint 消息过滤为前端需要的 user/agent 文本。"""

        conversation_messages = []
        for message in messages:
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "agent"
            else:
                continue

            content = cls._message_text(message).strip()
            if content:
                conversation_messages.append(
                    {
                        "role": role,
                        "content": cls._display_message_text(message),
                    }
                )
        return conversation_messages

    async def _update_outline_tool(self, update_reason: str) -> str:
        """主 Agent 调用的本地工具：委托子 Agent 生成新大纲，但不直接落库。"""

        logger.info(
            "OutlineAgent update_outline tool called reason_chars=%s current_outline_chars=%s",
            len(update_reason),
            len(self._current_outline),
        )
        messages = []
        if self._current_user_prompt:
            messages.append(HumanMessage(content=self._current_user_prompt))
        conversation_context = self._format_messages(messages)
        update_agent = OutlineUpdateAgent(llm=self.llm)
        updated_outline = await update_agent.update_outline(
            current_outline=self._current_outline,
            user_prompt=self._current_user_prompt,
            update_reason=update_reason,
            conversation_context=conversation_context,
        )
        self._last_updated_outline = updated_outline
        logger.info("OutlineAgent update_outline tool completed outline_chars=%s", len(updated_outline))
        return "大纲已更新。请用简短自然的话告诉用户你已经根据本轮信息整理了大纲，不要复述完整大纲。"

    async def clear_thread(self, *, thread_id: str) -> None:
        """清空指定会话的短期记忆，通常用于重新开始大纲讨论。"""

        self._ensure_ready()
        await self._checkpointer.adelete_thread(thread_id)  # type: ignore[union-attr]

    async def _get_thread_messages(self, *, thread_id: str) -> list[BaseMessage]:
        """从 LangGraph checkpoint 读取某个 thread_id 的消息列表。"""

        self._ensure_ready()
        logger.debug("OutlineAgent reading checkpoint state thread_id=%s", thread_id)
        snapshot = await self._agent.aget_state(  # type: ignore[union-attr]
            config={"configurable": {"thread_id": thread_id}},
        )
        messages = snapshot.values.get("messages", [])
        result = [
            message
            for message in messages
            if isinstance(message, BaseMessage)
        ]
        logger.debug("OutlineAgent checkpoint state loaded thread_id=%s message_count=%s", thread_id, len(result))
        return result

    async def _invoke(self, *, thread_id: str, user_message: str) -> str:
        """调用底层 create_agent，并用 thread_id 选择对应的会话记忆。"""

        self._ensure_ready()
        logger.info("OutlineAgent invoke started thread_id=%s user_message_chars=%s", thread_id, len(user_message))
        result = await self._agent.ainvoke(  # type: ignore[union-attr]
            {"messages": [HumanMessage(content=user_message)]},
            # LangGraph checkpoint 用 thread_id 区分不同用户/项目的对话历史。
            config={"configurable": {"thread_id": thread_id}},
        )
        text = self._last_ai_message(result["messages"])
        logger.info("OutlineAgent invoke completed thread_id=%s response_chars=%s", thread_id, len(text))
        return text

    async def _stream(self, *, thread_id: str, user_message: str) -> AsyncIterator[str]:
        """调用底层 create_agent 的事件流，只向外暴露模型生成文本。"""

        self._ensure_ready()
        logger.debug("OutlineAgent stream opened thread_id=%s", thread_id)
        async for event in self._agent.astream_events(  # type: ignore[union-attr]
            {"messages": [HumanMessage(content=user_message)]},
            # LangGraph checkpoint 用 thread_id 区分不同用户/项目的对话历史。
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            if event.get("event") != "on_chat_model_stream":
                continue
            langgraph_node = event.get("metadata", {}).get("langgraph_node")
            if langgraph_node is not None and langgraph_node != "model":
                continue

            chunk = event.get("data", {}).get("chunk")
            text = self._chunk_text(chunk)
            if text:
                yield text
        logger.debug("OutlineAgent stream closed thread_id=%s", thread_id)

    def _ensure_ready(self) -> None:
        """确保 Agent 已经通过 async with 完成初始化。"""

        if self._agent is None or self._checkpointer is None:
            raise RuntimeError("OutlineAgent must be used with 'async with OutlineAgent()'.")

    def _ensure_checkpointer_ready(self) -> None:
        """确保 checkpoint 已打开；创建 Agent 时不要求旧 agent 已存在。"""

        if self._checkpointer is None:
            raise RuntimeError("OutlineAgent must be used with 'async with OutlineAgent()'.")

    @staticmethod
    def _format_messages(messages: list[BaseMessage]) -> str:
        """把会话消息整理成快照 Agent 易读的纯文本上下文。"""

        lines = []
        for message in messages:
            if isinstance(message, HumanMessage):
                role = "用户"
            elif isinstance(message, AIMessage):
                role = "助手"
            else:
                role = message.type
            lines.append(f"{role}: {OutlineAgent._display_message_text(message)}")
        return "\n".join(lines)

    @staticmethod
    def _build_main_agent_input(*, current_outline: str, user_message: str) -> str:
        """把当前大纲和用户输入一起交给主 Agent，同时保留可恢复的用户原文标记。"""

        return "\n\n".join(
            [
                "当前大纲：",
                current_outline or "暂无大纲。",
                "本轮用户输入：",
                f"{USER_PROMPT_START}\n{user_message}\n{USER_PROMPT_END}",
            ]
        )

    @staticmethod
    def _last_ai_message(messages: list[BaseMessage]) -> str:
        """从消息列表末尾找到最近一条 AI 回复。"""

        for message in reversed(messages):
            if isinstance(message, AIMessage):
                # Gemini 可能返回结构化 content，不能直接 str()，否则会把签名等元数据展示给用户。
                return OutlineAgent._message_text(message)
        raise ValueError("OutlineAgent graph returned no AI message.")

    @staticmethod
    def _chunk_text(chunk: Any) -> str:
        """从 LangChain 的流式消息块中提取文本内容。"""

        if not isinstance(chunk, AIMessageChunk):
            return ""
        if isinstance(chunk.content, str):
            return chunk.content
        if isinstance(chunk.content, list):
            return "".join(
                item.get("text", "")
                for item in chunk.content
                if isinstance(item, dict)
            )
        return ""

    @staticmethod
    def _message_text(message: BaseMessage) -> str:
        """兼容字符串和结构化消息内容，提取可读文本。"""

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
    def _display_message_text(message: BaseMessage) -> str:
        """恢复给前端展示的消息文本，隐藏主 Agent 输入中的当前大纲上下文。"""

        content = OutlineAgent._message_text(message)
        if USER_PROMPT_START in content and USER_PROMPT_END in content:
            return content.split(USER_PROMPT_START, 1)[1].split(USER_PROMPT_END, 1)[0].strip()
        return content

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建大纲阶段 ChatModel。"""

        from backend.llm_clients.factory import get_thinking_chat_model

        return get_thinking_chat_model()


@asynccontextmanager
async def create_outline_agent(**kwargs) -> AsyncIterator[OutlineAgent]:
    """便捷工厂：用 async with 管理 OutlineAgent 的记忆连接生命周期。"""

    async with OutlineAgent(**kwargs) as agent:
        yield agent
