import logging
from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.script_agent_models import PageScriptWriterResponse
from backend.agents.script_prompt_formatters import (
    format_outline_characters,
    format_pages,
    format_previous_context,
    format_scenes,
    format_section,
    format_section_characters,
)
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class PageScriptWriterAgent:
    """分页脚本编写 Agent：只生成当前已锁定分段的页面脚本，不生成视觉设定。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "script_writer_prompt.md",
        max_structured_retries: int = 3,
    ):
        """初始化页面脚本编写 Agent；输出由 response_format 约束为 pages。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = PromptLoader.load(prompt_name)
        logger.info("Initializing PageScriptWriterAgent prompt=%s", prompt_name)
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=PageScriptWriterResponse,
            name="page_script_writer_agent",
        )

    async def generate_page(
        self,
        *,
        outline: str,
        total_pages: int,
        current_section: dict,
        target_page_no: int,
        section_scenes: list[dict],
        section_characters: list[dict],
        previous_context: dict,
        outline_characters: list[dict],
        user_requirement: str = "",
        feedback: str = "",
        is_revision: bool = False,
        current_pages: list[dict] | None = None,
    ) -> list[dict]:
        """生成或修订单页脚本；调用方负责页码、引用和落库校验。"""

        logger.info(
            "PageScriptWriterAgent page generation started section_no=%s page_no=%s is_revision=%s feedback_chars=%s",
            current_section.get("section_no"),
            target_page_no,
            is_revision,
            len(feedback),
        )
        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content=self._build_section_input(
                        outline=outline,
                        total_pages=total_pages,
                        current_section=current_section,
                        target_page_no=target_page_no,
                        section_scenes=section_scenes,
                        section_characters=section_characters,
                        previous_context=previous_context,
                        outline_characters=outline_characters,
                        user_requirement=user_requirement,
                        feedback=feedback,
                        is_revision=is_revision,
                        current_pages=current_pages or [],
                    )
                )
            ],
            response_model=PageScriptWriterResponse,
            operation=f"page_script_writer_section_{current_section.get('section_no')}",
            max_retries=self.max_structured_retries,
            validator=self._validate_response,
        )
        pages = [page.model_dump() for page in response.pages]
        logger.info(
            "PageScriptWriterAgent page generation completed section_no=%s page_no=%s page_count=%s",
            current_section.get("section_no"),
            target_page_no,
            len(pages),
        )
        return pages

    @staticmethod
    def _validate_response(response: PageScriptWriterResponse) -> None:
        """页面编写至少需要返回一页；具体页码范围由 Service 做权威校验。"""

        if not response.pages:
            raise ValueError("PageScriptWriterAgent structured_response contains no pages.")

    @staticmethod
    def _build_section_input(
        *,
        outline: str,
        total_pages: int,
        current_section: dict,
        target_page_no: int,
        section_scenes: list[dict],
        section_characters: list[dict],
        previous_context: dict,
        outline_characters: list[dict],
        user_requirement: str,
        feedback: str,
        is_revision: bool,
        current_pages: list[dict],
    ) -> str:
        """构造单页脚本输入；用自然语言说明替代原始 JSON。"""

        if is_revision:
            mode_text = "监督修订：只输出当前目标页的修订稿。"
            current_pages_text = (
                format_pages(current_pages)
                if current_pages
                else "没有可用的最近页面上下文。"
            )
        else:
            mode_text = "逐页生成：只输出当前目标页。"
            current_pages_text = (
                format_pages(current_pages)
                if current_pages
                else "当前分段还没有已生成的前序页面。"
            )

        return "\n\n".join(
            [
                "任务模式：batch_single_page",
                f"当前模式：{mode_text}",
                f"本次唯一允许输出页码：{target_page_no}",
                f"总页数：{total_pages}",
                "当前需要生成的已锁定分段：",
                format_section(current_section),
                "当前分段可引用的中心化场景设定：",
                format_scenes(section_scenes),
                "当前分段可引用的角色细化设定：",
                format_section_characters(section_characters),
                "大纲阶段已确认的角色基准设定：",
                format_outline_characters(outline_characters),
                "先前已完成分段上下文：",
                format_previous_context(previous_context),
                "漫画大纲：",
                outline,
                "当前分段最近页面上下文（最多 5 页，用于当前页衔接参考，禁止重复输出这些页面）：",
                current_pages_text,
                "用户补充要求：",
                user_requirement or "无",
                "上一次校验或监督反馈：",
                feedback or "无",
            ]
        )

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建脚本生成 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
