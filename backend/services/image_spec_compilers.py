from dataclasses import dataclass
import re
from typing import Any

from backend.models.enums import (
    GenerationMode,
    ImagePromptType,
    VisualAssetRole,
    WorkflowCapability,
)
from backend.utils.json_utils import canonical_hash


IDENTITY_REFERENCE_ROLES = {
    VisualAssetRole.IDENTITY_FACE.value,
    VisualAssetRole.IDENTITY_HALF_BODY.value,
    VisualAssetRole.IDENTITY_FULL_BODY.value,
}
OUTFIT_REFERENCE_ROLES = {
    VisualAssetRole.OUTFIT_FRONT.value,
    VisualAssetRole.OUTFIT_BACK.value,
    VisualAssetRole.OUTFIT_DETAIL.value,
}
SCENE_REFERENCE_ROLES = {
    VisualAssetRole.SCENE_MASTER.value,
    VisualAssetRole.PROP_REFERENCE.value,
}
SCENE_ROLES = {
    *SCENE_REFERENCE_ROLES,
    VisualAssetRole.DEPTH.value,
    VisualAssetRole.CANNY.value,
    VisualAssetRole.LINEART.value,
    VisualAssetRole.SEGMENTATION.value,
}
STYLE_ROLES = {VisualAssetRole.STYLE_REFERENCE.value}
CONTROL_CAPABILITY_BY_ROLE = {
    VisualAssetRole.POSE.value: WorkflowCapability.POSE.value,
    VisualAssetRole.DEPTH.value: WorkflowCapability.DEPTH.value,
    VisualAssetRole.CANNY.value: WorkflowCapability.CANNY.value,
    VisualAssetRole.LINEART.value: WorkflowCapability.LINEART.value,
}

SINGLE_FRAME_TAGS = (
    "standalone borderless cinematic splash illustration, full-bleed continuous scenery, "
    "one uninterrupted moment, one camera perspective, clean edge-to-edge composition"
)
SINGLE_FRAME_INSTRUCTION = (
    "Create a standalone borderless cinematic splash illustration that fills the canvas "
    "edge to edge with one continuous moment from one camera perspective; image content "
    "touches all four canvas edges with no white margin, mat, frame, or border"
)
NO_TEXT_TAGS = (
    "plain bare uninterrupted surfaces, featureless weathered walls, "
    "purely visual storytelling, typography-free composition"
)
NO_TEXT_INSTRUCTION = (
    "Keep every visible surface plain, bare, uninterrupted, and completely unmarked; the "
    "entire frame contains no posters, notices, plaques, graphic design, lettering, digits, "
    "symbols, or typographic marks; convey meaning only through objects and character reaction"
)
LAYOUT_NEGATIVE_TAGS = (
    "(comic page layout:1.7), (multiple panels:1.7), (inset image:1.7), "
    "panel border, comic grid, split screen, collage, cutaway, repeated scene, "
    "duplicated character, duplicated accessory, duplicated prop"
)
LAYOUT_NEGATIVE_INSTRUCTION = (
    "Avoid comic-page layouts, multiple panels, panel borders, inset images, grids, split "
    "screens, collages, cutaways, repeated views, duplicated characters, duplicated "
    "accessories, and extra copies of props"
)
TEXT_NEGATIVE_TAGS = (
    "(speech bubble:1.7), (text:1.7), (typography:1.7), readable text, pseudo-text, "
    "letters, words, digits, captions, subtitles, dialogue balloon, signs, labels, "
    "coordinates, logos, watermark"
)
TEXT_NEGATIVE_INSTRUCTION = (
    "Avoid all typography, pseudo-text, letters, digits, captions, subtitles, speech "
    "bubbles, dialogue balloons, marked signs, labels, coordinates, logos, and watermarks"
)
FINAL_SINGLE_FRAME_INSTRUCTION = (
    "The finished image is one full-bleed borderless film keyframe with uninterrupted "
    "scenery, no surrounding white paper, and no graphic-design overlays"
)
FINAL_NO_TEXT_INSTRUCTION = (
    "The final canvas is visually text-free from edge to edge: only bare material surfaces "
    "are visible, with no readable or pseudo-readable marks anywhere"
)
UNIQUE_OBJECT_TAGS = (
    "(duplicate accessory:1.7), (second pocket watch:1.7), "
    "(multiple pocket watches:1.7), duplicate jewelry, duplicate prop"
)
UNIQUE_OBJECT_INSTRUCTION = (
    "Show exactly one physical instance of every named accessory and prop; never add a "
    "second copy elsewhere on the body or in the scene"
)

