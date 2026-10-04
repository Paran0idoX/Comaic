import logging
import json
from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.script_agent_models import StoryPacingResponse
from backend.agents.script_prompt_formatters import format_outline_characters
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class ScriptPlanningAgent:
    """分页脚本分段规划 Agent：只生成故事节奏分段，不负责落库。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "script_planning_prompt.md",
        max_structured_retries: int = 3,
    ):
        """初始化规划 Agent；使用结构化输出约束 section_plan。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = "\n\n".join([
            PromptLoader.load_system(prompt_name),
            PromptLoader.load("script_visual_context_protocol.md"),
        ])
        logger.info("Initializing ScriptPlanningAgent prompt=%s", prompt_name)
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=StoryPacingResponse,
            name="script_planning_agent",
        )

    async def generate_section_plan(
        self,
        *,
        outline: str,
        total_pages: int,
        outline_characters: list[dict] | None = None,
        user_requirement: str = "",
        feedback: str = "",
        scene_catalog: list[dict] | None = None,
        target_page_no: int | None = None,
    ) -> list[dict]:
        """生成完整分段计划和每段视觉设定；校验和保存由 Service 负责。"""

        logger.info(
            "ScriptPlanningAgent generation started total_pages=%s outline_chars=%s character_count=%s requirement_chars=%s feedback_chars=%s",
            total_pages,
            len(outline),
            len(outline_characters or []),
            len(user_requirement),
            len(feedback),
        )
        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content=self._build_input(
                        outline=outline,
                        total_pages=total_pages,
                        outline_characters=outline_characters or [],
                        user_requirement=user_requirement,
                        feedback=feedback,
                        scene_catalog=scene_catalog or [],
                        target_page_no=target_page_no,
                    )
                )
            ],
            response_model=StoryPacingResponse,
            operation="script_section_plan",
            max_retries=self.max_structured_retries,
            validator=self._validate_response,
        )
        sections = [section.model_dump() for section in response.sections]
        logger.info("ScriptPlanningAgent generation completed section_count=%s", len(sections))
        return sections

    @staticmethod
    def _validate_response(response: StoryPacingResponse) -> None:
        """规划必须有分段和场景；无人分段的角色列表允许为空。"""

        if not response.sections:
            raise ValueError("ScriptPlanningAgent structured_response contains no sections.")
        for section in response.sections:
            if not section.scenes:
                raise ValueError(f"section {section.section_no} contains no scenes.")
            if not section.page_plan:
                raise ValueError(f"section {section.section_no} contains no page_plan.")

    @staticmethod
    def _build_input(
        *,
        outline: str,
        total_pages: int,
        outline_characters: list[dict],
        user_requirement: str,
        feedback: str,
        scene_catalog: list[dict] | None = None,
        target_page_no: int | None = None,
    ) -> str:
        """构造规划输入；feedback 用于校验失败后的完整重试。"""

        parts = [
            f"目标总页数：{total_pages}",
            "漫画大纲：",
            outline,
            "大纲阶段已确认的角色基准设定：",
            format_outline_characters(outline_characters),
            "用户补充要求：",
            user_requirement or "无",
            "可复用的固定地点目录（reference_subject_key 只能逐字选择 key，或新地点填写 null）：",
            json.dumps(scene_catalog or [], ensure_ascii=False),
        ]
        if target_page_no is not None:
            parts.append(f"本轮只规划第 {target_page_no} 页：仅返回一个 section，section_no=1，page_start=page_end={target_page_no}，不划分整部漫画节奏。")
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
        """读取当前设置页保存的模型配置，创建脚本规划 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
