import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from backend.agents.script_agent_models import StoryPacingResponse
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class ScriptPlanningAgent:
    """分页脚本分段规划 Agent：只生成故事节奏分段，不负责落库。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "script_planning_prompt.md",
    ):
        """初始化规划 Agent；使用结构化输出约束 section_plan。"""

        self.llm = llm or self._default_llm()
        self.prompt = PromptLoader.load(prompt_name)
        logger.info("Initializing ScriptPlanningAgent prompt=%s", prompt_name)
        self._agent = create_agent(
            model=self.llm,
            tools=[],
            system_prompt=self.prompt,
            response_format=StoryPacingResponse,
            name="script_planning_agent",
        )

    async def generate_section_plan(
        self,
        *,
        outline: str,
        total_pages: int,
        user_requirement: str = "",
        feedback: str = "",
    ) -> list[dict]:
        """生成完整分段计划；校验和保存由 Service 负责。"""

        logger.info(
            "ScriptPlanningAgent generation started total_pages=%s outline_chars=%s requirement_chars=%s feedback_chars=%s",
            total_pages,
            len(outline),
            len(user_requirement),
            len(feedback),
        )
        result = await self._agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=self._build_input(
                            outline=outline,
                            total_pages=total_pages,
                            user_requirement=user_requirement,
                            feedback=feedback,
                        )
                    )
                ]
            }
        )
        structured_response = result.get("structured_response")
        if not isinstance(structured_response, StoryPacingResponse):
            raise ValueError("ScriptPlanningAgent returned no structured section plan.")
        sections = [section.model_dump() for section in structured_response.sections]
        logger.info("ScriptPlanningAgent generation completed section_count=%s", len(sections))
        return sections

    @staticmethod
    def _build_input(
        *,
        outline: str,
        total_pages: int,
        user_requirement: str,
        feedback: str,
    ) -> str:
        """构造规划输入；feedback 用于校验失败后的完整重试。"""

        parts = [
            f"目标总页数：{total_pages}",
            "漫画大纲：",
            outline,
            "用户补充要求：",
            user_requirement or "无",
        ]
        if feedback:
            parts.extend(
                [
                    "上一次分段计划校验失败，请重新输出完整分段计划。失败原因：",
                    feedback,
                ]
            )
        return "\n\n".join(parts)

    @staticmethod
    def _default_llm() -> Any:
        """懒加载脚本阶段 DeepSeek ChatModel，避免导入模块时校验 .env。"""

        from backend.llm_clients.deepseek import deepseek_tool_chat_model

        return deepseek_tool_chat_model
