from io import BytesIO
import hashlib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from backend.models.comic import (
    OutfitVariant,
    SceneVisualVersion,
    ScriptCharacter,
    ScriptScene,
    StyleProfile,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
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
    },
    VisualEntityType.OUTFIT: {
        VisualAssetRole.OUTFIT_FRONT,
        VisualAssetRole.OUTFIT_BACK,
        VisualAssetRole.OUTFIT_DETAIL,
        VisualAssetRole.MASK,
    },
    VisualEntityType.SCENE: {
        VisualAssetRole.SCENE_MASTER,
        VisualAssetRole.PROP_REFERENCE,
        VisualAssetRole.DEPTH,
        VisualAssetRole.CANNY,
        VisualAssetRole.LINEART,
        VisualAssetRole.SEGMENTATION,
        VisualAssetRole.MASK,
    },
    VisualEntityType.STYLE: {
        VisualAssetRole.STYLE_REFERENCE,
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


@dataclass
class VisualBibleDraftSummary:
    """脚本视觉设定同步到视觉圣经后的结果统计。"""

    created_outfits: int = 0
    reused_outfits: int = 0
    preserved_outfits: int = 0
    skipped_characters: int = 0
    created_scenes: int = 0
    reused_scenes: int = 0
    preserved_scenes: int = 0

    @property
    def outfit_count(self) -> int:
        """返回已绑定到视觉圣经服装版本的分段角色数量。"""

        return self.created_outfits + self.reused_outfits + self.preserved_outfits

    @property
    def scene_count(self) -> int:
        """返回已绑定到视觉圣经场景版本的脚本场景数量。"""

        return self.created_scenes + self.reused_scenes + self.preserved_scenes

    def event_payload(self) -> dict[str, int]:
        """转换为稳定的 SSE 数据，不把数据库实体暴露给前端。"""

        return {
            "outfit_count": self.outfit_count,
            "scene_count": self.scene_count,
            "created_outfit_count": self.created_outfits,
            "created_scene_count": self.created_scenes,
            "skipped_character_count": self.skipped_characters,
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

    def derive_script_visual_drafts(
        self,
        *,
        project_id: int,
        scenes: list[ScriptScene],
        characters: list[ScriptCharacter],
    ) -> VisualBibleDraftSummary:
        """从已锁定脚本设定派生可审核草稿，并幂等绑定到场景和分段角色。

        自动派生只补齐空绑定；人工已经选中的版本不会被脚本续跑覆盖。草稿仍需
        人工批准后才会进入最终 ImageSpec，因而不会绕过视觉圣经的审核边界。
        """

        self._require_project(project_id)
        summary = VisualBibleDraftSummary()
        for character in characters:
            if character.outfit_variant_id is not None:
                summary.preserved_outfits += 1
                continue
            if character.outline_character_id is None:
                summary.skipped_characters += 1
                continue

            outline_character = self.repository.get_outline_character(
                character.outline_character_id
            )
            if (
                outline_character is None
                or outline_character.outline_version.project_id != project_id
            ):
                raise ValueError(
                    "ScriptCharacter outline baseline does not belong to project: "
                    f"{character.id}"
                )

            clothing = self._stable_outfit_text(
                character.current_clothing,
                outline_character.default_clothing,
            )
            accessories = self._stable_outfit_text(
                character.current_accessories,
                outline_character.default_accessories,
            )
            color_palette = self._first_text(outline_character.default_color_palette)
            if not any((clothing, accessories, color_palette)):
                summary.skipped_characters += 1
                continue

            # 分段角色的 negative_constraints 会由连续性事件按 section 写入
            # ImageSpec；它可能包含“不要显示追踪者正脸”一类剧情约束，不能参与
            # 服装版本哈希，否则相同基础服装会被误拆成多个草稿。
            negative_constraints = self._first_text(
                outline_character.negative_constraints
            )
            outfit_content = {
                "garment_components": self._text_list(clothing),
                "layer_order": [],
                "colors": self._text_list(color_palette),
                "materials": [],
                "patterns": [],
                "accessories": self._text_list(accessories),
                "trigger_tokens": [],
                "negative_constraints": negative_constraints,
            }
            digest = hashlib.sha256(
                canonical_json(outfit_content).encode("utf-8")
            ).hexdigest()[:20]
            outfit_key = f"script_{digest}"
            outfit = self.repository.get_latest_outfit_variant_by_key(
                outline_character_id=outline_character.id,
                key=outfit_key,
            )
            if outfit is None:
                outfit = self.repository.create_outfit_variant(
                    project_id=project_id,
                    outline_character_id=outline_character.id,
                    key=outfit_key,
                    version=self.repository.next_outfit_version(
                        outline_character_id=outline_character.id,
                        key=outfit_key,
                    ),
                    name=self._automatic_outfit_name(
                        character.name or outline_character.name,
                        clothing or accessories or color_palette,
                    ),
                    garment_components_json=canonical_json(
                        outfit_content["garment_components"]
                    ),
                    layer_order_json=canonical_json(outfit_content["layer_order"]),
                    colors_json=canonical_json(outfit_content["colors"]),
                    materials_json=canonical_json(outfit_content["materials"]),
                    patterns_json=canonical_json(outfit_content["patterns"]),
                    accessories_json=canonical_json(outfit_content["accessories"]),
                    trigger_tokens_json=canonical_json(outfit_content["trigger_tokens"]),
                    negative_constraints=negative_constraints,
                    status=ApprovalStatus.DRAFT,
                )
                summary.created_outfits += 1
            else:
                summary.reused_outfits += 1
            self.repository.assign_outfit_variant(
                script_character_id=character.id,
                outfit_variant_id=outfit.id,
            )

        for scene in scenes:
            if scene.task.project_id != project_id:
                raise ValueError(
                    f"ScriptScene does not belong to project {project_id}: {scene.id}"
                )
            if scene.selected_visual_version_id is not None:
                summary.preserved_scenes += 1
                continue

            scene_content = {
                "landmarks": self._distinct_text_list(
                    scene.visual_anchors,
                    scene.environment_details,
                ),
                "spatial_relations": {},
                "camera_presets": [],
                "object_states": {},
                "color_palette": self._text_list(scene.color_palette),
                "lighting_state": self._non_empty_mapping(
                    lighting=scene.lighting,
                    time_of_day=scene.time_of_day,
                    weather=scene.weather,
                ),
            }
            serialized = {
                f"{field_name}_json": canonical_json(value)
                for field_name, value in scene_content.items()
            }
            version = self.repository.get_scene_version_by_content(
                script_scene_id=scene.id,
                **serialized,
            )
            if version is None:
                version = self.repository.create_scene_version(
                    project_id=project_id,
                    script_scene_id=scene.id,
                    version=self.repository.next_scene_version(scene.id),
                    **serialized,
                    status=ApprovalStatus.DRAFT,
                )
                summary.created_scenes += 1
            else:
                summary.reused_scenes += 1
            self.repository.select_scene_version(
                script_scene_id=scene.id,
                version_id=version.id,
            )

        return summary

    # Versioned visual settings ----------------------------------------
    def list_outfits(
        self, *, project_id: int, outline_character_id: int | None = None
    ) -> list[OutfitVariant]:
        self._require_project(project_id)
        return self.repository.list_outfit_variants(
            project_id=project_id,
            outline_character_id=outline_character_id,
        )

    @staticmethod
    def _first_text(*values: Any) -> str:
        """按优先级返回第一个非空文本。"""

        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                return normalized
        return ""

    @classmethod
    def _stable_outfit_text(cls, current: Any, default: Any) -> str:
        """相同基础服饰只因湿污、卷袖或持有位置变化时复用默认真值。"""

        current_text = cls._first_text(current)
        default_text = cls._first_text(default)
        if not current_text:
            return default_text
        if not default_text:
            return current_text

        def head(value: str) -> str:
            # Agent 通常先写服饰名，再用逗号或括号补充分段状态。
            first = re.split(r"[，,。；;（(]", value, maxsplit=1)[0]
            return "".join(first.casefold().split())

        current_head = head(current_text)
        default_head = head(default_text)
        shorter = min(len(current_head), len(default_head))
        longer = max(len(current_head), len(default_head), 1)
        same_base = current_head == default_head or (
            shorter / longer >= 0.8
            and (current_head in default_head or default_head in current_head)
        )
        return default_text if same_base else current_text

    @classmethod
    def _text_list(cls, value: Any) -> list[str]:
        """保留 Agent 自由文本整体，避免按标点误拆语义。"""

        normalized = cls._first_text(value)
        return [normalized] if normalized else []

    @classmethod
    def _distinct_text_list(cls, *values: Any) -> list[str]:
        """去重组合多个视觉描述，保持原始出现顺序。"""

        result: list[str] = []
        for value in values:
            normalized = cls._first_text(value)
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def _join_distinct_text(cls, *values: Any) -> str:
        """合并大纲和分段禁止项，同时去掉完全重复的文本。"""

        return "\n".join(cls._distinct_text_list(*values))

    @classmethod
    def _non_empty_mapping(cls, **values: Any) -> dict[str, str]:
        """只保存脚本实际提供的场景光照状态。"""

        return {
            key: normalized
            for key, value in values.items()
            if (normalized := cls._first_text(value))
        }

    @classmethod
    def _automatic_outfit_name(cls, character_name: Any, description: Any) -> str:
        """生成可辨认但不参与稳定 key 的草稿名称。"""

        name = cls._first_text(character_name) or "角色"
        detail = cls._first_text(description) or "脚本造型"
        return f"{name} · {detail}"[:255]

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
        positive_tag: str = "",
        negative_tag: str = "",
        positive_natural_language: str = "",
        negative_natural_language: str = "",
        color_palette: list[Any] | None = None,
        lighting: str = "",
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
            positive_tag=positive_tag.strip(),
            negative_tag=negative_tag.strip(),
            positive_natural_language=positive_natural_language.strip(),
            negative_natural_language=negative_natural_language.strip(),
            color_palette_json=canonical_json(color_palette or []),
            lighting=lighting.strip(),
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
        content: bytes,
        crop_metadata: dict[str, Any] | None = None,
        mask_asset_id: int | None = None,
        source: VisualAssetSource = VisualAssetSource.UPLOAD,
        source_image_id: int | None = None,
        approve: bool = False,
    ) -> VisualAsset:
        if role == VisualAssetRole.LORA:
            raise ValueError("LoRA must be configured inside the ComfyUI workflow.")
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
        renderer_locator: str,
        sha256: str | None = None,
        approve: bool = False,
    ) -> VisualAsset:
        if role == VisualAssetRole.LORA:
            raise ValueError("LoRA must be configured inside the ComfyUI workflow.")
        self._validate_asset_owner(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
        )
        locator = self._required(renderer_locator, "Renderer locator")
        normalized_hash = self._optional_sha256(sha256, "Asset sha256")
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DRAFT
        from backend.models.time import utc_now

        return self.repository.create_asset(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=self._optional(entity_key),
            role=role,
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
            content=path.read_bytes(),
            source=VisualAssetSource.GENERATED_IMAGE,
            source_image_id=image.id,
            approve=approve,
        )

    def set_asset_status(self, *, asset_id: int, status: ApprovalStatus) -> VisualAsset:
        asset = self.repository.get_asset(asset_id)
        if asset is None:
            raise ValueError(f"VisualAsset not found: {asset_id}")
        if asset.role == VisualAssetRole.LORA and status != ApprovalStatus.ARCHIVED:
            raise ValueError("Historical LoRA assets can only remain archived.")
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
