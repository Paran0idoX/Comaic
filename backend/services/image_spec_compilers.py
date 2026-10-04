from dataclasses import dataclass
from copy import deepcopy
import json
import re
from typing import Any

from backend.models.enums import (
    GenerationMode,
    ImagePromptType,
    PromptLanguage,
    ReferencePurpose,
    SubjectReferenceView,
    VisualAssetRole,
    VisualEntityType,
    WorkflowCapability,
)
from backend.utils.json_utils import canonical_hash
from backend.utils.prompt_loader import PromptLoader
from backend.services.reference_selection_service import IDENTITY_ROLES, ReferenceSelectionService


IDENTITY_REFERENCE_ROLES = IDENTITY_ROLES
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
    "(duplicate accessory:1.7), duplicate jewelry, duplicate prop"
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
    compiler_version = "17"
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
        reference_plan: dict[str, Any] | None = None,
        prompt_language: PromptLanguage = PromptLanguage.ORIGINAL,
        prompt_components: dict[str, str] | None = None,
    ) -> CompiledImageSpec:
        reference_plan = reference_plan or ReferenceSelectionService.select(
            snapshot=snapshot, shot_plan=shot_plan,
        )
        warnings = [dict(item) for item in reference_plan.get("warnings", [])]
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

        subjects = self._subjects(snapshot, shot_plan, reference_plan)
        scene = self._scene(snapshot, shot_plan, reference_plan)
        # 历史风格版本仍保存用于审计，新准备链路不再施加独立风格条件。
        style: dict[str, Any] = {}
        render_text = bool(shot_plan.get("render_text", False))
        prompt_subjects = subjects
        prompt_scene = self._scene_prompt_projection(scene)
        if not render_text:
            prompt_subjects = self._sanitize_prompt_value(subjects, mask_numbers=False)
            prompt_scene = self._sanitize_prompt_value(prompt_scene, mask_numbers=True)
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
        tag_text, natural_text = self._positive_components(
            subjects=prompt_subjects, scene=prompt_scene, style=style, render_text=render_text,
        )
        negative_constraints = self._negative_constraints(snapshot)
        negative_constraints.extend(prop.get("negative_constraints", "") for prop in scene.get("props", []) if prop.get("negative_constraints"))
        tag_negative = self._join_tags(
            [
                LAYOUT_NEGATIVE_TAGS,
                TEXT_NEGATIVE_TAGS if not render_text else "",
                UNIQUE_OBJECT_TAGS,
                self._accessory_prompt_templates()["pocket_watch_negative_tags"]
                if any(re.search(r"\bpocket watch\b|怀表", str((subject.get("accessories") or {}).get("description", "")), re.IGNORECASE)
                       for subject in subjects) else "",
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

        if prompt_components is not None:
            tag_text = prompt_components["tag_text"]
            natural_text = prompt_components["natural_language_text"]
            tag_negative = prompt_components["negative_tag_text"]
            natural_negative = prompt_components["negative_natural_language_text"]
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
            "schema_version": 3,
            "source_hash": source_hash,
            "prompt_type": self.prompt_type.value,
            "generation_mode": generation_mode.value,
            "prompt_language": prompt_language.value,
            "prompt": prompt,
            "subjects": subjects,
            "scene": scene,
            "style": style,
            "shot_plan": shot_plan,
            "reference_plan": reference_plan,
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

    @classmethod
    def reference_positive_components(cls, spec: dict[str, Any], identities: dict[str, str]) -> tuple[str, str]:
        """实际传图后追加身份引用，稳定外貌、当前造型和本页变化仍共用文字规格。"""
        subjects = deepcopy(spec.get("subjects") or [])
        scene = cls._scene_prompt_projection(deepcopy(spec.get("scene") or {}))
        render_text = bool((spec.get("shot_plan") or {}).get("render_text", False))
        if not render_text:
            subjects = cls._sanitize_prompt_value(subjects, mask_numbers=False)
            scene = cls._sanitize_prompt_value(scene, mask_numbers=True)
        subjects, scene = cls._deduplicate_accessory_mentions(subjects=subjects, scene=scene)
        for subject in subjects:
            instruction = identities.get(subject.get("character_key", ""))
            if instruction:
                subject.setdefault("identity", {})["reference_instruction"] = instruction
        return cls._positive_components(subjects=subjects, scene=scene, style=spec.get("style") or {}, render_text=render_text)

    @classmethod
    def _positive_components(cls, *, subjects, scene, style, render_text) -> tuple[str, str]:
        """文字规格与传图投影共用构图、状态和三类表达，避免两条路径丢失本页动作。"""
        tag_text = cls._join_tags(
            [
                SINGLE_FRAME_TAGS,
                NO_TEXT_TAGS if not render_text else "",
                cls._tag_positive(
                    subjects=subjects,
                    scene=scene,
                    style=style,
                ),
            ]
        ).strip()
        natural_text = cls._join_sentences(
            [
                SINGLE_FRAME_INSTRUCTION,
                NO_TEXT_INSTRUCTION if not render_text else "",
                cls._composition_instruction(
                    subjects=subjects,
                    scene=scene,
                ),
                cls._natural_language_positive(
                    subjects=subjects,
                    scene=scene,
                    style=style,
                ),
                FINAL_SINGLE_FRAME_INSTRUCTION,
                FINAL_NO_TEXT_INSTRUCTION if not render_text else "",
            ]
        ).strip()
        return tag_text, natural_text

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
                # 时刻和色温等数字是环境条件，不属于需要绘制的文字。
                key: cls._sanitize_prompt_value(item, mask_numbers=mask_numbers and key != "scene_conditions")
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
        """只识别明确带链的饰物名称，不把邮包、眼镜或任意描述后缀当成挂饰。"""

        if not re.search(r"\b(?:chain|necklace)\b|链", description, re.IGNORECASE):
            return []
        if re.search(r"\b(?:without|no)\s+(?:a\s+|any\s+)?chain\b|(?:无|没有|不带|未连).{0,4}链", description, re.IGNORECASE):
            return []
        names = re.findall(r"\b(?:pocket watch|pendant|locket|necklace)\b|怀表|吊坠|挂坠|项链|坠饰", description, re.IGNORECASE)
        return sorted(set(names), key=len, reverse=True)

    @staticmethod
    def _accessory_prompt_templates() -> dict[str, str]:
        """配饰规则的生成文案集中存放，代码只负责判断同一物体是否被托起。"""
        return json.loads(PromptLoader.load("image_spec_accessory_prompts.json"))

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
        """动作须直接以该饰物为对象；提到饰物同时打开其它盒子不能触发。"""

        shot = subject.get("shot") or {}
        if not aliases:
            return False
        for key in ("action", "pose"):
            text = str(shot.get(key, ""))
            for alias in aliases:
                if re.search(r"[\u4e00-\u9fff]", alias):
                    prefix = r"(?:拿起|握住|握着|托起|托着|捧起|捧着|举起|抬起|攥着|抓住|托|捧|握|拿|举)(?:(?:胸前|颈间|腰间|的|那|这|一枚|一条|同一|银色|金色|黄铜|旧|小)\s*)*"
                    pattern = prefix + re.escape(alias)
                else:
                    prefix = r"\b(?:hold|holds|holding|lift|lifts|lifting|raise|raises|raising|grasp|grasps|grasping|clutch|clutches|clutching)\s+(?:(?:the|a|an|his|her|their|same|attached|silver|gold|golden|brass|old|small|antique)\s+)*"
                    pattern = prefix + re.escape(alias) + r"\b"
                if re.search(pattern, text, re.IGNORECASE):
                    return True
        return False

    @classmethod
    def _manipulated_accessory_description(cls, description: str) -> str:
        """手持时只保留一个空间位置，避免“胸前一枚、手里一枚”。"""

        templates = cls._accessory_prompt_templates()
        chest_position = bool(re.search(r"胸前|\b(?:on|at)\s+(?:the\s+)?chest\b", description, re.IGNORECASE))
        text = re.sub(
            r"(?:悬挂|垂挂|挂|佩戴)(?:在|于)?胸前(?:的)?(?:颈链上)?",
            templates["lifted_chest_zh"],
            description,
        )
        text = re.sub(
            r"(?i)\b(?:hanging|hung|worn)\s+(?:on|at)\s+(?:the\s+)?chest\b",
            templates["lifted_chest_en"],
            text,
        )
        return " ".join((text, templates["held_chain"], templates["empty_chest"] if chest_position else "")).strip()

    @classmethod
    def _deduplicate_accessory_mentions(
        cls,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """只合并当前确实托起的挂链饰物，其它配件及取物来源保持原文。"""

        all_aliases: list[str] = []
        normalized_subjects: list[dict[str, Any]] = []
        for subject in subjects:
            item = dict(subject)
            accessories = dict(item.get("accessories") or {})
            description = str(accessories.get("description", "")).strip()
            aliases: list[str] = []
            pieces = re.split(r"([;；。])", description)
            for index, piece in enumerate(pieces):
                piece_aliases = cls._accessory_aliases(piece)
                if piece_aliases and cls._shot_manipulates_accessory(item, piece_aliases):
                    pieces[index] = cls._manipulated_accessory_description(piece)
                    aliases.extend(piece_aliases)
            all_aliases.extend(aliases)
            if aliases:
                accessories["description"] = "".join(pieces)
            for key in ("shot", "conditions", "held_props"):
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

        if shot.get("reference_view") == SubjectReferenceView.BACK.value:
            return True
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
        reference_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        plans = {item["character_key"]: item for item in shot_plan.get("subjects", [])}
        subjects: list[dict[str, Any]] = []
        for character in snapshot.get("characters", []):
            subject = dict(character)
            # 历史快照可以读取，退役字段不再进入新 ImageSpec。
            subject.pop("visual_anchors", None)
            subject_plan = plans.get(character["character_key"], {})
            if "visible_prop_keys" in subject_plan:
                subject["held_props"] = [key for key in character.get("held_props", []) if key in subject_plan["visible_prop_keys"]]
            identity_assets = cls._usable_assets(list(character.get("identity_assets", [])))
            identity = dict(character.get("identity") or {})
            identity.pop("visual_anchors", None)
            selected = [
                item for item in reference_plan["items"]
                if item["owner"]["category"] == VisualEntityType.CHARACTER.value
                and item["owner"]["key"] == character["character_key"]
            ]
            identity["references"] = [item for item in selected if item["purpose"] == ReferencePurpose.IDENTITY.value]
            subject["identity_assets"] = identity_assets
            subject["identity"] = identity

            outfit = dict(character.get("outfit") or {})
            outfit_assets = cls._usable_assets(list(outfit.get("assets", [])))
            outfit["assets"] = outfit_assets
            outfit["references"] = [item for item in selected if item["purpose"] == ReferencePurpose.APPEARANCE.value]
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
                        item for item in reference_plan["items"]
                        if item["owner"]["category"] == VisualEntityType.PROP.value
                        and item["owner"]["key"] == prop.get("prop_key")
                    ],
                }
                for prop in character.get("held_prop_assets", [])
                if any(item["owner"]["category"] == VisualEntityType.PROP.value and item["owner"]["key"] == prop.get("prop_key") for item in reference_plan["items"])
            ]
            subject["shot"] = subject_plan
            subjects.append(subject)
        return subjects

    @classmethod
    def _scene_prompt_projection(cls, scene: dict[str, Any]) -> dict[str, Any]:
        """新版镜头用本页可见环境投影，原始场景事实仍留在规格中供审计。

        静态名称、地标、光照及状态均可能夹带可移动物件，不能靠道具名称匹配
        安全地删词。只把 Planner 已结合本页状态整理的 framing_notes 用于绘制，
        避免把关在容器里的物品或参考图上的旧摆设重新变成可见物。
        """

        shot = scene.get("shot") or {}
        if "visible_prop_keys" not in shot:
            return scene  # 历史镜头尚无投影协议，保留原有渲染方式。
        if shot.get("background_visible", True) and not str(shot.get("framing_notes", "")).strip():
            raise ValueError("visible scene requires nonempty framing_notes for its current environment")
        return {
            "shot": shot,
            "scene_conditions": scene.get("scene_conditions") or {},
            "camera": scene.get("camera") or {},
            "props": scene.get("props") or [],
            "_shot_environment_projection": True,
        }

    @staticmethod
    def _scene_prompt_templates() -> dict[str, str]:
        """本页环境优先于通用参考图陈设的文案，供三种表达共用。"""

        return json.loads(PromptLoader.load("image_spec_scene_prompts.json"))

    @classmethod
    def _scene(cls, snapshot: dict[str, Any], shot_plan: dict[str, Any], reference_plan: dict[str, Any]) -> dict[str, Any]:
        scene = dict(snapshot.get("scene") or {})
        # 页面条件独立于地点身份，参考图不能提供默认剧情天气或光照。
        if snapshot.get("scene_conditions") is not None:
            scene["scene_conditions"] = snapshot["scene_conditions"]
        scene.pop("visual_anchors", None)
        assets = cls._usable_assets(list(scene.get("assets", [])))
        scene["assets"] = assets
        scene["references"] = [item for item in reference_plan["items"] if item["owner"]["category"] == VisualEntityType.SCENE.value]
        # 可见目录物品即使在宽松模式缺图，也保留文字描述；隐藏物品不进入 Prompt。
        visible = set((shot_plan.get("scene") or {}).get("visible_prop_keys", []))
        for subject in shot_plan.get("subjects", []):
            visible.update(subject.get("visible_prop_keys", []))
        selected_prop_refs = [item for item in reference_plan["items"] if item["owner"]["category"] == VisualEntityType.PROP.value]
        if "visible_prop_keys" not in (shot_plan.get("scene") or {}):
            visible.update(item["owner"]["key"] for item in selected_prop_refs)
        scene["props"] = [
            {"prop_key": prop["key"], "name": prop.get("name") or prop["key"], "description": prop.get("description", ""), "negative_constraints": prop.get("negative_constraints", ""), "references": [item for item in selected_prop_refs if item["owner"]["key"] == prop["key"]]}
            for prop in snapshot.get("prop_catalog", []) if prop["key"] in visible
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
        if scene.get("reference_negative_constraints"):
            values.append(str(scene["reference_negative_constraints"]).strip())
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
                    # 背面不投影包含五官的固定外貌；当前发型、造型和局部状态仍保留。
                    identity.get("appearance") if not cls._is_back_facing(shot) else "",
                    identity.get("reference_instruction"),
                    "rear view, face out of frame" if cls._is_back_facing(shot) else "",
                    subject.get("hairstyle"),
                    cls._outfit_prompt_description(outfit),
                    ", ".join(str(value) for value in outfit.get("trigger_tokens", [])),
                    accessories.get("description"),
                    shot.get("expression"),
                    shot.get("action"),
                    shot.get("pose"),
                    shot.get("orientation"),
                    shot.get("gaze"),
                    shot.get("visible_state"),
                )
            )
            parts.extend(cls._character_state_tokens(subject))
        camera = scene.get("camera") or {}
        scene_shot = scene.get("shot") or {}
        parts.extend(
            (
                camera.get("shot_type"),
                camera.get("angle"),
                scene.get("environment_details") if scene_shot.get("background_visible", True) else "",
                scene.get("reference_description") if scene_shot.get("background_visible", True) else "",
                scene.get("lighting"),
                scene.get("weather") if scene_shot.get("background_visible", True) else "",
                scene_shot.get("framing_notes"),
                scene_shot.get("focal_point"),
                cls._scene_prompt_templates()["reference_scope_tags"]
                if scene.get("_shot_environment_projection") and scene_shot.get("background_visible", True) else "",
                style.get("positive_tag"),
                style.get("lighting"),
            )
        )
        if scene_shot.get("background_visible", True):
            parts.extend(cls._scene_state_tokens(scene))
        parts.extend(f"visible object {prop.get('name')}: {prop.get('description', '')}" for prop in scene.get("props", []))
        parts.extend(str(value) for value in (scene.get("scene_conditions") or {}).values() if value)
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
                " " + cls._accessory_prompt_templates()["accessory_description"].format(description=accessory_description)
                if accessory_description
                else ""
            )
            if cls._is_back_facing(shot):
                appearance_sentence = (
                    (str(identity.get("reference_instruction") or "") + " ") +
                    f"{subject.get('name') or subject.get('character_key')} appears once "
                    "and is shown strictly from behind; keep their face "
                    "entirely out of frame and do not add another view of them."
                )
            else:
                appearance_sentence = (
                    f"{subject.get('name') or subject.get('character_key')} has "
                    f"{identity.get('appearance', '')}. Keep this exact appearance consistent."
                )
                if identity.get("reference_instruction"):
                    appearance_sentence += " " + str(identity["reference_instruction"])
            sentence = (
                f"{appearance_sentence} " +
                (f"Their hairstyle is {subject.get('hairstyle')} and they wear "
                 if subject.get("hairstyle") else "They wear ") +
                f"{cls._outfit_prompt_description(outfit)}.{accessory_sentence} They are "
                f"{shot.get('action', '')}, "
                f"in a {shot.get('pose', '')} pose, oriented {shot.get('orientation', '')}, "
                f"looking {shot.get('gaze', '')}, with {shot.get('expression', '')}."
            )
            state_text = ", ".join(cls._character_state_tokens(subject))
            if state_text:
                sentence = f"{sentence} Current persistent state: {state_text}."
            if shot.get("visible_state"):
                sentence = f"{sentence} Visible state on this page: {shot['visible_state']}."
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
            f"{scene.get('reference_description', '')}. "
            f"Lighting is {scene.get('lighting', '')}; weather is {scene.get('weather', '')}."
        )
        if scene.get("_shot_environment_projection"):
            scene_text = cls._scene_prompt_templates()["projected_environment"].format(
                framing_notes=(scene.get("shot") or {}).get("framing_notes", "")
            )
        if not (scene.get("shot") or {}).get("background_visible", True):
            scene_text = "This shot has no visible background; do not add scenery merely to reproduce a scene reference."
        scene_state = ", ".join(cls._scene_state_tokens(scene)) if (scene.get("shot") or {}).get("background_visible", True) else ""
        if scene_state:
            scene_text = f"{scene_text} Current scene state: {scene_state}."
        conditions = "; ".join(f"{key}: {value}" for key, value in (scene.get("scene_conditions") or {}).items() if value)
        if conditions:
            scene_text += " " + cls._scene_prompt_templates()["page_conditions"].format(conditions=conditions)
        return cls._join_sentences(
            [
                "Create one coherent standalone cinematic splash illustration",
                *subject_sentences,
                scene_text,
                *[f"The visible catalog object {prop.get('name')} is {prop.get('description', '')}" for prop in scene.get("props", [])],
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
        # 保留私有兼容入口，但就绪只取本页所需参考，不要求风格或独立服装图片。
        return ReferenceSelectionService.select(snapshot=snapshot, shot_plan={})["warnings"]

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
        for prop in scene.get("props", []):
            references.extend(prop.get("references", []))
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
