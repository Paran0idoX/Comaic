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
            requested = {
                requirement
                for subject in response.subjects
                for requirement in subject.control_requirements
            } | set(response.scene.control_requirements)
            unsupported = requested - set(available_controls)
            if unsupported:
                raise ValueError(f"shot plan requests unavailable controls: {sorted(unsupported)}")

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
        return response.model_dump(mode="json")

    @staticmethod
    def _default_llm() -> Any:
        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