# `render_text=false` means that story facts may still describe documents and signs, but
# those facts must not become literal typography instructions for the diffusion model.
# Replacing the carrier with a blank equivalent preserves composition while removing the
# strongest prompt-side cause of invented readable text.
TEXT_SURFACE_REPLACEMENTS = (
    (r"(?i)\b(?:cinema|movie theater|theatre|theater)\b", "abandoned old building"),
    (r"(?i)\b(?:signboard|signage|sign|label|caption|subtitle)\b", "bare uninterrupted wall"),
    (r"(?i)\b(?:note|letter|document|record|calendar)\b", "plain folded paper shown from its blank back"),
    (r"(?i)\b(?:writing|handwriting|text|letters|words|digits|coordinates)\b", "blank unmarked surface"),
    (r"(?i)\b(?:arrow|arrows|marker|marking|graffiti|inscription|serial number)\b", "natural directional surface crack"),
    (r"(?i)\b(?:read|reading|decipher|deciphering)\b", "examine the blank surface"),
    (r"\u62db\u724c(?:\u5b57\u8ff9|\u6587\u5b57|\u5185\u5bb9|\u6807\u8bc6)?", "\u88f8\u9732\u8fde\u7eed\u7684\u65e7\u5899\u9762"),
    (r"\u6807\u724c(?:\u5b57\u8ff9|\u6587\u5b57|\u5185\u5bb9|\u6807\u8bc6)?", "\u88f8\u9732\u8fde\u7eed\u7684\u5899\u9762"),
    (r"\u7eb8\u6761|\u4fe1\u4ef6|\u4fe1\u5c01|\u6587\u4ef6|\u65e5\u5386", "\u4ec5\u4ece\u7a7a\u767d\u80cc\u9762\u53ef\u89c1\u7684\u6298\u53e0\u7eb8\u5f20"),
    (r"\u7b14\u8bb0\u672c|\u65e5\u8bb0|\u4e66\u672c|\u518c\u5b50", "\u5c01\u95ed\u7684\u7d20\u8272\u65e0\u6807\u8bb0\u65e7\u518c"),
    (r"\u94c5\u7b14\u5b57\u8ff9|\u9ed1\u8272\u8bb0\u53f7\u7b14", "\u81ea\u7136\u7684\u7eb8\u9762\u6216\u5899\u9762\u7eb9\u7406"),
    (r"\u7bad\u5934(?:\u6807\u8bb0)?", "\u5177\u6709\u65b9\u5411\u611f\u7684\u5899\u9762\u88c2\u7eb9"),
    (r"\u6807\u8bb0|\u8bb0\u53f7|\u6d82\u9e26|\u7f16\u53f7|\u5e8f\u5217|\u540d\u5355|\u6807\u7b7e", "\u81ea\u7136\u8868\u9762\u7eb9\u7406"),
    (r"\u9605\u8bfb|\u9010\u5b57|\u8bfb\u5b8c|\u8bfb\u51fa|\u8fa8\u8ba4|\u8fa8\u8bc6", "\u89c2\u5bdf\u7a7a\u767d\u8868\u9762"),
    (r"[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+\u4e2a\u5b57|\u5b57\u6837|\u4e8c\u5b57", "\u7a7a\u767d\u7eb8\u9762"),
    (r"\u5b57\u8ff9|\u6587\u5b57|\u624b\u5199|\u6570\u5b57|\u5750\u6807|\u7b7e\u540d|\u9898\u5b57|\u5b57\u5e55|\u5bf9\u767d", "\u7a7a\u767d\u65e0\u6807\u8bb0\u8868\u9762"),
    (r"\u7535\u5f71\u9662|\u5f71\u9662", "\u5e9f\u5f03\u65e7\u5efa\u7b51"),
)


@dataclass(frozen=True)
class CompiledImageSpec:
    spec: dict[str, Any]
    positive_prompt: str
    negative_prompt: str
    required_capabilities: list[str]
    warnings: list[dict[str, Any]]
    spec_hash: str


