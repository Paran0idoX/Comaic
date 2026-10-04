from io import BytesIO
import hashlib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from backend.i18n.errors import AppError
from backend.models.comic import (
    OutfitVariant,
    ReferenceSubject,
    SceneVisualVersion,
    ScriptCharacter,
    ScriptScene,
    StyleProfile,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
    CharacterVisualType,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.models.scene_conditions import SCENE_DEFINITION_VERSION
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
        VisualAssetRole.IDENTITY_FULL_BODY,
        VisualAssetRole.IDENTITY_SIDE,
        VisualAssetRole.IDENTITY_BACK,
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
            # 用户已舍弃的内容保持空绑定；内容变化会产生新的 key，仍可派生草稿。
            if outfit is not None and outfit.status in (ApprovalStatus.DELETED, ApprovalStatus.ARCHIVED):
                summary.skipped_characters += 1
                continue
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
                ) if scene.task.scene_definition_version < 2 else {},
            }
            serialized = {
                f"{field_name}_json": canonical_json(value)
                for field_name, value in scene_content.items()
            }
            version = self.repository.get_scene_version_by_content(
                script_scene_id=scene.id,
                **serialized,
            )
            if version is not None and version.status in (ApprovalStatus.DELETED, ApprovalStatus.ARCHIVED):
                continue
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

        # 脚本完成即可在目录和生图准备中定位场景，不依赖用户先打开素材页。
        from backend.repositories.reference_subject_repository import ReferenceSubjectRepository
        from backend.services.reference_subject_service import ReferenceSubjectService

        ReferenceSubjectService(ReferenceSubjectRepository(self.repository.session)).sync_script_scenes(project_id)
        return summary

    # Versioned visual settings ----------------------------------------
    def update_character_visual_type(
        self,
        *,
        character_id: int,
        visual_type: CharacterVisualType,
    ):
        """更新 CIDS 编码器路由类型；角色归属仍由现有大纲关系约束。"""

        character = self.repository.get_outline_character(character_id)
        if character is None:
            raise ValueError(f"OutlineCharacter not found: {character_id}")
        return self.repository.update_outline_character_visual_type(
            character_id=character_id,
            visual_type=visual_type,
        )

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
        apply_to: dict[str, Any] | None = None,
    ) -> OutfitVariant:
        """追加造型版本，可由明确的分段编辑入口一次确认并应用。"""
        self._validate_character_owner(project_id, outline_character_id)
        character = None
        if apply_to is not None:
            character = self.repository.get_script_character(apply_to["script_character_id"])
            if (
                character is None
                or character.section.task_id != apply_to["script_task_id"]
                or character.section.task.project_id != project_id
                or character.outline_character_id != outline_character_id
            ):
                raise AppError(code="visual.configuration_apply_target_invalid", status_code=422)
        normalized_key = self._required(key, "Outfit key")
        return self.repository.create_outfit_variant(
            apply_to_character_id=character.id if character is not None else None,
            expected_outfit_variant_id=apply_to["expected_outfit_variant_id"] if apply_to else None,
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
        apply_to: dict[str, Any] | None = None,
    ) -> SceneVisualVersion:
        """追加场景版本；应用目标必须仍是编辑入口所属任务的场景。"""
        self._validate_scene_owner(project_id, script_scene_id)
        scene = self.repository.get_script_scene(script_scene_id)
        if scene.task.scene_definition_version >= SCENE_DEFINITION_VERSION:
            # 新地点版本只保存固定空间事实，临时状态与光照由页面条件负责。
            object_states, lighting_state = {}, {}
        if apply_to is not None:
            if scene.task_id != apply_to["script_task_id"]:
                raise AppError(code="visual.configuration_apply_target_invalid", status_code=422)
        return self.repository.create_scene_version(
            apply_to_scene=apply_to is not None,
            expected_visual_version_id=apply_to["expected_visual_version_id"] if apply_to else None,
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

    def _require_removable_configuration(
        self, kind: VisualEntityType, item_id: int,
    ) -> OutfitVariant | SceneVisualVersion:
        """删除入口只允许服装和场景，风格及参考原图不参与此次生命周期变更。"""
        getters = {
            VisualEntityType.OUTFIT: self.repository.get_outfit_variant,
            VisualEntityType.SCENE: self.repository.get_scene_version,
        }
        getter = getters.get(kind)
        if getter is None:
            raise AppError(code="common.validation_error", status_code=422)
        entity = getter(item_id)
        if entity is None:
            raise AppError(code="common.not_found", status_code=404)
        return entity

    def configuration_usage(self, *, kind: VisualEntityType, item_id: int) -> dict:
        """返回跨任务的真实绑定范围，供删除确认框展示。"""
        entity = self._require_removable_configuration(kind, item_id)
        bindings = self.repository.configuration_bindings(entity)
        return {
            "id": entity.id,
            "status": entity.status.value,
            "binding_count": len(bindings),
            "bindings": [{"id": binding.id, "name": binding.name} for binding in bindings],
        }

    def delete_configuration_draft(self, *, kind: VisualEntityType, item_id: int) -> dict:
        """删除草稿并解除所有脚本绑定；已确认版本须使用归档入口。"""
        entity = self._require_removable_configuration(kind, item_id)
        if entity.status == ApprovalStatus.DELETED:
            return {"id": item_id}
        if entity.status != ApprovalStatus.DRAFT:
            raise AppError(code="visual.configuration_delete_requires_draft", status_code=409)
        self.repository.retire_configuration(entity, ApprovalStatus.DELETED)
        return {"id": item_id}

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
        if entity.status == ApprovalStatus.DELETED or status == ApprovalStatus.DELETED:
            raise AppError(code="visual.configuration_deleted", status_code=409)
        if status == ApprovalStatus.ARCHIVED and isinstance(entity, (OutfitVariant, SceneVisualVersion)):
            self.repository.retire_configuration(entity, status)
            return entity
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
        commit: bool = True,
        reference_subject_id: int | None = None,
        outfit_variant_id: int | None = None,
    ) -> VisualAsset:
        if role == VisualAssetRole.LORA:
            raise ValueError("LoRA must be configured inside the ComfyUI workflow.")
        entity_key = self._reference_owner_key(project_id, entity_type, entity_id,
            entity_key, reference_subject_id, outfit_variant_id)
        self._validate_asset_owner(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
            reference_subject_id=reference_subject_id,
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
            commit=commit,
            reference_subject_id=reference_subject_id,
            outfit_variant_id=outfit_variant_id,
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
        reference_subject_id: int | None = None,
        outfit_variant_id: int | None = None,
    ) -> VisualAsset:
        if role == VisualAssetRole.LORA:
            raise ValueError("LoRA must be configured inside the ComfyUI workflow.")
        entity_key = self._reference_owner_key(project_id, entity_type, entity_id,
            entity_key, reference_subject_id, outfit_variant_id)
        self._validate_asset_owner(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
            reference_subject_id=reference_subject_id,
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
            reference_subject_id=reference_subject_id,
            outfit_variant_id=outfit_variant_id,
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
        reference_subject_id: int | None = None,
        outfit_variant_id: int | None = None,
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
            reference_subject_id=reference_subject_id,
            outfit_variant_id=outfit_variant_id,
        )

    def set_asset_status(self, *, asset_id: int, status: ApprovalStatus, commit: bool = True) -> VisualAsset:
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
        return self.repository.set_asset_approval_status(asset, status, commit=commit)

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
    def _reference_owner_key(self, project_id, entity_type, entity_id, entity_key,
            reference_subject_id, outfit_variant_id):
        """统一上传、生成图转存和远端登记的归属校验，避免目录 id 混入旧版本 id。"""
        if reference_subject_id is not None:
            subject = self.repository.session.get(ReferenceSubject, reference_subject_id)
            if subject is None or subject.project_id != project_id or subject.entity_type != entity_type:
                raise AppError("reference.owner_invalid", status_code=422)
            if entity_type not in {VisualEntityType.SCENE, VisualEntityType.PROP}:
                raise AppError("reference.owner_invalid", status_code=422)
            if entity_id is not None:
                if entity_type == VisualEntityType.SCENE and subject.scene_definition_version >= SCENE_DEFINITION_VERSION:
                    raise AppError("reference.owner_invalid", status_code=422)
                version = self.repository.get_scene_version(entity_id) if entity_type == VisualEntityType.SCENE else None
                if (version is None or version.project_id != project_id
                        or version.script_scene.task.project_id != project_id
                        or version.script_scene.reference_subject_id != reference_subject_id):
                    raise AppError("reference.owner_invalid", status_code=422)
            entity_key = subject.key
        if outfit_variant_id is not None:
            outfit = self.repository.get_outfit_variant(outfit_variant_id)
            if (entity_type != VisualEntityType.CHARACTER or outfit is None
                    or outfit.project_id != project_id or outfit.outline_character_id != entity_id):
                raise AppError("reference.outfit_invalid", status_code=422)
        return entity_key

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
        reference_subject_id: int | None = None,
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
            if reference_subject_id is not None:
                subject = self.repository.session.get(ReferenceSubject, reference_subject_id)
                if subject is not None and subject.project_id == project_id and subject.entity_type == entity_type:
                    return
                raise AppError("reference.owner_invalid", status_code=422)
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
