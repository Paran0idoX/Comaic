"""根据角色视觉真值确定性编译人物参考图 Prompt，不调用 LLM。"""

from __future__ import annotations

import json
from typing import Any

from backend.models.comic import OutlineCharacter, OutfitVariant, StyleProfile
from backend.models.enums import ImagePromptType, VisualAssetRole
from backend.utils.prompt_loader import PromptLoader


REFERENCE_ROLES = (
    VisualAssetRole.IDENTITY_FACE,
    VisualAssetRole.IDENTITY_HALF_BODY,
    VisualAssetRole.IDENTITY_FULL_BODY,
)

NATURAL_FRAMING = {
    VisualAssetRole.IDENTITY_FACE: (
        "a front-facing head-and-shoulders portrait with the face large and unobstructed"
    ),
    VisualAssetRole.IDENTITY_HALF_BODY: (
        "a front-facing waist-up portrait with both shoulders, arms, and clothing visible"
    ),
    VisualAssetRole.IDENTITY_FULL_BODY: (
        "a front-facing head-to-toe full-body view with the entire silhouette inside the frame"
    ),
    VisualAssetRole.IDENTITY_SIDE: "a full-body side profile with the entire figure visible and the same outfit",
    VisualAssetRole.IDENTITY_BACK: "a full-body rear view showing the hairstyle, outfit back, and entire silhouette",
}

TAG_FRAMING = {
    VisualAssetRole.IDENTITY_FACE: "front-facing, headshot, head and shoulders, face focus",
    VisualAssetRole.IDENTITY_HALF_BODY: "front-facing, waist up, upper body, clothing visible",
    VisualAssetRole.IDENTITY_FULL_BODY: "front-facing, full body, head to toe, entire silhouette",
    VisualAssetRole.IDENTITY_SIDE: "full body, side view, profile, entire silhouette",
    VisualAssetRole.IDENTITY_BACK: "full body, back view, rear view, entire silhouette",
}


class CharacterReferencePromptService:
    """把角色基准字段与一个可选的已批准风格编译成三件套 Prompt。"""

    def __init__(self) -> None:
        self.natural_template = PromptLoader.load(
            "character_reference_natural_prompt.md"
        ).strip()
        self.tag_template = PromptLoader.load(
            "character_reference_tag_prompt.md"
        ).strip()
        self.natural_negative_template = PromptLoader.load(
            "character_reference_natural_negative_prompt.md"
        ).strip()
        self.tag_negative_template = PromptLoader.load(
            "character_reference_tag_negative_prompt.md"
        ).strip()

    def compile(
        self,
        *,
        character: OutlineCharacter,
        prompt_type: ImagePromptType,
        style: StyleProfile | None = None,
        roles: tuple[VisualAssetRole, ...] | None = None,
        outfit: OutfitVariant | None = None,
    ) -> dict[str, dict[str, str]]:
        """返回以 VisualAssetRole.value 为键的正负 Prompt 快照。"""

        style_values = self._style_values(style)
        common = {
            "appearance": self._text(character.appearance),
            "visual_anchors": self._text(character.visual_anchors),
            "hairstyle": self._text(character.default_hairstyle),
            "clothing": self._text(character.default_clothing),
            "accessories": self._text(character.default_accessories),
            "color_palette": self._text(character.default_color_palette),
            "negative_constraints": self._text(character.negative_constraints),
        }
        if outfit is not None:
            common["clothing"] = self._join(self._json_list(outfit.garment_components_json), "; ") or common["clothing"]
            common["accessories"] = self._join(self._json_list(outfit.accessories_json), "; ") or common["accessories"]
            common["color_palette"] = self._join(self._json_list(outfit.colors_json), ", ") or common["color_palette"]
            common["negative_constraints"] = self._join([common["negative_constraints"], outfit.negative_constraints], "; ")
        result: dict[str, dict[str, str]] = {}
        for role in roles or REFERENCE_ROLES:
            natural_positive = self.natural_template.format(
                framing=NATURAL_FRAMING[role],
                style=style_values["positive_natural"],
                **common,
            )
            tag_positive = self.tag_template.format(
                framing=TAG_FRAMING[role],
                style=style_values["positive_tag"],
                **common,
            )
            natural_negative = self.natural_negative_template.format(
                negative_constraints=common["negative_constraints"],
                style_negative=style_values["negative_natural"],
            )
            tag_negative = self.tag_negative_template.format(
                negative_constraints=common["negative_constraints"],
                style_negative=style_values["negative_tag"],
            )
            result[role.value] = {
                "positive": self._combine(prompt_type, natural_positive, tag_positive),
                "negative": self._combine(prompt_type, natural_negative, tag_negative),
            }
        return result

    @classmethod
    def _style_values(cls, style: StyleProfile | None) -> dict[str, str]:
        if style is None:
            return {
                "positive_natural": "not specified",
                "negative_natural": "none",
                "positive_tag": "",
                "negative_tag": "",
            }
        palette = cls._json_list(style.color_palette_json)
        natural_parts = [style.positive_natural_language]
        if palette:
            natural_parts.append(f"color palette: {', '.join(palette)}")
        if style.lighting:
            natural_parts.append(f"lighting: {style.lighting}")
        tag_parts = [style.positive_tag, *palette, style.lighting]
        return {
            "positive_natural": cls._join(natural_parts, "; ") or "not specified",
            "negative_natural": cls._text(style.negative_natural_language),
            "positive_tag": cls._join(tag_parts, ", "),
            "negative_tag": cls._text(style.negative_tag),
        }

    @staticmethod
    def _combine(
        prompt_type: ImagePromptType,
        natural: str,
        tags: str,
    ) -> str:
        if prompt_type == ImagePromptType.NATURAL_LANGUAGE:
            return natural.strip()
        if prompt_type == ImagePromptType.TAG:
            return tags.strip(" ,\n")
        tag_text = tags.strip(" ,\n")
        return f"{natural.strip()}\n{tag_text}".rstrip()

    @staticmethod
    def _text(value: Any) -> str:
        normalized = str(value or "").strip()
        return normalized or "not specified"

    @staticmethod
    def _join(values: list[Any], delimiter: str) -> str:
        return delimiter.join(
            text for value in values if (text := str(value or "").strip())
        )

    @staticmethod
    def _json_list(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]
