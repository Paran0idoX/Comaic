import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from backend.agents.agent_factory import create_structured_agent
from backend.agents.structured_output import ainvoke_structured_with_retries
from backend.models.enums import OutlineEntityKind
from backend.utils.prompt_loader import PromptLoader


logger = logging.getLogger(__name__)


class OutlineCharacterItem(BaseModel):
    """大纲阶段的角色基准设定。"""

    character_key: str = Field(description="稳定角色 key，后续脚本阶段复用。")
    name: str = Field(description="角色名称。")
    role: str = Field(description="独立故事参与者的身份或叙事功能，不能仅因剧情重要就把设定当成角色。")
    background: str = Field(description="角色背景设定。")
    appearance: str = Field(description="固定样貌、年龄感、体型、五官等不常变化内容。")
    negative_constraints: str = Field(description="角色不应被改写或混淆的内容。")
    default_hairstyle: str = Field(description="默认发型；脚本分段可按剧情覆盖。")
    default_clothing: str = Field(description="默认服装；脚本分段可按剧情覆盖。")
    default_accessories: str = Field(description="默认配件；脚本分段可按剧情覆盖。")
    default_color_palette: str = Field(description="默认角色色彩；脚本分段可按剧情覆盖。")


class OutlineEntityCandidate(BaseModel):
    """先判断实体类别，只有独立角色可以附带角色基准设定。"""

    name: str = Field(description="大纲实体名称，与角色设定名称一致。")
    kind: OutlineEntityKind = Field(description="角色、普通道具、场景或抽象设定。动物、机器人和拟人角色可以是 character。")
    classification_reason: str = Field(description="分类依据；角色需说明其独立身份和形象，其他实体需说明为何不是角色。")
    character: OutlineCharacterItem | None = Field(description="仅 character 类别填写角色设定；其他类别必须为 null。")


class OutlineCharacterResponse(BaseModel):
    """同一次调用完成分类和设定；临时分类信息不进入数据库或公开 API。"""

    entities: list[OutlineEntityCandidate] = Field(description="已分类的大纲实体候选；早期大纲可以为空。")


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
        self.prompt = PromptLoader.load_system(prompt_name)
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
        characters = [
            entity.character.model_dump()
            for entity in response.entities
            if entity.kind == OutlineEntityKind.CHARACTER and entity.character is not None
        ]
        logger.info("OutlineCharacterAgent generated character_count=%s", len(characters))
        return characters

    @staticmethod
    def _validate_response(response: OutlineCharacterResponse) -> None:
        """分类矛盾和身份字段缺失都交给同一 Agent 重试，不靠名称黑名单删角色。"""

        keys: set[str] = set()
        for entity in response.entities:
            if not entity.name.strip() or not entity.classification_reason.strip():
                raise ValueError("outline entity requires a name and classification_reason")
            if entity.kind != OutlineEntityKind.CHARACTER:
                if entity.character is not None:
                    raise ValueError(f"{entity.name}: {entity.kind.value} is not a character; character must be null")
                continue
            character = entity.character
            if character is None:
                raise ValueError(f"{entity.name}: character entity requires character settings")
            if not character.character_key.strip():
                raise ValueError("outline character missing character_key")
            if not character.name.strip():
                raise ValueError("outline character missing name")
            if not character.appearance.strip():
                raise ValueError("outline character missing appearance")
            if entity.name.strip() != character.name.strip():
                raise ValueError("outline entity name must match character name")
            key = character.character_key.strip()
            if key in keys:
                raise ValueError(f"outline character has duplicate character_key: {key}")
            keys.add(key)

    @staticmethod
    def _build_input(
        *,
        outline: str,
        previous_characters: list[dict],
        user_message: str,
    ) -> str:
        """历史记录只是待重新分类的候选，不能因为已有 key 就继续当作角色。"""

        return "\n\n".join(
            [
                "当前大纲：",
                outline or "暂无。",
                "历史角色记录（待重新判断的候选，不保证都是合法角色）：",
                json.dumps(previous_characters, ensure_ascii=False) if previous_characters else "暂无。",
                "本轮用户输入：",
                user_message or "无。",
            ]
        )

    @staticmethod
    def _default_llm() -> Any:
        """读取当前设置页保存的模型配置，创建大纲阶段 ChatModel。"""

        from backend.llm_clients.factory import get_tool_chat_model

        return get_tool_chat_model()
