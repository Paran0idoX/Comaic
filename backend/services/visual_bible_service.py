from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from backend.models.comic import (
    ModelProfile,
    OutfitVariant,
    SceneVisualVersion,
    StyleProfile,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
    ModelFamily,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.utils.json_utils import canonical_json


MAX_ASSET_BYTES = 25 * 1024 * 1024
IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}
COMPILER_BY_FAMILY = {
    ModelFamily.ANIMA: "anima_v1",
    ModelFamily.Z_IMAGE: "z_image_v1",
}
ALLOWED_ASSET_ROLES = {
    VisualEntityType.CHARACTER: {
        VisualAssetRole.IDENTITY_FACE,
        VisualAssetRole.IDENTITY_HALF_BODY,
        VisualAssetRole.IDENTITY_FULL_BODY,
        VisualAssetRole.POSE,
        VisualAssetRole.DEPTH,
        VisualAssetRole.CANNY,
        VisualAssetRole.LINEART,
        VisualAssetRole.SEGMENTATION,
        VisualAssetRole.MASK,
        VisualAssetRole.LORA,
    },
    VisualEntityType.OUTFIT: {
        VisualAssetRole.OUTFIT_FRONT,
        VisualAssetRole.OUTFIT_BACK,
        VisualAssetRole.OUTFIT_DETAIL,
        VisualAssetRole.MASK,
        VisualAssetRole.LORA,
    },
    VisualEntityType.SCENE: {
        VisualAssetRole.SCENE_MASTER,
        VisualAssetRole.PROP_REFERENCE,
        VisualAssetRole.DEPTH,
        VisualAssetRole.CANNY,
        VisualAssetRole.LINEART,
        VisualAssetRole.SEGMENTATION,
        VisualAssetRole.MASK,
        VisualAssetRole.LORA,
    },
    VisualEntityType.STYLE: {
        VisualAssetRole.STYLE_REFERENCE,
        VisualAssetRole.LORA,
    },
    VisualEntityType.PROP: {
        VisualAssetRole.PROP_REFERENCE,
        VisualAssetRole.MASK,
    },
    VisualEntityType.CONTROL: {
        VisualAssetRole.POSE,
        VisualAssetRole.DEPTH,
        VisualAssetRole.CANNY,
        VisualAssetRole.LINEART,
        VisualAssetRole.SEGMENTATION,
        VisualAssetRole.MASK,
    },
}


