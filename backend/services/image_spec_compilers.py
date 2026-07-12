from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from backend.models.enums import GenerationMode, ModelFamily, VisualAssetRole, WorkflowCapability
from backend.utils.json_utils import canonical_hash, canonical_json


IDENTITY_REFERENCE_ROLES = {
    VisualAssetRole.IDENTITY_FACE.value,
    VisualAssetRole.IDENTITY_HALF_BODY.value,
    VisualAssetRole.IDENTITY_FULL_BODY.value,
}
IDENTITY_ROLES = {
    *IDENTITY_REFERENCE_ROLES,
    VisualAssetRole.LORA.value,
}
OUTFIT_REFERENCE_ROLES = {
    VisualAssetRole.OUTFIT_FRONT.value,
    VisualAssetRole.OUTFIT_BACK.value,
    VisualAssetRole.OUTFIT_DETAIL.value,
}
OUTFIT_ROLES = {
    *OUTFIT_REFERENCE_ROLES,
    VisualAssetRole.LORA.value,
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
STYLE_ROLES = {VisualAssetRole.STYLE_REFERENCE.value, VisualAssetRole.LORA.value}
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
    warnings: list[dict[str, str]]
    spec_hash: str


class BaseImageSpecCompiler(ABC):
    """确定性 ImageSpec 编译器基类；子类只决定模型专用 Prompt 顺序。"""

    compiler_key = "base"
    compiler_version = "1"
    family = ModelFamily.GENERIC

    def compile(
        self,
        *,
        snapshot: dict[str, Any],
        shot_plan: dict[str, Any],
        model_profile: dict[str, Any],
        style_profile: dict[str, Any] | None,
        negative_prompt: str,
        generation_mode: GenerationMode,
        source_hash: str,
    ) -> CompiledImageSpec:
        if ModelFamily(model_profile["family"]) != self.family:
            raise ValueError(
                f"Compiler {self.compiler_key} cannot compile family {model_profile['family']}"
            )
        warnings = self._readiness_warnings(
            snapshot=snapshot,
            style_profile=style_profile,
            model_family=self.family,
        )
        if generation_mode == GenerationMode.FINAL and warnings:
            codes = ", ".join(item["code"] for item in warnings)
            raise ValueError(f"Final image spec is missing canonical conditions: {codes}")

        subjects = self._subjects(snapshot, shot_plan, self.family)
        scene = self._scene(snapshot, shot_plan, self.family)
        style = self._style(style_profile or {}, self.family)
        render = dict(model_profile.get("default_render") or {})
        render.update(style.get("render_defaults") or {})
        capabilities = self._required_capabilities(
            subjects=subjects,
            scene=scene,
            style=style,
            shot_plan=shot_plan,
        )
        positive_prompt = self.compile_positive_prompt(
            subjects=subjects,
            scene=scene,
            style=style,
            shot_plan=shot_plan,
        ).strip()
        if not positive_prompt:
            raise ValueError("Compiled positive prompt cannot be empty.")
        negative_parts = [
            negative_prompt.strip(),
            str(style.get("negative_tokens", "")).strip(),
            *self._negative_constraints(snapshot),
        ]
        compiled_negative = ", ".join(dict.fromkeys(part for part in negative_parts if part))
        spec = {
            "schema_version": 1,
            "source_hash": source_hash,
            "model_profile": model_profile,
            "generation_mode": generation_mode.value,
            "prompt": {
                "positive": positive_prompt,
                "negative": compiled_negative,
            },
            "subjects": subjects,
            "scene": scene,
            "style": style,
            "shot_plan": shot_plan,
            "render": render,
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
            negative_prompt=compiled_negative,
            required_capabilities=capabilities,
            warnings=warnings,
            spec_hash=canonical_hash(spec),
        )

    @abstractmethod
    def compile_positive_prompt(
        self,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
        shot_plan: dict[str, Any],
    ) -> str:
        raise NotImplementedError

    @staticmethod
    def _subjects(
        snapshot: dict[str, Any],
        shot_plan: dict[str, Any],
        model_family: ModelFamily,
    ) -> list[dict[str, Any]]:
        plans = {
            item["character_key"]: item for item in shot_plan.get("subjects", [])
        }
        subjects: list[dict[str, Any]] = []
        for character in snapshot.get("characters", []):
            character_key = character["character_key"]
            subject = dict(character)
            identity_assets = BaseImageSpecCompiler._compatible_assets(
                list(character.get("identity_assets", [])), model_family
            )
            subject["identity_assets"] = identity_assets
            identity = dict(character.get("identity") or {})
            identity["references"] = [
                asset
                for asset in identity_assets
                if asset.get("role") in IDENTITY_REFERENCE_ROLES
            ]
            identity["loras"] = [
                asset for asset in identity_assets if asset.get("role") == VisualAssetRole.LORA.value
            ]
            subject["identity"] = identity
            outfit = dict(character.get("outfit") or {})
            outfit_assets = BaseImageSpecCompiler._compatible_assets(
                list(outfit.get("assets", [])), model_family
            )
            outfit["assets"] = outfit_assets
            outfit["references"] = [
                asset
                for asset in outfit_assets
                if asset.get("role") in OUTFIT_REFERENCE_ROLES
            ]
            outfit["loras"] = [
                asset for asset in outfit_assets if asset.get("role") == VisualAssetRole.LORA.value
            ]
            subject["outfit"] = outfit
            controls: dict[str, dict[str, Any]] = {}
            for asset in identity_assets + outfit_assets:
                role = str(asset.get("role", ""))
                if role in CONTROL_CAPABILITY_BY_ROLE and role not in controls:
                    controls[role] = asset
            subject["controls"] = controls
            props: list[dict[str, Any]] = []
            for prop in character.get("held_prop_assets", []):
                prop_assets = BaseImageSpecCompiler._compatible_assets(
                    list(prop.get("assets", [])), model_family
                )
                props.append(
                    {
                        "prop_key": prop.get("prop_key"),
                        "assets": prop_assets,
                        "references": [
                            asset
                            for asset in prop_assets
                            if asset.get("role") == VisualAssetRole.PROP_REFERENCE.value
                        ],
                    }
                )
            subject["props"] = props
            subject["shot"] = plans.get(character_key, {})
            subjects.append(subject)
        return subjects

    @staticmethod
    def _scene(
        snapshot: dict[str, Any],
        shot_plan: dict[str, Any],
        model_family: ModelFamily,
    ) -> dict[str, Any]:
        scene = dict(snapshot.get("scene") or {})
        assets = BaseImageSpecCompiler._compatible_assets(
            list(scene.get("assets", [])), model_family
        )
        scene["assets"] = assets
        scene["references"] = [
            asset
            for asset in assets
            if asset.get("role") in SCENE_REFERENCE_ROLES
        ]
        scene["loras"] = [
            asset for asset in assets if asset.get("role") == VisualAssetRole.LORA.value
        ]
        controls: dict[str, dict[str, Any]] = {}
        for asset in assets:
            role = str(asset.get("role", ""))
            if role in CONTROL_CAPABILITY_BY_ROLE and role not in controls:
                controls[role] = asset
        scene["controls"] = controls
        scene["shot"] = shot_plan.get("scene") or {}
        scene["camera"] = shot_plan.get("camera") or {}
        return scene

    @staticmethod
    def _style(
        style_profile: dict[str, Any], model_family: ModelFamily
    ) -> dict[str, Any]:
        """把风格资产投影为可绑定的 references/loras，同时保留完整版本元数据。"""

        style = dict(style_profile)
        assets = BaseImageSpecCompiler._compatible_assets(
            list(style.get("assets", [])), model_family
        )
        style["assets"] = assets
        style["references"] = [
            asset for asset in assets if asset.get("role") == VisualAssetRole.STYLE_REFERENCE.value
        ]
        style["loras"] = [
            asset for asset in assets if asset.get("role") == VisualAssetRole.LORA.value
        ]
        return style

    @staticmethod
    def _compatible_assets(
        values: list[dict[str, Any]], model_family: ModelFamily
    ) -> list[dict[str, Any]]:
        """通用图片可跨家族使用，模型组件只能进入匹配家族的规格。"""

        return [
            asset
            for asset in values
            if (
                asset.get("model_family") == model_family.value
                or (
                    asset.get("model_family") == ModelFamily.GENERIC.value
                    and asset.get("role") != VisualAssetRole.LORA.value
                )
            )
        ]

    @staticmethod
    def _negative_constraints(snapshot: dict[str, Any]) -> list[str]:
        """把视觉真值中的禁止改写项确定性并入负向 Prompt。"""

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
        """把 reducer 的临时状态编译为稳定短语，避免只保存却不进入生成条件。"""

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

    @staticmethod
    def _readiness_warnings(
        *,
        snapshot: dict[str, Any],
        style_profile: dict[str, Any] | None,
        model_family: ModelFamily,
    ) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []

        def compatible_assets(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return BaseImageSpecCompiler._compatible_assets(values, model_family)

        for character in snapshot.get("characters", []):
            identity_assets = compatible_assets(character.get("identity_assets", []))
            if not any(asset.get("role") in IDENTITY_ROLES for asset in identity_assets):
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
                        "message": (
                            f"Character {character['character_key']} has no approved outfit version."
                        ),
                    }
                )
            else:
                outfit_assets = compatible_assets(outfit.get("assets", []))
                if not any(asset.get("role") in OUTFIT_ROLES for asset in outfit_assets):
                    warnings.append(
                        {
                            "code": "image_spec.outfit_asset_missing",
                            "message": f"Character {character['character_key']} outfit has no approved condition.",
                        }
                    )
            for prop in character.get("held_prop_assets", []):
                prop_assets = compatible_assets(prop.get("assets", []))
                if not any(
                    asset.get("role") == VisualAssetRole.PROP_REFERENCE.value
                    for asset in prop_assets
                ):
                    warnings.append(
                        {
                            "code": "image_spec.prop_asset_missing",
                            "message": (
                                f"Held prop {prop.get('prop_key', '')} has no approved reference."
                            ),
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
        scene_assets = compatible_assets(scene.get("assets", []))
        if not any(asset.get("role") in SCENE_ROLES for asset in scene_assets):
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
        elif style_profile.get("model_family") not in {
            ModelFamily.GENERIC.value,
            model_family.value,
        }:
            warnings.append(
                {
                    "code": "image_spec.style_family_mismatch",
                    "message": (
                        f"Style family {style_profile.get('model_family')} is not compatible "
                        f"with {model_family.value}."
                    ),
                }
            )
        elif not any(
            asset.get("role") in STYLE_ROLES
            for asset in compatible_assets(style_profile.get("assets", []))
        ):
            warnings.append(
                {
                    "code": "image_spec.style_asset_missing",
                    "message": "Selected style has no approved reference or LoRA.",
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
        loras: list[dict[str, Any]] = []
        controls: dict[str, dict[str, Any]] = {}
        for subject in subjects:
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            references.extend(identity.get("references", []))
            references.extend(outfit.get("references", []))
            for prop in subject.get("props", []):
                references.extend(prop.get("references", []))
            loras.extend(identity.get("loras", []))
            loras.extend(outfit.get("loras", []))
            controls.update(subject.get("controls", {}))
        references.extend(scene.get("references", []))
        references.extend(style.get("references", []))
        loras.extend(scene.get("loras", []))
        loras.extend(style.get("loras", []))
        controls.update(scene.get("controls", {}))
        if references:
            capabilities.add(WorkflowCapability.REFERENCE_IMAGE.value)
        if loras:
            capabilities.add(WorkflowCapability.LORA.value)
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


class AnimaImageSpecCompiler(BaseImageSpecCompiler):
    compiler_key = "anima_v1"
    family = ModelFamily.ANIMA

    def compile_positive_prompt(
        self,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
        shot_plan: dict[str, Any],
    ) -> str:
        parts = ["masterpiece", "high quality", f"{len(subjects)} characters"]
        for subject in subjects:
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            accessories = subject.get("accessories") or {}
            shot = subject.get("shot") or {}
            parts.append(
                ", ".join(
                    value
                    for value in (
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
                    if value
                )
            )
            parts.extend(self._character_state_tokens(subject))
        camera = scene.get("camera") or {}
        scene_shot = scene.get("shot") or {}
        parts.extend(
            value
            for value in (
                camera.get("shot_type"),
                camera.get("angle"),
                scene.get("environment_details"),
                scene.get("visual_anchors"),
                scene.get("lighting"),
                scene.get("weather"),
                scene_shot.get("framing_notes"),
                style.get("positive_tokens"),
                style.get("lighting"),
            )
            if value
        )
        parts.extend(self._scene_state_tokens(scene))
        return ", ".join(str(value).strip() for value in parts if str(value).strip())


class ZImageImageSpecCompiler(BaseImageSpecCompiler):
    compiler_key = "z_image_v1"
    family = ModelFamily.Z_IMAGE

    def compile_positive_prompt(
        self,
        *,
        subjects: list[dict[str, Any]],
        scene: dict[str, Any],
        style: dict[str, Any],
        shot_plan: dict[str, Any],
    ) -> str:
        subject_sentences: list[str] = []
        for subject in subjects:
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            shot = subject.get("shot") or {}
            sentence = (
                f"{subject.get('name') or subject.get('character_key')} with "
                f"{identity.get('appearance', '')}; consistent features: "
                f"{identity.get('visual_anchors', '')}; section anchors: "
                f"{subject.get('visual_anchors', '')}; hairstyle {subject.get('hairstyle', '')}; "
                f"wearing {outfit.get('description', '')}; {shot.get('action', '')}, "
                f"{shot.get('pose', '')}, expression {shot.get('expression', '')}."
            )
            state_text = ", ".join(self._character_state_tokens(subject))
            if state_text:
                sentence = f"{sentence} Persistent current state: {state_text}."
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
            f"Persistent landmarks: {scene.get('visual_anchors', '')}. "
            f"Lighting: {scene.get('lighting', '')}; weather: {scene.get('weather', '')}."
        )
        scene_state = ", ".join(self._scene_state_tokens(scene))
        if scene_state:
            scene_text = f"{scene_text} Current scene state: {scene_state}."
        style_text = " ".join(
            value
            for value in (
                style.get("positive_tokens", ""),
                style.get("lighting", ""),
            )
            if value
        )
        return " ".join(
            part
            for part in (
                "A coherent full-page single-shot comic image.",
                " ".join(subject_sentences),
                scene_text,
                f"Camera: {camera_text}." if camera_text else "",
                style_text,
            )
            if part
        ).strip()


def compiler_for_family(family: ModelFamily) -> BaseImageSpecCompiler:
    """显式注册支持的模型编译器，不接受数据库中的任意 Python import path。"""

    if family == ModelFamily.ANIMA:
        return AnimaImageSpecCompiler()
    if family == ModelFamily.Z_IMAGE:
        return ZImageImageSpecCompiler()
    raise ValueError(f"No ImageSpec compiler registered for model family: {family.value}")
