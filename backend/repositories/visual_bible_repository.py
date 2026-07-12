from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.comic import (
    ComicImage,
    ComicProject,
    ModelProfile,
    OutlineCharacter,
    OutfitVariant,
    SceneVisualVersion,
    ScriptCharacter,
    ScriptScene,
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
from backend.models.time import utc_now


class VisualBibleRepository:
    """视觉圣经数据访问层；只负责实体的查询、版本追加和状态更新。"""

    def __init__(self, session: Session):
        self.session = session

    def get_project(self, project_id: int) -> ComicProject | None:
        return self.session.get(ComicProject, project_id)

    def get_outline_character(self, character_id: int) -> OutlineCharacter | None:
        return self.session.get(OutlineCharacter, character_id)

    def get_script_scene(self, scene_id: int) -> ScriptScene | None:
        return self.session.get(ScriptScene, scene_id)

    def get_script_character(self, character_id: int) -> ScriptCharacter | None:
        return self.session.get(ScriptCharacter, character_id)

    def get_comic_image(self, image_id: int) -> ComicImage | None:
        return self.session.get(ComicImage, image_id)

    # Model profiles -----------------------------------------------------
    def list_model_profiles(self) -> list[ModelProfile]:
        return list(
            self.session.scalars(
                select(ModelProfile).order_by(
                    ModelProfile.family,
                    ModelProfile.is_default.desc(),
                    ModelProfile.name,
                )
            )
        )

    def get_model_profile(self, profile_id: int) -> ModelProfile | None:
        return self.session.get(ModelProfile, profile_id)

    def save_model_profile(self, profile: ModelProfile) -> ModelProfile:
        if profile.is_default:
            others = self.session.scalars(
                select(ModelProfile).where(
                    ModelProfile.family == profile.family,
                    ModelProfile.id != profile.id,
                )
            )
            for other in others:
                other.is_default = False
        self.session.add(profile)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    # Outfit variants ---------------------------------------------------
    def list_outfit_variants(
        self,
        *,
        project_id: int,
        outline_character_id: int | None = None,
    ) -> list[OutfitVariant]:
        statement = select(OutfitVariant).where(OutfitVariant.project_id == project_id)
        if outline_character_id is not None:
            statement = statement.where(
                OutfitVariant.outline_character_id == outline_character_id
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    OutfitVariant.outline_character_id,
                    OutfitVariant.key,
                    OutfitVariant.version.desc(),
                )
            )
        )

    def get_outfit_variant(self, variant_id: int) -> OutfitVariant | None:
        return self.session.get(OutfitVariant, variant_id)

    def next_outfit_version(self, *, outline_character_id: int, key: str) -> int:
        current = self.session.scalar(
            select(func.max(OutfitVariant.version)).where(
                OutfitVariant.outline_character_id == outline_character_id,
                OutfitVariant.key == key,
            )
        )
        return int(current or 0) + 1

    def create_outfit_variant(self, **values: Any) -> OutfitVariant:
        variant = OutfitVariant(**values)
        self.session.add(variant)
        self.session.commit()
        self.session.refresh(variant)
        return variant

    def assign_outfit_variant(
        self,
        *,
        script_character_id: int,
        outfit_variant_id: int | None,
    ) -> ScriptCharacter:
        character = self.session.get(ScriptCharacter, script_character_id)
        if character is None:
            raise ValueError(f"ScriptCharacter not found: {script_character_id}")
        character.outfit_variant_id = outfit_variant_id
        self.session.commit()
        self.session.refresh(character)
        return character

    # Style profiles ----------------------------------------------------
    def list_style_profiles(self, project_id: int) -> list[StyleProfile]:
        return list(
            self.session.scalars(
                select(StyleProfile)
                .where(StyleProfile.project_id == project_id)
                .order_by(StyleProfile.key, StyleProfile.version.desc())
            )
        )

    def get_style_profile(self, style_id: int) -> StyleProfile | None:
        return self.session.get(StyleProfile, style_id)

    def next_style_version(self, *, project_id: int, key: str) -> int:
        current = self.session.scalar(
            select(func.max(StyleProfile.version)).where(
                StyleProfile.project_id == project_id,
                StyleProfile.key == key,
            )
        )
        return int(current or 0) + 1

    def create_style_profile(self, **values: Any) -> StyleProfile:
        profile = StyleProfile(**values)
        self.session.add(profile)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    # Scene visual versions --------------------------------------------
    def list_scene_versions(
        self,
        *,
        project_id: int,
        script_scene_id: int | None = None,
    ) -> list[SceneVisualVersion]:
        statement = select(SceneVisualVersion).where(
            SceneVisualVersion.project_id == project_id
        )
        if script_scene_id is not None:
            statement = statement.where(
                SceneVisualVersion.script_scene_id == script_scene_id
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    SceneVisualVersion.script_scene_id,
                    SceneVisualVersion.version.desc(),
                )
            )
        )

    def get_scene_version(self, version_id: int) -> SceneVisualVersion | None:
        return self.session.get(SceneVisualVersion, version_id)

    def next_scene_version(self, script_scene_id: int) -> int:
        current = self.session.scalar(
            select(func.max(SceneVisualVersion.version)).where(
                SceneVisualVersion.script_scene_id == script_scene_id
            )
        )
        return int(current or 0) + 1

    def create_scene_version(self, **values: Any) -> SceneVisualVersion:
        version = SceneVisualVersion(**values)
        self.session.add(version)
        self.session.commit()
        self.session.refresh(version)
        return version

    def select_scene_version(
        self,
        *,
        script_scene_id: int,
        version_id: int | None,
    ) -> ScriptScene:
        scene = self.session.get(ScriptScene, script_scene_id)
        if scene is None:
            raise ValueError(f"ScriptScene not found: {script_scene_id}")
        scene.selected_visual_version_id = version_id
        self.session.commit()
        self.session.refresh(scene)
        return scene

    # Visual assets -----------------------------------------------------
    def list_assets(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType | None = None,
        entity_id: int | None = None,
        status: ApprovalStatus | None = None,
    ) -> list[VisualAsset]:
        statement = select(VisualAsset).where(VisualAsset.project_id == project_id)
        if entity_type is not None:
            statement = statement.where(VisualAsset.entity_type == entity_type)
        if entity_id is not None:
            statement = statement.where(VisualAsset.entity_id == entity_id)
        if status is not None:
            statement = statement.where(VisualAsset.status == status)
        return list(
            self.session.scalars(
                statement.order_by(
                    VisualAsset.entity_type,
                    VisualAsset.entity_id,
                    VisualAsset.role,
                    VisualAsset.version.desc(),
                )
            )
        )

    def get_asset(self, asset_id: int) -> VisualAsset | None:
        return self.session.get(VisualAsset, asset_id)

    def next_asset_version(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
    ) -> int:
        current = self.session.scalar(
            select(func.max(VisualAsset.version)).where(
                VisualAsset.project_id == project_id,
                VisualAsset.entity_type == entity_type,
                VisualAsset.entity_id == entity_id,
                VisualAsset.entity_key == entity_key,
                VisualAsset.role == role,
            )
        )
        return int(current or 0) + 1

    def create_asset(
        self,
        *,
        project_id: int,
        entity_type: VisualEntityType,
        entity_id: int | None,
        entity_key: str | None,
        role: VisualAssetRole,
        model_family: ModelFamily,
        storage_kind: VisualAssetStorageKind,
        source: VisualAssetSource,
        version: int,
        local_path: str | None = None,
        renderer_locator: str | None = None,
        mime_type: str | None = None,
        sha256: str | None = None,
        width: int | None = None,
        height: int | None = None,
        source_image_id: int | None = None,
        derived_from_asset_id: int | None = None,
        crop_metadata_json: str = "{}",
        mask_asset_id: int | None = None,
        status: ApprovalStatus = ApprovalStatus.DRAFT,
        approved_at: datetime | None = None,
    ) -> VisualAsset:
        asset = VisualAsset(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
            model_family=model_family,
            storage_kind=storage_kind,
            local_path=local_path,
            renderer_locator=renderer_locator,
            mime_type=mime_type,
            sha256=sha256,
            width=width,
            height=height,
            version=version,
            status=status,
            source=source,
            source_image_id=source_image_id,
            derived_from_asset_id=derived_from_asset_id,
            crop_metadata_json=crop_metadata_json,
            mask_asset_id=mask_asset_id,
            approved_at=approved_at,
        )
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def set_approval_status(
        self,
        entity: OutfitVariant | StyleProfile | SceneVisualVersion | VisualAsset,
        status: ApprovalStatus,
    ):
        entity.status = status
        entity.approved_at = utc_now() if status == ApprovalStatus.APPROVED else None
        self.session.commit()
        self.session.refresh(entity)
        return entity
