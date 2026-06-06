import logging
from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.script_agent_models import ScriptSupervisorResponse
from backend.agents.script_prompt_formatters import (
    format_outline_characters,
    format_pages,
    format_scenes,
    format_section,
    format_section_characters,
)
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class ScriptSupervisorAgent:
    """分页脚本监督 Agent：只审查当前分段页面并输出逐页修改意见。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "script_supervisor_prompt.md",
        max_structured_retries: int = 3,
    ):
        """初始化监督 Agent；输出由 response_format 约束为 passed/reviews。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = PromptLoader.load(prompt_name)
        logger.info("Initializing ScriptSupervisorAgent prompt=%s", prompt_name)
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=ScriptSupervisorResponse,
            name="script_supervisor_agent",
        )

    async def review_section_pages(
        self,
        *,
        outline: str,
        current_section: dict,
        section_scenes: list[dict],
        section_characters: list[dict],
        outline_characters: list[dict],
        pages: list[dict],
    ) -> dict:
        """审查当前分段页面脚本；只关注本段内部内容质量。"""

        logger.info(
            "ScriptSupervisorAgent review started section_no=%s page_count=%s",
            current_section.get("section_no"),
            len(pages),
        )
        expected_page_nos = {
            int(page.get("page_no", 0))
            for page in pages
            if isinstance(page, dict) and int(page.get("page_no", 0)) > 0
        }
        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content=self._build_review_input(
                        outline=outline,
                        current_section=current_section,
                        section_scenes=section_scenes,
                        section_characters=section_characters,
                        outline_characters=outline_characters,
                        pages=pages,
                    )
                )
            ],
            response_model=ScriptSupervisorResponse,
            operation=f"script_supervisor_section_{current_section.get('section_no')}",
            max_retries=self.max_structured_retries,
            validator=lambda response: self._validate_response(
                response,
                expected_page_nos=expected_page_nos,
            ),
        )
        payload = response.model_dump()
        failed_count = sum(
            1
            for review in payload.get("reviews", [])
            if isinstance(review, dict) and not review.get("passed")
        )
        logger.info(
            "ScriptSupervisorAgent review completed section_no=%s review_count=%s failed_count=%s",
            current_section.get("section_no"),
            len(payload.get("reviews", [])),
            failed_count,
        )
        return payload

    @staticmethod
    def _validate_response(
        response: ScriptSupervisorResponse,
        *,
        expected_page_nos: set[int],
    ) -> None:
        """监督输出必须包含逐页审查结果，便于 Service 精确修订。"""

        if not response.reviews:
            raise ValueError("ScriptSupervisorAgent structured_response contains no reviews.")
        review_page_nos = [review.page_no for review in response.reviews]
        if len(review_page_nos) != len(set(review_page_nos)):
            raise ValueError("ScriptSupervisorAgent reviews contain duplicate page_no.")
        if expected_page_nos and set(review_page_nos) != expected_page_nos:
            raise ValueError(
                "ScriptSupervisorAgent reviews must cover every input page exactly; "
                f"expected={sorted(expected_page_nos)}, got={sorted(review_page_nos)}."
            )
        failed_reviews = [review for review in response.reviews if not review.passed]
        for review in failed_reviews:
            if not review.revision_suggestions:
                raise ValueError(
                    f"ScriptSupervisorAgent failed page {review.page_no} missing revision_suggestions."
                )

    @staticmethod
    def _build_review_input(
        *,
        outline: str,
        current_section: dict,
        section_scenes: list[dict],
        section_characters: list[dict],
        outline_characters: list[dict],
        pages: list[dict],
    ) -> str:
        """构造监督输入；只提供当前分段内容，避免审查跨段衔接。"""

        return "\n\n".join(
            [
                "任务模式：review_section_pages",
                "当前已锁定分段：",
                format_section(current_section),
                "当前分段中心化场景设定：",
                format_scenes(section_scenes),
                "当前分段角色细化设定：",
                format_section_characters(section_characters),
                "大纲阶段已确认的角色基准设定：",
                format_outline_characters(outline_characters),
                "待审查页面脚本：",
                format_pages(pages),
                "漫画大纲：",
                outline,
            ]
        )

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建脚本监督 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
