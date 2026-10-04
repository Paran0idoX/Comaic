"""提炼稳定的参考图视觉事实；不写库、不生成图片、不使用会话记忆。"""

import json
from langchain_core.messages import HumanMessage
from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.models.enums import ReferenceProfileKind
from backend.models.reference_visual import ReferenceVisualExtraction, FixedSceneVisualExtraction
from backend.utils.prompt_loader import PromptLoader


class ReferenceVisualAgent:
    def __init__(self, llm=None):
        if llm is None:
            from backend.llm_clients.factory import get_tool_chat_model
            from backend.i18n.errors import AppError
            try:
                llm = get_tool_chat_model()
            except ValueError as exc:
                raise AppError("reference.profile_model_missing", status_code=422) from exc
        self.llm = llm
        self.agent = create_structured_agent(model=llm,
            system_prompt=PromptLoader.load("reference_visual_extraction_prompt.md"),
            response_model=ReferenceVisualExtraction, name="reference_visual_agent")

    async def extract(self, sources, cached):
        """一个对象一次调用补齐缺失摘要；缓存身份只作只读上下文。"""
        from backend.services.reference_visual_profile_service import validate_extraction
        agent, response_model = self.agent, ReferenceVisualExtraction
        # 场景目录统一在 schema 层排除人物/临时状态类型，不根据历史版本放宽规则。
        if sources and all(source["kind"] == ReferenceProfileKind.SCENE_SUBJECT.value for source in sources):
            response_model = FixedSceneVisualExtraction
            agent = create_structured_agent(model=self.llm,
                system_prompt=PromptLoader.load("reference_visual_extraction_prompt.md"),
                response_model=response_model, name="reference_visual_agent")
        result = await ainvoke_structured_with_retries(agent,
            messages=[HumanMessage(content=json.dumps({"sources": sources, "cached_profiles": cached}, ensure_ascii=False))],
            response_model=response_model, operation="reference_visual_profiles",
            validator=lambda response: validate_extraction(response, sources), max_retries=3)
        return ReferenceVisualExtraction.model_validate(result.model_dump(mode="json"))
