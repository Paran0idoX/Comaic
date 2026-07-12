from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.agents.visual_agent_models import ShotPlanResponse
from backend.utils.json_utils import canonical_json
from backend.utils.prompt_loader import PromptLoader


class ShotPlannerAgent:
    """只决定当前页需要创造的镜头和动作，不复制视觉真值。"""

    VERSION = "1"

    def __init__(
        self,
        *,
        llm: Any | None = None,
        system_prompt: str | None = None,
        max_structured_retries: int = 3,
    ):
        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = system_prompt or PromptLoader.load("shot_planner_prompt.md")
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=ShotPlanResponse,
            name="shot_planner_agent",
        )

    async def plan(
        self,
        *,
        page: dict,
        snapshot: dict,
        available_controls: list[str],
    ) -> dict:
        known_character_keys = {
            str(character.get("character_key", ""))
            for character in snapshot.get("characters", [])
        }

        def validate(response: ShotPlanResponse) -> None:
            planned_character_keys = {
                subject.character_key for subject in response.subjects
            }
            unknown = planned_character_keys - known_character_keys
            if unknown:
                raise ValueError(f"shot plan contains unknown character keys: {sorted(unknown)}")
            missing = known_character_keys - planned_character_keys
            if missing:
                raise ValueError(f"shot plan omits page characters: {sorted(missing)}")

        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content="\n\n".join(
                        [
                            "本页结构化脚本：\n" + canonical_json(page),
                            "本页只读视觉状态：\n" + canonical_json(snapshot),
                            "可用结构控制：\n" + canonical_json(available_controls),
                        ]
                    )
                )
            ],
            response_model=ShotPlanResponse,
            operation=f"shot_plan_page_{page.get('page_no')}",
            max_retries=self.max_structured_retries,
            validator=validate,
        )
        plan = response.model_dump(mode="json")
        available = {str(value).strip() for value in available_controls if str(value).strip()}
        dropped: set[str] = set()

        # 模型偶尔会无视 Prompt 请求 ControlNet 等当前页面并不存在的控制图。
        # 这些要求不是镜头语义本身，确定性剔除后保留告警，比重复调用模型更可靠。
        for subject in plan.get("subjects", []):
            requested = {
                str(value).strip()
                for value in subject.get("control_requirements", [])
                if str(value).strip()
            }
            dropped.update(requested - available)
            subject["control_requirements"] = sorted(requested & available)
        scene = plan.get("scene") or {}
        requested = {
            str(value).strip()
            for value in scene.get("control_requirements", [])
            if str(value).strip()
        }
        dropped.update(requested - available)
        scene["control_requirements"] = sorted(requested & available)
        if dropped:
            controls = ", ".join(sorted(dropped))
            plan["warnings"] = [
                {
                    "code": "shot_plan.control_unavailable",
                    "message": f"Dropped unavailable shot controls: {controls}.",
                }
            ]
        else:
            plan["warnings"] = []
        return plan

    @staticmethod
    def _default_llm() -> Any:
        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
