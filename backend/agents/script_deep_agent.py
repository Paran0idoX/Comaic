import json
import logging
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class ScriptDeepAgent:
    """DeepAgents 分页脚本主 Agent，负责调度节奏、编写和监督子 Agent。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        main_prompt_name: str = "script_deep_main_prompt.md",
        pacing_prompt_name: str = "script_pacing_prompt.md",
        writer_prompt_name: str = "script_writer_prompt.md",
        supervisor_prompt_name: str = "script_supervisor_prompt.md",
    ):
        """初始化 Deep Agent 和三个专用子 Agent。"""

        self.llm = llm or self._default_llm()
        logger.info("Initializing ScriptDeepAgent")
        self.main_prompt = PromptLoader.load(main_prompt_name)
        self.pacing_prompt = PromptLoader.load(pacing_prompt_name)
        self.writer_prompt = PromptLoader.load(writer_prompt_name)
        self.supervisor_prompt = PromptLoader.load(supervisor_prompt_name)
        self._agent = create_deep_agent(
            model=self.llm,
            system_prompt=self.main_prompt,
            subagents=[
                {
                    "name": "story_pacing_agent",
                    "description": "根据漫画大纲和目标页数划分故事节奏段落。",
                    "system_prompt": self.pacing_prompt,
                    "model": self.llm,
                },
                {
                    "name": "page_script_writer_agent",
                    "description": "根据大纲、分段计划和审查意见编写或修订分页漫画脚本。",
                    "system_prompt": self.writer_prompt,
                    "model": self.llm,
                },
                {
                    "name": "script_supervisor_agent",
                    "description": "审查分页脚本是否符合大纲、分段目标、页码连续性和段落衔接。",
                    "system_prompt": self.supervisor_prompt,
                    "model": self.llm,
                },
            ],
            name="script_deep_agent",
        )

    async def generate_single_page(
        self,
        *,
        outline: str,
        total_pages: int,
        page_no: int,
        user_requirement: str = "",
    ) -> dict[str, Any]:
        """生成单页漫画脚本，返回结构化 JSON 数据。"""

        logger.info(
            "ScriptDeepAgent single generation started page_no=%s total_pages=%s outline_chars=%s requirement_chars=%s",
            page_no,
            total_pages,
            len(outline),
            len(user_requirement),
        )
        result = await self._agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=self._build_single_page_input(
                            outline=outline,
                            total_pages=total_pages,
                            page_no=page_no,
                            user_requirement=user_requirement,
                        )
                    )
                ]
            }
        )
        parsed = self._parse_json_result(result["messages"])
        logger.info(
            "ScriptDeepAgent single generation completed page_count=%s review_count=%s",
            len(parsed.get("pages", [])),
            len(parsed.get("reviews", [])),
        )
        return parsed

    async def generate_batch(
        self,
        *,
        outline: str,
        total_pages: int,
        user_requirement: str = "",
    ) -> dict[str, Any]:
        """批量生成分页漫画脚本，返回结构化 JSON 数据。"""

        logger.info(
            "ScriptDeepAgent batch generation started total_pages=%s outline_chars=%s requirement_chars=%s",
            total_pages,
            len(outline),
            len(user_requirement),
        )
        result = await self._agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=self._build_batch_input(
                            outline=outline,
                            total_pages=total_pages,
                            user_requirement=user_requirement,
                        )
                    )
                ]
            }
        )
        parsed = self._parse_json_result(result["messages"])
        logger.info(
            "ScriptDeepAgent batch generation completed section_count=%s page_count=%s review_count=%s",
            len(parsed.get("section_plan", [])),
            len(parsed.get("pages", [])),
            len(parsed.get("reviews", [])),
        )
        return parsed

    @staticmethod
    def _build_single_page_input(
        *,
        outline: str,
        total_pages: int,
        page_no: int,
        user_requirement: str,
    ) -> str:
        """构造单页生成输入。"""

        return "\n\n".join(
            [
                "任务模式：single",
                f"目标页码：{page_no}",
                f"总页数：{total_pages}",
                "漫画大纲：",
                outline,
                "用户补充要求：",
                user_requirement or "无",
            ]
        )

    @staticmethod
    def _build_batch_input(*, outline: str, total_pages: int, user_requirement: str) -> str:
        """构造批量生成输入。"""

        return "\n\n".join(
            [
                "任务模式：batch",
                f"总页数：{total_pages}",
                "漫画大纲：",
                outline,
                "用户补充要求：",
                user_requirement or "无",
            ]
        )

    def _parse_json_result(self, messages: list[BaseMessage]) -> dict[str, Any]:
        """从 Agent 最终消息中解析 JSON，兼容代码块包裹。"""

        text = self._last_ai_message(messages)
        logger.debug("ScriptDeepAgent raw result chars=%s", len(text))
        json_text = self._extract_json_text(text)
        result = json.loads(json_text)
        if not isinstance(result, dict):
            raise ValueError("ScriptDeepAgent result must be a JSON object.")
        logger.debug("ScriptDeepAgent parsed result keys=%s", list(result.keys()))
        return result

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """提取 JSON 对象文本，避免模型输出 ```json 包裹导致解析失败。"""

        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("ScriptDeepAgent returned no JSON object.")
        return stripped[start : end + 1]

    @staticmethod
    def _last_ai_message(messages: list[BaseMessage]) -> str:
        """从消息列表中提取最后一条 AI 文本。"""

        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return ScriptDeepAgent._message_text(message).strip()
        raise ValueError("ScriptDeepAgent returned no AI message.")

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
    def _default_llm() -> Any:
        """懒加载默认 DeepSeek ChatModel，避免导入模块时立刻校验 .env。"""

        from backend.model_clients.deepseek import deepseek_chat_model

        return deepseek_chat_model