class BaseImageSpecCompiler:
    """模型无关 ImageSpec 编译器；差异只来自 Prompt 表达类型。"""

    compiler_key = "base"
    compiler_version = "10"
    prompt_type = ImagePromptType.NATURAL_LANGUAGE

    def compile(
        self,
        *,
        snapshot: dict[str, Any],
        shot_plan: dict[str, Any],
        style_profile: dict[str, Any] | None,
        negative_prompts: dict[str, str],
        generation_mode: GenerationMode,
        source_hash: str,
    ) -> CompiledImageSpec:
        warnings = self._readiness_warnings(
            snapshot=snapshot,
            style_profile=style_profile,
        )
        if generation_mode == GenerationMode.FINAL and warnings:
            codes = ", ".join(item["code"] for item in warnings)
            raise ValueError(f"Final image spec is missing canonical conditions: {codes}")
        # ShotPlanner 的降级告警不代表视觉圣经缺失，因此不会额外阻断 Final；
        # 但会进入每种 ImageSpec，供页面审查和工作流选择时查看。
        warnings.extend(
            dict(item)
            for item in shot_plan.get("warnings", [])
            if isinstance(item, dict)
        )

        subjects = self._subjects(snapshot, shot_plan)
        scene = self._scene(snapshot, shot_plan)
        style = self._style(style_profile or {})
        render_text = bool(shot_plan.get("render_text", False))
        prompt_subjects = subjects
        prompt_scene = scene
        if not render_text:
            prompt_subjects = self._sanitize_prompt_value(subjects, mask_numbers=False)
            prompt_scene = self._sanitize_prompt_value(scene, mask_numbers=True)
        prompt_subjects, prompt_scene = self._deduplicate_accessory_mentions(
            subjects=prompt_subjects,
            scene=prompt_scene,
        )
        capabilities = self._required_capabilities(
            subjects=subjects,
            scene=scene,
            style=style,
            shot_plan=shot_plan,
        )
        tag_text = self._join_tags(
            [
                SINGLE_FRAME_TAGS,
                NO_TEXT_TAGS if not render_text else "",
                self._tag_positive(
                    subjects=prompt_subjects,
                    scene=prompt_scene,
                    style=style,
                ),
            ]
        ).strip()
        natural_text = self._join_sentences(
            [
                SINGLE_FRAME_INSTRUCTION,
                NO_TEXT_INSTRUCTION if not render_text else "",
                self._composition_instruction(
                    subjects=prompt_subjects,
                    scene=prompt_scene,
                ),
                self._natural_language_positive(
                    subjects=prompt_subjects,
                    scene=prompt_scene,
                    style=style,
                ),
                FINAL_SINGLE_FRAME_INSTRUCTION,
                FINAL_NO_TEXT_INSTRUCTION if not render_text else "",
            ]
        ).strip()
        negative_constraints = self._negative_constraints(snapshot)
        tag_negative = self._join_tags(
            [
                LAYOUT_NEGATIVE_TAGS,
                TEXT_NEGATIVE_TAGS if not render_text else "",
                UNIQUE_OBJECT_TAGS,
                negative_prompts.get("tag", ""),
                style.get("negative_tag", ""),
                *negative_constraints,
            ]
        )
        natural_negative = self._join_sentences(
            [
                LAYOUT_NEGATIVE_INSTRUCTION,
                TEXT_NEGATIVE_INSTRUCTION if not render_text else "",
                UNIQUE_OBJECT_INSTRUCTION,
                negative_prompts.get("natural_language", ""),
                style.get("negative_natural_language", ""),
                *negative_constraints,
            ]
        )

        positive_prompt, negative_prompt = self._effective_prompts(
            tag_text=tag_text,
            natural_text=natural_text,
            tag_negative=tag_negative,
            natural_negative=natural_negative,
        )
        if not positive_prompt:
            raise ValueError("Compiled positive prompt cannot be empty.")
        prompt = {
            "positive": positive_prompt,
            "negative": negative_prompt,
            "tag_text": tag_text,
            "natural_language_text": natural_text,
            "combined_text": self._combine(natural_text, tag_text),
            "negative_tag_text": tag_negative,
            "negative_natural_language_text": natural_negative,
            "negative_combined_text": self._combine(natural_negative, tag_negative),
        }
        spec = {
            "schema_version": 2,
            "source_hash": source_hash,
            "prompt_type": self.prompt_type.value,
            "generation_mode": generation_mode.value,
            "prompt": prompt,
            "subjects": subjects,
            "scene": scene,
            "style": style,
            "shot_plan": shot_plan,
            "required_capabilities": capabilities,
            "warnings": warnings,
            "compiler": {
                "key": self.compiler_key,
                "version": self.compiler_version,
            },
        }
        return CompiledImageSpec(
            spec=spec,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            required_capabilities=capabilities,
            warnings=warnings,
            spec_hash=canonical_hash(spec),
        )

    def _effective_prompts(
        self,
        *,
        tag_text: str,
        natural_text: str,
        tag_negative: str,
        natural_negative: str,
    ) -> tuple[str, str]:
        if self.prompt_type == ImagePromptType.TAG:
            return tag_text, tag_negative
        if self.prompt_type == ImagePromptType.NATURAL_LANGUAGE:
            return natural_text, natural_negative
        return (
            self._combine(natural_text, tag_text),
            self._combine(natural_negative, tag_negative),
        )

    @staticmethod
    def _combine(natural_language: str, tags: str) -> str:
        """混合型固定先放自然语言，再换行追加 tag，保证结果可预测。"""

        return "\n".join(value for value in (natural_language.strip(), tags.strip()) if value)

    @classmethod
    def _sanitize_prompt_value(cls, value: Any, *, mask_numbers: bool) -> Any:
        """render_text=false 时只清洗编译用副本，规格中的原始视觉事实仍完整保留。"""

        if isinstance(value, dict):
            return {
                key: cls._sanitize_prompt_value(item, mask_numbers=mask_numbers)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                cls._sanitize_prompt_value(item, mask_numbers=mask_numbers)
                for item in value
            ]
        if not isinstance(value, str):
            return value
        text = value
        for left, right in (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")):
            pattern = re.escape(left) + r"[^\r\n]{1,160}?" + re.escape(right)
            text = re.sub(pattern, "", text)
        if mask_numbers:
            text = re.sub(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?!\w)", "", text)
        for pattern, replacement in TEXT_SURFACE_REPLACEMENTS:
            text = re.sub(pattern, replacement, text)
        return " ".join(text.split())

    @staticmethod
    def _outfit_prompt_description(outfit: dict[str, Any]) -> str:
        """渲染服装时优先使用衣物组件，避免颜色汇总再次夹带配饰。"""

        components = outfit.get("garment_components") or []
        if isinstance(components, list):
            values = [str(item).strip() for item in components if str(item).strip()]
            if values:
                return "; ".join(values)
        return str(outfit.get("description", "")).strip()

    @staticmethod
    def _accessory_aliases(description: str) -> list[str]:
        """从配饰描述提取稳定名称，供动作和构图引用同一实体。"""

        aliases: set[str] = set()
        for segment in re.split(r"[;；。]", description):
            value = segment.strip()
            if not value:
                continue
            head = re.split(r"[（(]", value, maxsplit=1)[0].strip()
            if not head:
                continue
            aliases.add(head)
            cjk_groups = re.findall(r"[\u4e00-\u9fff]+", head)
            for group in cjk_groups:
                if 2 <= len(group) <= 6:
                    aliases.add(group[-2:])
            words = re.findall(r"[A-Za-z][A-Za-z-]*", head)
            if 2 <= len(words) <= 5:
                aliases.add(" ".join(words[-2:]))
        return sorted((item for item in aliases if len(item) >= 2), key=len, reverse=True)

    @classmethod
    def _replace_accessory_mentions(cls, value: Any, aliases: list[str]) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._replace_accessory_mentions(item, aliases)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._replace_accessory_mentions(item, aliases) for item in value]
        if not isinstance(value, str):
            return value
        text = value
        for alias in aliases:
            replacement = (
                "同一件已连接配饰"
                if re.search(r"[\u4e00-\u9fff]", alias)
                else "the same attached accessory"
            )
            text = re.sub(re.escape(alias), replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _shot_manipulates_accessory(
        subject: dict[str, Any], aliases: list[str]
    ) -> bool:
        """识别当前镜头是否把固定配饰从静止位置托起或打开。"""

        shot = subject.get("shot") or {}
        text = " ".join(
            str(shot.get(key, "")) for key in ("action", "pose")
        ).lower()
        if not any(alias.lower() in text for alias in aliases):
            return False
        return bool(
            re.search(
                r"\b(?:hold|holds|holding|open|opens|opening|lift|lifts|lifting|"
                r"raise|raises|raising|grasp|grasps|grasping|clutch|clutches|"
                r"clutching|touch|touches|touching)\b|"
                r"[拿握托捧举开抬攥抓触摸扶]",
                text,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _manipulated_accessory_description(description: str) -> str:
        """手持时只保留一个空间位置，避免“胸前一枚、手里一枚”。"""

        text = re.sub(
            r"(?:悬挂|垂挂|挂|佩戴)(?:在|于)?胸前(?:的)?(?:颈链上)?",
            "当前由一只手托起且颈链仍连接",
            description,
        )
        text = re.sub(
            r"(?i)\b(?:hanging|hung|worn)\s+(?:on|at)\s+(?:the\s+)?chest\b",
            "currently lifted by one hand while its neck chain remains attached",
            text,
        )
        return (
            f"{text} In this shot, the currently hand-held accessory appears only in "
            "that hand at the end of its still-attached chain; its normal chest resting "
            "position is completely empty, with no pendant, dial, jewelry, or second "
            "copy there"
        )

    @classmethod
    def _deduplicate_accessory_mentions(
        cls,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """配饰只在规范描述中命名一次，其余字段引用同一对象，避免模型画出副本。"""

        all_aliases: list[str] = []
        normalized_subjects: list[dict[str, Any]] = []
        for subject in subjects:
            item = dict(subject)
            accessories = dict(item.get("accessories") or {})
            description = str(accessories.get("description", "")).strip()
            aliases = cls._accessory_aliases(description)
            all_aliases.extend(aliases)
            if description and cls._shot_manipulates_accessory(item, aliases):
                accessories["description"] = cls._manipulated_accessory_description(
                    description
                )
            for key in ("shot", "conditions", "held_props", "visual_anchors"):
                if key in item:
                    item[key] = cls._replace_accessory_mentions(item[key], aliases)
            if "states" in accessories:
                accessories["states"] = cls._replace_accessory_mentions(
                    accessories["states"], aliases
                )
            item["accessories"] = accessories
            normalized_subjects.append(item)
        normalized_scene = cls._replace_accessory_mentions(
            scene,
            sorted(set(all_aliases), key=len, reverse=True),
        )
        return normalized_subjects, normalized_scene

    @classmethod
    def _composition_instruction(
        cls,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
    ) -> str:
        """把 ShotPlan 的空间约束提前，避免身份描述压过镜头与朝向。"""

        camera = scene.get("camera") or {}
        scene_shot = scene.get("shot") or {}
        camera_values = [
            camera.get("shot_type"),
            camera.get("angle"),
            f"{camera.get('lens_mm')}mm lens" if camera.get("lens_mm") else None,
            camera.get("camera_height"),
            camera.get("depth_of_field"),
        ]
        subject_values: list[str] = []
        for subject in subjects:
            shot = subject.get("shot") or {}
            details = ", ".join(
                str(value)
                for value in (
                    shot.get("orientation"),
                    shot.get("pose"),
                    shot.get("gaze"),
                )
                if value
            )
            if details:
                subject_values.append(
                    f"{subject.get('name') or subject.get('character_key')}: {details}"
                )
        count = len(subjects)
        values = [
            f"The scene contains exactly {count} visible person{'s' if count != 1 else ''}; "
            "each planned subject appears once and there are no duplicates or bystanders",
            "Camera: " + ", ".join(str(value) for value in camera_values if value),
            f"Framing: {scene_shot.get('framing_notes')}"
            if scene_shot.get("framing_notes")
            else "",
            f"Focal point: {scene_shot.get('focal_point')}"
            if scene_shot.get("focal_point")
            else "",
            *subject_values,
        ]
        details = ". ".join(value for value in values if value)
        return f"Treat this camera and composition as mandatory: {details}" if details else ""

    @staticmethod
    def _is_back_facing(shot: dict[str, Any]) -> bool:
        """背对镜头时不强迫模型展示面部，否则容易复制人物来满足身份锚点。"""

        value = " ".join(
            str(shot.get(key, "")) for key in ("orientation", "pose")
        ).casefold()
        markers = (
            "back to camera",
            "back toward the camera",
            "rear view",
            "face away from camera",
            "\u80cc\u5bf9\u955c\u5934",
            "\u540e\u8111",
            "\u540e\u89c6\u89d2",
            "\u80cc\u5f71",
        )
        return any(marker in value for marker in markers)

    @staticmethod
    def _usable_assets(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """资产不再按模型筛选；历史 LoRA 由工作流内化，因此不进入 ImageSpec。"""

        return [
            asset
            for asset in values
            if asset.get("role") != VisualAssetRole.LORA.value
        ]

    @classmethod
    def _subjects(
        cls,
        snapshot: dict[str, Any],
        shot_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        plans = {item["character_key"]: item for item in shot_plan.get("subjects", [])}
        subjects: list[dict[str, Any]] = []
        for character in snapshot.get("characters", []):
            subject = dict(character)
            identity_assets = cls._usable_assets(list(character.get("identity_assets", [])))
            identity = dict(character.get("identity") or {})
            identity["references"] = [
                asset for asset in identity_assets if asset.get("role") in IDENTITY_REFERENCE_ROLES
            ]
            subject["identity_assets"] = identity_assets
            subject["identity"] = identity

            outfit = dict(character.get("outfit") or {})
            outfit_assets = cls._usable_assets(list(outfit.get("assets", [])))
            outfit["assets"] = outfit_assets
            outfit["references"] = [
                asset for asset in outfit_assets if asset.get("role") in OUTFIT_REFERENCE_ROLES
            ]
            subject["outfit"] = outfit

            controls: dict[str, dict[str, Any]] = {}
            for asset in identity_assets + outfit_assets:
                role = str(asset.get("role", ""))
                if role in CONTROL_CAPABILITY_BY_ROLE and role not in controls:
                    controls[role] = asset
            subject["controls"] = controls
            subject["props"] = [
                {
                    "prop_key": prop.get("prop_key"),
                    "assets": cls._usable_assets(list(prop.get("assets", []))),
                    "references": [
                        asset
                        for asset in cls._usable_assets(list(prop.get("assets", [])))
                        if asset.get("role") == VisualAssetRole.PROP_REFERENCE.value
                    ],
                }
                for prop in character.get("held_prop_assets", [])
            ]
            subject["shot"] = plans.get(character["character_key"], {})
            subjects.append(subject)
        return subjects

    @classmethod
    def _scene(cls, snapshot: dict[str, Any], shot_plan: dict[str, Any]) -> dict[str, Any]:
        scene = dict(snapshot.get("scene") or {})
        assets = cls._usable_assets(list(scene.get("assets", [])))
        scene["assets"] = assets
        scene["references"] = [
            asset for asset in assets if asset.get("role") in SCENE_REFERENCE_ROLES
        ]
        scene["controls"] = {
            str(asset["role"]): asset
            for asset in assets
            if str(asset.get("role", "")) in CONTROL_CAPABILITY_BY_ROLE
        }
        scene["shot"] = shot_plan.get("scene") or {}
        scene["camera"] = shot_plan.get("camera") or {}
        return scene

    @classmethod
    def _style(cls, style_profile: dict[str, Any]) -> dict[str, Any]:
        style = dict(style_profile)
        assets = cls._usable_assets(list(style.get("assets", [])))
        style["assets"] = assets
        style["references"] = [
            asset
            for asset in assets
            if asset.get("role") == VisualAssetRole.STYLE_REFERENCE.value
        ]
        return style

    @staticmethod
    def _negative_constraints(snapshot: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for character in snapshot.get("characters", []):
            identity = character.get("identity") or {}
            outfit = character.get("outfit") or {}
            values.extend(
                str(value).strip()
                for value in (
                    identity.get("negative_constraints"),
                    character.get("negative_constraints"),
                    outfit.get("negative_constraints"),
                )
                if value
            )
        scene = snapshot.get("scene") or {}
        if scene.get("negative_constraints"):
            values.append(str(scene["negative_constraints"]).strip())
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _character_state_tokens(subject: dict[str, Any]) -> list[str]:
        outfit = subject.get("outfit") or {}
        accessories = subject.get("accessories") or {}
        values: list[str] = []
        for label, mapping in (
            ("garment", outfit.get("garment_states") or {}),
            ("clothing", outfit.get("conditions") or {}),
            ("character", subject.get("conditions") or {}),
            ("accessory", accessories.get("states") or {}),
        ):
            values.extend(
                f"{label} {key} {value}"
                for key, value in sorted(mapping.items())
                if value not in (None, "", False)
            )
        values.extend(f"holding {prop}" for prop in subject.get("held_props", []))
        return values

    @staticmethod
    def _scene_state_tokens(scene: dict[str, Any]) -> list[str]:
        values: list[str] = []
        if scene.get("time"):
            values.append(f"time {scene['time']}")
        palette = scene.get("color_palette")
        if isinstance(palette, list):
            values.extend(f"palette {value}" for value in palette if value)
        elif palette:
            values.append(f"palette {palette}")
        values.extend(
            f"spatial {key} {value}"
            for key, value in sorted((scene.get("spatial_relations") or {}).items())
            if value not in (None, "")
        )
        for label, mapping in (
            ("object", scene.get("object_states") or {}),
            ("light", scene.get("light_states") or {}),
        ):
            values.extend(
                f"{label} {key} {value}"
                for key, value in sorted(mapping.items())
                if value not in (None, "")
            )
        return values

    @classmethod
    def _tag_positive(
        cls,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
    ) -> str:
        parts: list[Any] = ["masterpiece", "high quality", f"{len(subjects)} characters"]
        for subject in subjects:
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            accessories = subject.get("accessories") or {}
            shot = subject.get("shot") or {}
            parts.extend(
                (
                    subject.get("name") or subject.get("character_key"),
                    identity.get("appearance"),
                    subject.get("hairstyle"),
                    cls._outfit_prompt_description(outfit),
                    ", ".join(str(value) for value in outfit.get("trigger_tokens", [])),
                    accessories.get("description"),
                    shot.get("expression"),
                    shot.get("action"),
                    shot.get("pose"),
                    shot.get("orientation"),
                    shot.get("gaze"),
                )
            )
            parts.extend(cls._character_state_tokens(subject))
        camera = scene.get("camera") or {}
        scene_shot = scene.get("shot") or {}
        parts.extend(
            (
                camera.get("shot_type"),
                camera.get("angle"),
                scene.get("environment_details"),
                scene.get("visual_anchors"),
                scene.get("lighting"),
                scene.get("weather"),
                scene_shot.get("framing_notes"),
                scene_shot.get("focal_point"),
                style.get("positive_tag"),
                style.get("lighting"),
            )
        )
        parts.extend(cls._scene_state_tokens(scene))
        return cls._join_tags(parts)

    @classmethod
    def _natural_language_positive(
        cls,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
    ) -> str:
        subject_sentences: list[str] = []
        for subject in subjects:
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            accessories = subject.get("accessories") or {}
            shot = subject.get("shot") or {}
            accessory_description = str(accessories.get("description", "")).strip()
            accessory_sentence = (
                f" Their fixed accessories are {accessory_description}. Show one and only "
                "one physical instance of each named accessory in the entire image; when a "
                "hand touches, holds, or opens it, draw that same attached object once in "
                "total and never create another copy."
                if accessory_description
                else ""
            )
            if cls._is_back_facing(shot):
                appearance_sentence = (
                    f"{subject.get('name') or subject.get('character_key')} is the only "
                    "visible person and is shown strictly from behind; keep their face "
                    "entirely out of frame and do not add another view of them."
                )
            else:
                appearance_sentence = (
                    f"{subject.get('name') or subject.get('character_key')} has "
                    f"{identity.get('appearance', '')}. Keep this exact appearance consistent."
                )
            sentence = (
                f"{appearance_sentence} "
                f"Their hairstyle is {subject.get('hairstyle', '')} and they wear "
                f"{cls._outfit_prompt_description(outfit)}.{accessory_sentence} They are "
                f"{shot.get('action', '')}, "
                f"in a {shot.get('pose', '')} pose, oriented {shot.get('orientation', '')}, "
                f"looking {shot.get('gaze', '')}, with {shot.get('expression', '')}."
            )
            state_text = ", ".join(cls._character_state_tokens(subject))
            if state_text:
                sentence = f"{sentence} Current persistent state: {state_text}."
            subject_sentences.append(" ".join(sentence.split()))
        camera = scene.get("camera") or {}
        camera_text = ", ".join(
            str(value)
            for value in (
                camera.get("shot_type"),
                camera.get("angle"),
                f"{camera.get('lens_mm')}mm lens" if camera.get("lens_mm") else None,
                camera.get("camera_height"),
                camera.get("depth_of_field"),
            )
            if value
        )
        scene_text = (
            f"The scene is {scene.get('name', '')}: {scene.get('environment_details', '')}. "
            f"Keep these landmarks consistent: {scene.get('visual_anchors', '')}. "
            f"Lighting is {scene.get('lighting', '')}; weather is {scene.get('weather', '')}."
        )
        scene_state = ", ".join(cls._scene_state_tokens(scene))
        if scene_state:
            scene_text = f"{scene_text} Current scene state: {scene_state}."
        return cls._join_sentences(
            [
                "Create one coherent standalone cinematic splash illustration",
                *subject_sentences,
                scene_text,
                f"Use this camera setup: {camera_text}" if camera_text else "",
                style.get("positive_natural_language", ""),
                style.get("lighting", ""),
            ]
        )

    @classmethod
    def _readiness_warnings(
        cls,
        *,
        snapshot: dict[str, Any],
        style_profile: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        for character in snapshot.get("characters", []):
            identity_assets = cls._usable_assets(character.get("identity_assets", []))
            if not any(asset.get("role") in IDENTITY_REFERENCE_ROLES for asset in identity_assets):
                warnings.append(
                    {
                        "code": "image_spec.identity_asset_missing",
                        "message": f"Character {character['character_key']} has no approved identity condition.",
                    }
                )
            outfit = character.get("outfit") or {}
            if outfit.get("variant_id") is None:
                warnings.append(
                    {
                        "code": "image_spec.outfit_variant_missing",
                        "message": f"Character {character['character_key']} has no approved outfit version.",
                    }
                )
            elif not any(
                asset.get("role") in OUTFIT_REFERENCE_ROLES
                for asset in cls._usable_assets(outfit.get("assets", []))
            ):
                warnings.append(
                    {
                        "code": "image_spec.outfit_asset_missing",
                        "message": f"Character {character['character_key']} outfit has no approved condition.",
                    }
                )
        scene = snapshot.get("scene") or {}
        if scene.get("visual_version_id") is None:
            warnings.append(
                {
                    "code": "image_spec.scene_version_missing",
                    "message": f"Scene {scene.get('scene_key', '')} has no approved visual version.",
                }
            )
        if not any(
            asset.get("role") in SCENE_ROLES
            for asset in cls._usable_assets(scene.get("assets", []))
        ):
            warnings.append(
                {
                    "code": "image_spec.scene_asset_missing",
                    "message": f"Scene {scene.get('scene_key', '')} has no approved master/control asset.",
                }
            )
        if not style_profile or style_profile.get("status") != "approved":
            warnings.append(
                {
                    "code": "image_spec.style_profile_missing",
                    "message": "No approved style profile is selected.",
                }
            )
        elif not any(
            asset.get("role") in STYLE_ROLES
            for asset in cls._usable_assets(style_profile.get("assets", []))
        ):
            warnings.append(
                {
                    "code": "image_spec.style_asset_missing",
                    "message": "Selected style has no approved reference.",
                }
            )
        return warnings

    @staticmethod
    def _required_capabilities(
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
        shot_plan: dict[str, Any],
    ) -> list[str]:
        capabilities = {WorkflowCapability.TXT2IMG.value}
        references: list[dict[str, Any]] = []
        controls: dict[str, dict[str, Any]] = {}
        for subject in subjects:
            references.extend((subject.get("identity") or {}).get("references", []))
            references.extend((subject.get("outfit") or {}).get("references", []))
            for prop in subject.get("props", []):
                references.extend(prop.get("references", []))
            controls.update(subject.get("controls", {}))
        references.extend(scene.get("references", []))
        references.extend(style.get("references", []))
        controls.update(scene.get("controls", {}))
        if references:
            capabilities.add(WorkflowCapability.REFERENCE_IMAGE.value)
        for role in controls:
            capabilities.add(CONTROL_CAPABILITY_BY_ROLE[role])
        requested_controls = {
            value
            for subject in shot_plan.get("subjects", [])
            for value in subject.get("control_requirements", [])
        } | set((shot_plan.get("scene") or {}).get("control_requirements", []))
        capabilities.update(requested_controls)
        if len(subjects) > 1:
            capabilities.add(WorkflowCapability.REGIONAL_CONDITION.value)
        return sorted(capabilities)

    @staticmethod
    def _join_tags(values: list[Any]) -> str:
        normalized = [str(value).strip(" ,") for value in values if str(value or "").strip(" ,")]
        return ", ".join(dict.fromkeys(normalized))

    @staticmethod
    def _join_sentences(values: list[Any]) -> str:
        normalized = [str(value).strip(" .") for value in values if str(value or "").strip(" .")]
        return ". ".join(dict.fromkeys(normalized)) + ("." if normalized else "")


class TagImageSpecCompiler(BaseImageSpecCompiler):
    compiler_key = "tag_v1"
    prompt_type = ImagePromptType.TAG


class NaturalLanguageImageSpecCompiler(BaseImageSpecCompiler):
    compiler_key = "natural_language_v1"
    prompt_type = ImagePromptType.NATURAL_LANGUAGE


class HybridImageSpecCompiler(BaseImageSpecCompiler):
    compiler_key = "hybrid_v1"
    prompt_type = ImagePromptType.HYBRID


def compiler_for_prompt_type(prompt_type: ImagePromptType) -> BaseImageSpecCompiler:
    """显式注册三类通用 Prompt 编译器。"""

    if prompt_type == ImagePromptType.TAG:
        return TagImageSpecCompiler()
    if prompt_type == ImagePromptType.NATURAL_LANGUAGE:
        return NaturalLanguageImageSpecCompiler()
    if prompt_type == ImagePromptType.HYBRID:
        return HybridImageSpecCompiler()
    raise ValueError(f"No ImageSpec compiler registered for prompt type: {prompt_type.value}")
