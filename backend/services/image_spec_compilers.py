from dataclasses import dataclass
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
    compiler_version = "2"
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
        capabilities = self._required_capabilities(
            subjects=subjects,
            scene=scene,
            style=style,
            shot_plan=shot_plan,
        )
        tag_text = self._tag_positive(
            subjects=subjects,
            scene=scene,
            style=style,
        ).strip()
        natural_text = self._natural_language_positive(
            subjects=subjects,
            scene=scene,
            style=style,
        ).strip()
        negative_constraints = self._negative_constraints(snapshot)
        tag_negative = self._join_tags(
            [
                negative_prompts.get("tag", ""),
                style.get("negative_tag", ""),
                *negative_constraints,
            ]
        )
        natural_negative = self._join_sentences(
            [
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
        values.extend(f"landmark {value}" for value in scene.get("landmarks", []))
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
                    identity.get("visual_anchors"),
                    subject.get("visual_anchors"),
                    subject.get("hairstyle"),
                    outfit.get("description"),
                    ", ".join(str(value) for value in outfit.get("trigger_tokens", [])),
                    accessories.get("description"),
                    shot.get("expression"),
                    shot.get("action"),
                    shot.get("pose"),
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
            shot = subject.get("shot") or {}
            sentence = (
                f"{subject.get('name') or subject.get('character_key')} has "
                f"{identity.get('appearance', '')}. Keep these features consistent: "
                f"{identity.get('visual_anchors', '')}; {subject.get('visual_anchors', '')}. "
                f"Their hairstyle is {subject.get('hairstyle', '')} and they wear "
                f"{outfit.get('description', '')}. They are {shot.get('action', '')}, "
                f"in a {shot.get('pose', '')} pose, with {shot.get('expression', '')}."
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
                "Create a coherent full-page single-shot comic image",
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