class VisualBibleService:
    """视觉圣经业务层：验证版本归属、资产文件和人工批准边界。"""

    def __init__(
        self,
        repository: VisualBibleRepository,
        *,
        asset_root: str | Path = "data/visual-assets",
    ):
        self.repository = repository
        self.asset_root = Path(asset_root)

    # Model profiles -----------------------------------------------------
    def list_model_profiles(self) -> list[ModelProfile]:
        return self.repository.list_model_profiles()

    def create_model_profile(
        self,
        *,
        name: str,
        family: ModelFamily,
        variant: str = "",
        checkpoint_name: str = "",
        checkpoint_hash: str | None = None,
        component_manifest: dict[str, Any] | None = None,
        default_render: dict[str, Any] | None = None,
        license: str | None = None,
        commercial_use_allowed: bool | None = None,
        paid_service_allowed: bool | None = None,
        fine_tuning_allowed: bool | None = None,
        redistribution_allowed: bool | None = None,
        license_notice: str | None = None,
        is_enabled: bool = False,
        is_default: bool = False,
    ) -> ModelProfile:
        if family not in COMPILER_BY_FAMILY:
            raise ValueError("Generic model profiles cannot compile ImageSpec.")
        if is_enabled and not checkpoint_name.strip():
            raise ValueError("Enabled model profile requires checkpoint_name.")
        profile = ModelProfile(
            name=self._required(name, "Model profile name"),
            family=family,
            variant=variant.strip(),
            checkpoint_name=checkpoint_name.strip(),
            checkpoint_hash=self._optional_sha256(checkpoint_hash, "Checkpoint hash"),
            component_manifest_json=canonical_json(component_manifest or {}),
            compiler_key=COMPILER_BY_FAMILY[family],
            compiler_version="1",
            default_render_json=canonical_json(default_render or {}),
            license=self._optional(license),
            commercial_use_allowed=commercial_use_allowed,
            paid_service_allowed=paid_service_allowed,
            fine_tuning_allowed=fine_tuning_allowed,
            redistribution_allowed=redistribution_allowed,
            license_notice=self._optional(license_notice),
            is_enabled=is_enabled,
            is_default=is_default,
        )
        return self.repository.save_model_profile(profile)

    def update_model_profile(self, *, profile_id: int, **values: Any) -> ModelProfile:
        profile = self.repository.get_model_profile(profile_id)
        if profile is None:
            raise ValueError(f"ModelProfile not found: {profile_id}")
        family = values.get("family", profile.family)
        if family not in COMPILER_BY_FAMILY:
            raise ValueError("Generic model profiles cannot compile ImageSpec.")
        checkpoint_name = str(values.get("checkpoint_name", profile.checkpoint_name)).strip()
        is_enabled = bool(values.get("is_enabled", profile.is_enabled))
        if is_enabled and not checkpoint_name:
            raise ValueError("Enabled model profile requires checkpoint_name.")
        profile.name = self._required(str(values.get("name", profile.name)), "Model profile name")
        profile.family = family
        profile.variant = str(values.get("variant", profile.variant)).strip()
        profile.checkpoint_name = checkpoint_name
        profile.checkpoint_hash = self._optional_sha256(
            values.get("checkpoint_hash"), "Checkpoint hash"
        )
        profile.component_manifest_json = canonical_json(
            values["component_manifest"]
            if "component_manifest" in values
            else json.loads(profile.component_manifest_json)
        )
        profile.default_render_json = canonical_json(
            values["default_render"]
            if "default_render" in values
            else json.loads(profile.default_render_json)
        )
        profile.compiler_key = COMPILER_BY_FAMILY[family]
        for field_name in (
            "license",
            "license_notice",
            "commercial_use_allowed",
            "paid_service_allowed",
            "fine_tuning_allowed",
            "redistribution_allowed",
            "is_enabled",
            "is_default",
        ):
            if field_name in values:
                value = values[field_name]
                if field_name in {"license", "license_notice"}:
                    value = self._optional(value)
                setattr(profile, field_name, value)
        return self.repository.save_model_profile(profile)

    # Versioned visual settings ----------------------------------------
    def list_outfits(
        self, *, project_id: int, outline_character_id: int | None = None
    ) -> list[OutfitVariant]:
        self._require_project(project_id)
        return self.repository.list_outfit_variants(
            project_id=project_id,
            outline_character_id=outline_character_id,
        )

    def create_outfit(
        self,
        *,
        project_id: int,
        outline_character_id: int,
        key: str,
        name: str,
        garment_components: list[Any] | None = None,
        layer_order: list[Any] | None = None,
        colors: list[Any] | None = None,
        materials: list[Any] | None = None,
        patterns: list[Any] | None = None,
        accessories: list[Any] | None = None,
        trigger_tokens: list[Any] | None = None,
        negative_constraints: str = "",
    ) -> OutfitVariant:
        self._validate_character_owner(project_id, outline_character_id)
        normalized_key = self._required(key, "Outfit key")
        return self.repository.create_outfit_variant(
            project_id=project_id,
            outline_character_id=outline_character_id,
            key=normalized_key,
            version=self.repository.next_outfit_version(
                outline_character_id=outline_character_id,
                key=normalized_key,
            ),
            name=self._required(name, "Outfit name"),
            garment_components_json=canonical_json(garment_components or []),
            layer_order_json=canonical_json(layer_order or []),
            colors_json=canonical_json(colors or []),
            materials_json=canonical_json(materials or []),
            patterns_json=canonical_json(patterns or []),
            accessories_json=canonical_json(accessories or []),
            trigger_tokens_json=canonical_json(trigger_tokens or []),
            negative_constraints=negative_constraints.strip(),
            status=ApprovalStatus.DRAFT,
        )

    def create_style(
        self,
        *,
        project_id: int,
        key: str,
        name: str,
        model_family: ModelFamily = ModelFamily.GENERIC,
        positive_tokens: str = "",
        negative_tokens: str = "",
        color_palette: list[Any] | None = None,
        lighting: str = "",
        render_defaults: dict[str, Any] | None = None,
    ) -> StyleProfile:
        self._require_project(project_id)
        normalized_key = self._required(key, "Style key")
        return self.repository.create_style_profile(
            project_id=project_id,
            key=normalized_key,
            version=self.repository.next_style_version(
                project_id=project_id,
                key=normalized_key,
            ),
            name=self._required(name, "Style name"),
            model_family=model_family,
            positive_tokens=positive_tokens.strip(),
            negative_tokens=negative_tokens.strip(),
            color_palette_json=canonical_json(color_palette or []),
            lighting=lighting.strip(),
            render_defaults_json=canonical_json(render_defaults or {}),
            status=ApprovalStatus.DRAFT,
        )

    def list_styles(self, *, project_id: int) -> list[StyleProfile]:
        self._require_project(project_id)
        return self.repository.list_style_profiles(project_id)

    def create_scene_version(
        self,
        *,
        project_id: int,
        script_scene_id: int,
        landmarks: list[Any] | None = None,
        spatial_relations: dict[str, Any] | None = None,
        camera_presets: list[Any] | None = None,
        object_states: dict[str, Any] | None = None,
        color_palette: list[Any] | None = None,
        lighting_state: dict[str, Any] | None = None,
    ) -> SceneVisualVersion:
        self._validate_scene_owner(project_id, script_scene_id)
        return self.repository.create_scene_version(
            project_id=project_id,
            script_scene_id=script_scene_id,
            version=self.repository.next_scene_version(script_scene_id),
            landmarks_json=canonical_json(landmarks or []),
            spatial_relations_json=canonical_json(spatial_relations or {}),
            camera_presets_json=canonical_json(camera_presets or []),
            object_states_json=canonical_json(object_states or {}),
            color_palette_json=canonical_json(color_palette or []),
            lighting_state_json=canonical_json(lighting_state or {}),
            status=ApprovalStatus.DRAFT,
        )

    def list_scene_versions(
        self,
        *,
        project_id: int,
        script_scene_id: int | None = None,
    ) -> list[SceneVisualVersion]:
        self._require_project(project_id)
        return self.repository.list_scene_versions(
            project_id=project_id,
            script_scene_id=script_scene_id,
        )

    def set_configuration_status(
        self,
        *,
        kind: str,
        item_id: int,
        status: ApprovalStatus,
    ) -> OutfitVariant | StyleProfile | SceneVisualVersion:
        getters = {
            "outfit": self.repository.get_outfit_variant,
            "style": self.repository.get_style_profile,
            "scene": self.repository.get_scene_version,
        }
        getter = getters.get(kind)
        if getter is None:
            raise ValueError(f"Unsupported visual configuration kind: {kind}")
        entity = getter(item_id)
        if entity is None:
            raise ValueError(f"Visual configuration not found: {kind}/{item_id}")
        return self.repository.set_approval_status(entity, status)

    def assign_outfit(self, *, script_character_id: int, outfit_variant_id: int | None):
        character = self.repository.get_script_character(script_character_id)
        if character is None:
            raise ValueError(f"ScriptCharacter not found: {script_character_id}")
        if outfit_variant_id is not None:
            variant = self.repository.get_outfit_variant(outfit_variant_id)
            if (
                variant is None
                or variant.outline_character_id != character.outline_character_id
                or variant.status != ApprovalStatus.APPROVED
            ):
                raise ValueError(
                    f"Approved OutfitVariant not found for character {script_character_id}: "
                    f"{outfit_variant_id}"
                )
        return self.repository.assign_outfit_variant(
            script_character_id=script_character_id,
            outfit_variant_id=outfit_variant_id,
        )

    def select_scene_version(self, *, script_scene_id: int, version_id: int | None):
        if version_id is not None:
            version = self.repository.get_scene_version(version_id)
            if (
                version is None
                or version.script_scene_id != script_scene_id
                or version.status != ApprovalStatus.APPROVED
            ):
                raise ValueError(
                    f"Approved SceneVisualVersion not found for scene {script_scene_id}: "
                    f"{version_id}"
                )
        return self.repository.select_scene_version(
            script_scene_id=script_scene_id,
            version_id=version_id,
        )

    # Assets ------------------------------------------------------------
    def list_assets(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType | None = None,
        entity_id: int | None = None,
        status: ApprovalStatus | None = None,
    ) -> list[VisualAsset]:
        self._require_project(project_id)
        return self.repository.list_assets(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            status=status,
        )

    def upload_asset(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
        model_family: ModelFamily,
        content: bytes,
        crop_metadata: dict[str, Any] | None = None,
        mask_asset_id: int | None = None,
        source: VisualAssetSource = VisualAssetSource.UPLOAD,
        source_image_id: int | None = None,
        approve: bool = False,
    ) -> VisualAsset:
        if role == VisualAssetRole.LORA:
            raise ValueError(
                "LoRA files cannot be uploaded to Comaic; register a renderer locator and hash."
            )
        self._validate_asset_owner(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
        )
        self._validate_mask_asset(
            project_id=project_id,
            mask_asset_id=mask_asset_id,
            require_approved=approve,
        )
        mime_type, suffix, width, height = self._validate_image(content)
        digest = hashlib.sha256(content).hexdigest()
        directory = self.asset_root / f"project_{project_id}"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{digest}{suffix}"
        if not destination.exists():
            temporary = directory / f".{digest}.{uuid4().hex}.tmp"
            temporary.write_bytes(content)
            temporary.replace(destination)
        version = self.repository.next_asset_version(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=self._optional(entity_key),
            role=role,
        )
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DRAFT
        from backend.models.time import utc_now

        return self.repository.create_asset(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=self._optional(entity_key),
            role=role,
            model_family=model_family,
            storage_kind=VisualAssetStorageKind.LOCAL_FILE,
            source=source,
            version=version,
            local_path=str(destination),
            mime_type=mime_type,
            sha256=digest,
            width=width,
            height=height,
            source_image_id=source_image_id,
            crop_metadata_json=canonical_json(crop_metadata or {}),
            mask_asset_id=mask_asset_id,
            status=status,
            approved_at=utc_now() if approve else None,
        )

    def register_renderer_asset(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
        model_family: ModelFamily,
        renderer_locator: str,
        sha256: str | None = None,
        approve: bool = False,
    ) -> VisualAsset:
        self._validate_asset_owner(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
        )
        locator = self._required(renderer_locator, "Renderer locator")
        normalized_hash = self._optional_sha256(sha256, "Asset sha256")
        if role == VisualAssetRole.LORA:
            if model_family == ModelFamily.GENERIC:
                raise ValueError("LoRA assets require an explicit model family.")
            if normalized_hash is None:
                raise ValueError("LoRA assets require a sha256 hash.")
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DRAFT
        from backend.models.time import utc_now

        return self.repository.create_asset(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=self._optional(entity_key),
            role=role,
            model_family=model_family,
            storage_kind=VisualAssetStorageKind.RENDERER_LOCATOR,
            source=VisualAssetSource.RENDERER_LOCATOR,
            version=self.repository.next_asset_version(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_key=self._optional(entity_key),
                role=role,
            ),
            renderer_locator=locator,
            sha256=normalized_hash,
            status=status,
            approved_at=utc_now() if approve else None,
        )

    def promote_image(
        self,
        *,
        image_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
        model_family: ModelFamily,
        approve: bool = False,
    ) -> VisualAsset:
        image = self.repository.get_comic_image(image_id)
        if image is None or not image.local_path:
            raise ValueError(f"ComicImage file not found: {image_id}")
        path = Path(image.local_path)
        if not path.is_file():
            raise ValueError(f"ComicImage file not found: {image_id}")
        return self.upload_asset(
            project_id=image.page.project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
            model_family=model_family,
            content=path.read_bytes(),
            source=VisualAssetSource.GENERATED_IMAGE,
            source_image_id=image.id,
            approve=approve,
        )

    def set_asset_status(self, *, asset_id: int, status: ApprovalStatus) -> VisualAsset:
        asset = self.repository.get_asset(asset_id)
        if asset is None:
            raise ValueError(f"VisualAsset not found: {asset_id}")
        if status == ApprovalStatus.APPROVED:
            self._validate_mask_asset(
                project_id=asset.project_id,
                mask_asset_id=asset.mask_asset_id,
                require_approved=True,
            )
        return self.repository.set_approval_status(asset, status)

    def asset_file(self, asset_id: int) -> tuple[Path, str | None]:
        asset = self.repository.get_asset(asset_id)
        if asset is None or not asset.local_path:
            raise ValueError(f"VisualAsset file not found: {asset_id}")
        path = Path(asset.local_path).resolve()
        root = self.asset_root.resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"VisualAsset file not found: {asset_id}")
        return path, asset.mime_type

    # Validation --------------------------------------------------------
    def _require_project(self, project_id: int) -> None:
        if self.repository.get_project(project_id) is None:
            raise ValueError(f"ComicProject not found: {project_id}")

    def _validate_character_owner(self, project_id: int, character_id: int) -> None:
        character = self.repository.get_outline_character(character_id)
        if character is None or character.outline_version.project_id != project_id:
            raise ValueError(
                f"OutlineCharacter not found for project {project_id}: {character_id}"
            )

    def _validate_scene_owner(self, project_id: int, scene_id: int) -> None:
        scene = self.repository.get_script_scene(scene_id)
        if scene is None or scene.task.project_id != project_id:
            raise ValueError(f"ScriptScene not found for project {project_id}: {scene_id}")

    def _validate_asset_owner(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
    ) -> None:
        self._require_project(project_id)
        if role not in ALLOWED_ASSET_ROLES[entity_type]:
            raise ValueError(
                f"Visual asset role {role.value} is not valid for {entity_type.value}."
            )
        if entity_type == VisualEntityType.CHARACTER:
            if entity_id is None:
                raise ValueError("Character visual asset requires entity_id.")
            self._validate_character_owner(project_id, entity_id)
            return
        if entity_type == VisualEntityType.OUTFIT:
            variant = self.repository.get_outfit_variant(entity_id or 0)
            if variant is None or variant.project_id != project_id:
                raise ValueError(f"OutfitVariant not found for project {project_id}: {entity_id}")
            return
        if entity_type == VisualEntityType.SCENE:
            version = self.repository.get_scene_version(entity_id or 0)
            if version is None or version.project_id != project_id:
                raise ValueError(
                    f"SceneVisualVersion not found for project {project_id}: {entity_id}"
                )
            return
        if entity_type == VisualEntityType.STYLE:
            style = self.repository.get_style_profile(entity_id or 0)
            if style is None or style.project_id != project_id:
                raise ValueError(f"StyleProfile not found for project {project_id}: {entity_id}")
            return
        if not self._optional(entity_key):
            raise ValueError(f"{entity_type.value} visual asset requires entity_key.")

    def _validate_mask_asset(
        self,
        *,
        project_id: int,
        mask_asset_id: int | None,
        require_approved: bool,
    ) -> None:
        if mask_asset_id is None:
            return
        mask = self.repository.get_asset(mask_asset_id)
        if (
            mask is None
            or mask.project_id != project_id
            or mask.role != VisualAssetRole.MASK
            or (require_approved and mask.status != ApprovalStatus.APPROVED)
        ):
            raise ValueError(
                f"Approved mask VisualAsset not found for project {project_id}: "
                f"{mask_asset_id}"
            )

    @staticmethod
    def _validate_image(content: bytes) -> tuple[str, str, int, int]:
        if not content:
            raise ValueError("Visual asset image cannot be empty.")
        if len(content) > MAX_ASSET_BYTES:
            raise ValueError("Visual asset image exceeds the 25 MB limit.")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Visual asset must be a valid PNG, JPEG, or WebP image.") from exc
        if image_format not in IMAGE_FORMATS:
            raise ValueError("Visual asset must be a PNG, JPEG, or WebP image.")
        mime_type, suffix = IMAGE_FORMATS[image_format]
        return mime_type, suffix, width, height

    @staticmethod
    def _required(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty.")
        return normalized

    @staticmethod
    def _optional(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @classmethod
    def _optional_sha256(cls, value: Any, field_name: str) -> str | None:
        normalized = cls._optional(value)
        if normalized is None:
            return None
        if len(normalized) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in normalized
        ):
            raise ValueError(
                f"{field_name} must contain exactly 64 hexadecimal characters."
            )
        return normalized.lower()
