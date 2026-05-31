import json
import logging
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.agents.script_agent_models import (
    ScriptDeepAgentResponse,
    PageScriptWriterResponse,
    ScriptSupervisorResponse,
)
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
    ):
        """初始化 Deep Agent 和页面编写/监督两个子 Agent。"""

        self.llm = llm or self._default_llm()
        logger.info("Initializing ScriptDeepAgent")
        self.main_prompt = PromptLoader.load(main_prompt_name)
        self.writer_prompt = PromptLoader.load(writer_prompt_name)
        self.supervisor_prompt = PromptLoader.load(supervisor_prompt_name)
        self._agent = self._create_agent()

    def _create_agent(self, *, tools: list[Any] | None = None):
        """创建 DeepAgents 实例；实时生成时会额外挂载本地提交工具。"""

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
        parsed = self._parse_agent_result(result)
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
        result = await self._agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=self._build_section_input(
                            outline=outline,
                            total_pages=total_pages,
                            current_section=current_section,
                            previous_context=previous_context,
                            user_requirement=user_requirement,
                            feedback=feedback,
                        )
                    )
                ]
            }
        )
        parsed = self._parse_agent_result(result)
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

    def _parse_agent_result(self, result_state: dict[str, Any]) -> dict[str, Any]:
        """解析 DeepAgents 最终结果，优先读取结构化响应，避免自然语言收尾解析失败。"""

        structured_response = result_state.get("structured_response")
        if isinstance(structured_response, ScriptDeepAgentResponse):
            logger.debug("ScriptDeepAgent structured response parsed")
            return structured_response.model_dump()
        if isinstance(structured_response, dict):
            logger.debug("ScriptDeepAgent structured response dict parsed")
            return structured_response
        if hasattr(structured_response, "model_dump"):
            logger.debug("ScriptDeepAgent generic structured response parsed")
            return structured_response.model_dump()

        file_text = self._final_output_file_text(result_state.get("files", {}))
        if file_text:
            logger.debug("ScriptDeepAgent final_output file chars=%s", len(file_text))
            return self._loads_json_text(file_text)

        return self._parse_json_result(result_state["messages"])

    def _parse_json_result(self, messages: list[BaseMessage]) -> dict[str, Any]:
        """从 Agent 最终消息中解析 JSON，兼容代码块包裹。"""

        text = self._last_ai_message(messages)
        logger.debug("ScriptDeepAgent raw result chars=%s", len(text))
        return self._loads_json_text(text)

    def _loads_json_text(self, text: str) -> dict[str, Any]:
        """把 JSON 文本解析成字典，统一做类型校验。"""

        json_text = self._extract_json_text(text)
        result = json.loads(json_text)
        if not isinstance(result, dict):
            raise ValueError("ScriptDeepAgent result must be a JSON object.")
        logger.debug("ScriptDeepAgent parsed result keys=%s", list(result.keys()))
        return result

    @staticmethod
    def _final_output_file_text(files: dict[str, Any]) -> str | None:
        """DeepAgents 可能把最终 JSON 写入 /final_output.json，这里兼容读取。"""

        for path in ("/final_output.json", "final_output.json"):
            file_data = files.get(path)
            if isinstance(file_data, dict):
                content = file_data.get("content")
                if isinstance(content, str) and content.strip():
                    return content
            if isinstance(file_data, str) and file_data.strip():
                return file_data
        return None

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

        from backend.llm_clients.deepseek import deepseek_tool_chat_model

        return deepseek_tool_chat_model
