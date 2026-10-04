from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.agents.visual_agent_models import ShotPlanResponse, PromptLanguageResponse
from backend.models.enums import PromptLanguage
from backend.utils.json_utils import canonical_json
from backend.utils.prompt_loader import PromptLoader


class ShotPlannerAgent:
    """规划当前页镜头、动作和可见局部状态，不改写固定视觉设定。"""

    VERSION = "8"

    def __init__(
        self,
        *,
        llm: Any | None = None,
        system_prompt: str | None = None,
        language_system_prompt: str | None = None,
        max_structured_retries: int = 3,
    ):
        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = system_prompt or PromptLoader.load_system("shot_planner_prompt.md")
        self.language_prompt = language_system_prompt or PromptLoader.load_system("image_spec_language_prompt.md")
        self.reference_protocol = PromptLoader.load("shot_planner_reference_protocol.md")
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

        known_prop_keys = {str(item["key"]) for item in snapshot.get("prop_catalog", [])}

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
            if response.scene.background_visible and not response.scene.framing_notes.strip():
                raise ValueError("visible scene requires nonempty framing_notes for its current environment")

            # 唯一目录物品只能占据一个位置；集合去重会掩盖双持有或人物/场景冲突。
            prop_locations: dict[str, list[str]] = {}
            for subject_index, subject in enumerate(response.subjects):
                for prop_index, key in enumerate(subject.visible_prop_keys):
                    location = (
                        f"subjects[{subject_index}](character_key={subject.character_key})"
                        f".visible_prop_keys[{prop_index}]"
                    )
                    prop_locations.setdefault(key, []).append(location)
            for prop_index, key in enumerate(response.scene.visible_prop_keys):
                prop_locations.setdefault(key, []).append(f"scene.visible_prop_keys[{prop_index}]")
            unknown_props = set(prop_locations) - known_prop_keys
            if unknown_props:
                raise ValueError(
                    f"shot plan contains unknown prop keys: {sorted(unknown_props)}; "
                    f"allowed visible_prop_keys (prop_catalog): {sorted(known_prop_keys)}"
                )
            duplicate_locations = {
                key: locations for key, locations in prop_locations.items() if len(locations) > 1
            }
            if duplicate_locations:
                raise ValueError(
                    "shot plan assigns one catalog prop to multiple locations: "
                    + canonical_json(duplicate_locations)
                )

        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content="\n\n".join(
                        [
                            "本页结构化脚本：\n" + canonical_json(page),
                            "本页只读角色基准、当前造型和场景设定：\n" + canonical_json(snapshot),
                            "可用结构控制：\n" + canonical_json(available_controls),
                            # 目录限制是业务协议，必须独立于可编辑的数据库 Prompt 配置传入。
                            self.reference_protocol.format(
                                allowed_visible_prop_keys=canonical_json(sorted(known_prop_keys))
                            ),
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

    async def translate_prompt_components(self, components: dict[str, str], language: PromptLanguage) -> dict[str, str]:
        """沿用当前模型转换最终文本，不改动镜头、绑定或原始视觉事实。"""
        agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.language_prompt,
            response_model=PromptLanguageResponse,
            name="shot_planner_prompt_language",
        )

        def validate(response: PromptLanguageResponse) -> None:
            if any(not value.strip() for value in response.model_dump().values()):
                raise ValueError("Translated prompt components must not be empty")

        response = await ainvoke_structured_with_retries(
            agent=agent,
            messages=[HumanMessage(content=canonical_json({"output_language": language.value, "components": components}))],
            response_model=PromptLanguageResponse,
            operation="image_spec_prompt_language",
            max_retries=self.max_structured_retries,
            validator=validate,
        )
        return response.model_dump()

    @staticmethod
    def _default_llm() -> Any:
        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
