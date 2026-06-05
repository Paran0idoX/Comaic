import json
import logging
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage

from backend.agents.script_agent_models import (
    ScriptDeepAgentResponse,
    PageScriptWriterResponse,
    ScriptSupervisorResponse,
)
from backend.agents.deepagent_profiles import ensure_comaic_deepagent_profile
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class ScriptDeepAgent:
    """DeepAgents 分页脚本主 Agent，负责基于已锁定分段编写和监督脚本。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        main_prompt_name: str = "script_deep_main_prompt.md",
        writer_prompt_name: str = "script_writer_prompt.md",
        supervisor_prompt_name: str = "script_supervisor_prompt.md",
        max_structured_retries: int = 3,
        recursion_limit: int = 80,
    ):
        """初始化 Deep Agent 和页面编写/监督两个子 Agent。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.recursion_limit = recursion_limit
        logger.info("Initializing ScriptDeepAgent")
        self.main_prompt = PromptLoader.load(main_prompt_name)
        self.writer_prompt = PromptLoader.load(writer_prompt_name)
        self.supervisor_prompt = PromptLoader.load(supervisor_prompt_name)
        self._agent = self._create_agent()

    def _create_agent(self, *, tools: list[Any] | None = None):
        """创建 DeepAgents 实例，并隐藏脚本生成不需要的内置工具。"""

        # tools=[] 只表示不额外添加工具；DeepAgents 内置工具需要通过 HarnessProfile 禁用。
        ensure_comaic_deepagent_profile()
        return create_deep_agent(
            model=self.llm,
            tools=tools or [],
            system_prompt=self.main_prompt,
            response_format=ScriptDeepAgentResponse,
            subagents=[
                {
                    "name": "page_script_writer_agent",
                    "description": "根据大纲、分段计划和审查意见编写或修订分页漫画脚本。",
                    "system_prompt": self.writer_prompt,
                    "model": self.llm,
                    "response_format": PageScriptWriterResponse,
                },
                {
                    "name": "script_supervisor_agent",
                    "description": "审查分页脚本是否符合大纲、分段目标、页码连续性和段落衔接。",
                    "system_prompt": self.supervisor_prompt,
                    "model": self.llm,
                    "response_format": ScriptSupervisorResponse,
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
        parsed = await self._invoke_structured_response(
            operation="single_page",
            user_input=self._build_single_page_input(
                outline=outline,
                total_pages=total_pages,
                page_no=page_no,
                user_requirement=user_requirement,
            ),
        )
        logger.info(
            "ScriptDeepAgent single generation completed page_count=%s review_count=%s",
            len(parsed.get("pages", [])),
            len(parsed.get("reviews", [])),
        )
        return parsed

    async def generate_section(
        self,
        *,
        outline: str,
        total_pages: int,
        current_section: dict,
        previous_context: dict,
        user_requirement: str = "",
        feedback: str = "",
    ) -> dict[str, Any]:
        """生成单个已锁定分段的页面脚本，避免 Agent 自行回头处理其他分段。"""

        logger.info(
            "ScriptDeepAgent section generation started section_no=%s page_range=%s-%s total_pages=%s feedback_chars=%s",
            current_section.get("section_no"),
            current_section.get("page_start"),
            current_section.get("page_end"),
            total_pages,
            len(feedback),
        )
        parsed = await self._invoke_structured_response(
            operation=f"section_{current_section.get('section_no')}",
            user_input=self._build_section_input(
                outline=outline,
                total_pages=total_pages,
                current_section=current_section,
                previous_context=previous_context,
                user_requirement=user_requirement,
                feedback=feedback,
            ),
        )
        logger.info(
            "ScriptDeepAgent section generation completed section_no=%s page_count=%s review_count=%s",
            current_section.get("section_no"),
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
    def _build_section_input(
        *,
        outline: str,
        total_pages: int,
        current_section: dict,
        previous_context: dict,
        user_requirement: str,
        feedback: str,
    ) -> str:
        """构造单分段生成输入；历史上下文只用于衔接，不允许生成历史分段。"""

        return "\n\n".join(
            [
                "任务模式：batch_section",
                f"总页数：{total_pages}",
                "当前需要生成的已锁定分段：",
                json.dumps(current_section, ensure_ascii=False),
                "先前已完成分段上下文：",
                json.dumps(previous_context, ensure_ascii=False),
                "漫画大纲：",
                outline,
                "用户补充要求：",
                user_requirement or "无",
                "上一次校验失败反馈：",
                feedback or "无",
            ]
        )

    async def _invoke_structured_response(
        self,
        *,
        operation: str,
        user_input: str,
    ) -> dict[str, Any]:
        """调用通用结构化输出封装，并保留脚本 Agent 自己的业务校验。"""

        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[HumanMessage(content=user_input)],
            response_model=ScriptDeepAgentResponse,
            operation=operation,
            max_retries=self.max_structured_retries,
            config={
                "recursion_limit": self.recursion_limit,
                "metadata": {
                    "agent": "script_deep_agent",
                    "operation": operation,
                    "recursion_limit": self.recursion_limit,
                },
            },
            validator=self._validate_structured_response,
        )
        logger.debug(
            "ScriptDeepAgent structured response validated page_count=%s review_count=%s",
            len(response.pages),
            len(response.reviews),
        )
        return response.model_dump()

    @staticmethod
    def _validate_structured_response(response: ScriptDeepAgentResponse) -> None:
        """脚本生成必须至少返回一页，页码范围等细节继续交给 Service 校验。"""

        if not response.pages:
            raise ValueError("ScriptDeepAgent structured_response contains no pages.")

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建脚本生成 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
