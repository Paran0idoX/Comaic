from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.agents.visual_agent_models import ContinuityEventResponse
from backend.utils.json_utils import canonical_json
from backend.utils.prompt_loader import PromptLoader


class ContinuityEventAgent:
    """从完整分页脚本提取持久变化；不负责状态计算和落库。"""

    VERSION = "1"

    def __init__(self, *, llm: Any | None = None, max_structured_retries: int = 3):
        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = PromptLoader.load("continuity_event_prompt.md")
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=ContinuityEventResponse,
            name="continuity_event_agent",
        )

    async def extract(
        self,
        *,
        pages: list[dict],
        characters: list[dict],
        scenes: list[dict],
        outfits: list[dict],
        validation_feedback: str | None = None,
    ) -> list[dict]:
        message_parts = [
            "已知角色：\n" + canonical_json(characters),
            "已知场景：\n" + canonical_json(scenes),
            "已知服装版本：\n" + canonical_json(outfits),
            "完整分页脚本：\n" + canonical_json(pages),
        ]
        if validation_feedback:
            message_parts.append(
                "上一轮事件通过结构校验后未能通过确定性状态机校验。"
                "请依据以下错误重新生成完整 events，不要只返回局部修补：\n"
                + validation_feedback
            )
        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content="\n\n".join(message_parts)
                )
            ],
            response_model=ContinuityEventResponse,
            operation="continuity_event_extraction",
            max_retries=self.max_structured_retries,
            validator=self._validate_response,
        )
        return [event.model_dump(mode="json") for event in response.events]

    @staticmethod
    def _validate_response(response: ContinuityEventResponse) -> None:
        seen: set[tuple[int, int]] = set()
        for event in response.events:
            key = (event.page_no, event.sequence_no)
            if key in seen:
                raise ValueError(f"duplicate continuity event sequence: {key}")
            seen.add(key)
            if not event.target_key.strip():
                raise ValueError("continuity event target_key cannot be empty")

    @staticmethod
    def _default_llm() -> Any:
        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
