import logging
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class OutlineCharacterItem(BaseModel):
    """大纲阶段的角色基准设定。"""

    character_key: str = Field(description="稳定角色 key，后续脚本阶段复用。")
    name: str = Field(description="角色名称。")
    role: str = Field(description="角色身份或叙事功能。")
    background: str = Field(description="角色背景设定。")
    appearance: str = Field(description="固定样貌、年龄感、体型、五官等不常变化内容。")
    visual_anchors: str = Field(description="跨分段必须保留的角色识别锚点。")
    negative_constraints: str = Field(description="角色不应被改写或混淆的内容。")
    default_hairstyle: str = Field(description="默认发型；脚本分段可按剧情覆盖。")
    default_clothing: str = Field(description="默认服装；脚本分段可按剧情覆盖。")
    default_accessories: str = Field(description="默认配件；脚本分段可按剧情覆盖。")
    default_color_palette: str = Field(description="默认角色色彩；脚本分段可按剧情覆盖。")


class OutlineCharacterResponse(BaseModel):
    """大纲角色基准设定 Agent 的结构化输出。"""

    characters: list[OutlineCharacterItem] = Field(default_factory=list)


class OutlineCharacterAgent:
    """根据大纲版本生成角色基准设定，不负责落库。"""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        prompt_name: str = "outline_character_prompt.md",
        max_structured_retries: int = 3,
    ):
        """初始化角色基准 Agent，使用 response_format 约束输出。"""

        self.llm = llm or self._default_llm()
        self.max_structured_retries = max_structured_retries
        self.prompt = PromptLoader.load(prompt_name)
        self._agent = create_structured_agent(
            model=self.llm,
            system_prompt=self.prompt,
            response_model=OutlineCharacterResponse,
            name="outline_character_agent",
        )

    async def generate_characters(
        self,
        *,
        outline: str,
        previous_characters: list[dict] | None = None,
        user_message: str = "",
    ) -> list[dict]:
        """生成角色基准设定；调用方负责保存到 outline_character。"""

        response = await ainvoke_structured_with_retries(
            self._agent,
            messages=[
                HumanMessage(
                    content=self._build_input(
                        outline=outline,
                        previous_characters=previous_characters or [],
                        user_message=user_message,
                    )
                )
            ],
            response_model=OutlineCharacterResponse,
            operation="outline_characters",
            max_retries=self.max_structured_retries,
            validator=self._validate_response,
        )
        characters = [character.model_dump() for character in response.characters]
        logger.info("OutlineCharacterAgent generated character_count=%s", len(characters))
        return characters

    @staticmethod
    def _validate_response(response: OutlineCharacterResponse) -> None:
        """允许早期大纲没有角色，但一旦输出角色就必须有关键识别字段。"""

        for character in response.characters:
            if not character.character_key.strip():
                raise ValueError("outline character missing character_key")
            if not character.name.strip():
                raise ValueError("outline character missing name")
            if not character.appearance.strip():
                raise ValueError("outline character missing appearance")

    @staticmethod
    def _build_input(
        *,
        outline: str,
        previous_characters: list[dict],
        user_message: str,
    ) -> str:
        """整理角色生成输入，保留已有 key 便于 Agent 稳定复用。"""

        return "\n\n".join(
            [
                "当前大纲：",
                outline or "暂无。",
                "已有角色基准设定：",
                str(previous_characters or "暂无。"),
                "本轮用户输入：",
                user_message or "无。",
            ]
        )

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建大纲阶段 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
