from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from backend.models.comic import (
    ComicImage,
    ComicProject,
    CharacterReferenceGenerationRun,
    CharacterReferenceImage,
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
    CharacterVisualType,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.models.time import utc_now
from backend.i18n.errors import AppError


class VisualBibleRepository:
    """视觉圣经数据访问层；只负责实体的查询、版本追加和状态更新。"""

    def __init__(self, session: Session):
        self.session = session

    def get_project(self, project_id: int) -> ComicProject | None:
        return self.session.get(ComicProject, project_id)

    def get_outline_character(self, character_id: int) -> OutlineCharacter | None:
        return self.session.get(OutlineCharacter, character_id)

    def update_outline_character_visual_type(
        self,
        *,
        character_id: int,
        visual_type: CharacterVisualType,
    ) -> OutlineCharacter:
        character = self.get_outline_character(character_id)
        if character is None:
            raise ValueError(f"OutlineCharacter not found: {character_id}")
        character.visual_type = visual_type
        self.session.commit()
        self.session.refresh(character)
        return character

    def get_script_scene(self, scene_id: int) -> ScriptScene | None:
        return self.session.get(ScriptScene, scene_id)

    def get_script_character(self, character_id: int) -> ScriptCharacter | None:
        return self.session.get(ScriptCharacter, character_id)

    def get_comic_image(self, image_id: int) -> ComicImage | None:
        return self.session.get(ComicImage, image_id)

    # Outfit variants ---------------------------------------------------
    def list_outfit_variants(
        self,
        *,
        project_id: int,
        outline_character_id: int | None = None,
    ) -> list[OutfitVariant]:
        statement = select(OutfitVariant).where(
            OutfitVariant.project_id == project_id,
            OutfitVariant.status != ApprovalStatus.DELETED,
        )
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

    def get_latest_outfit_variant_by_key(
        self,
        *,
        outline_character_id: int,
        key: str,
    ) -> OutfitVariant | None:
        """按 key 读取最新版本，包含删除/归档标记以阻止已舍弃内容重新派生。"""

        statement = (
            select(OutfitVariant)
            .where(
                OutfitVariant.outline_character_id == outline_character_id,
                OutfitVariant.key == key,
            )
            .order_by(OutfitVariant.version.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def next_outfit_version(self, *, outline_character_id: int, key: str) -> int:
        current = self.session.scalar(
            select(func.max(OutfitVariant.version)).where(
                OutfitVariant.outline_character_id == outline_character_id,
                OutfitVariant.key == key,
            )
        )
        return int(current or 0) + 1

    def create_outfit_variant(
        self, *, apply_to_character_id: int | None = None,
        expected_outfit_variant_id: int | None = None, **values: Any,
    ) -> OutfitVariant:
        """将新增、人工确认与单个分段的绑定放在同一事务中。"""
        variant = OutfitVariant(**values)
        self.session.add(variant)
        try:
            if apply_to_character_id is not None:
                variant.status = ApprovalStatus.APPROVED
                variant.approved_at = utc_now()
                self.session.flush()
                result = self.session.execute(
                    update(ScriptCharacter).where(
                        ScriptCharacter.id == apply_to_character_id,
                        ScriptCharacter.outfit_variant_id == expected_outfit_variant_id,
                    ).values(outfit_variant_id=variant.id).execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    raise AppError(code="visual.configuration_binding_changed", status_code=409)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
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
            SceneVisualVersion.project_id == project_id,
            SceneVisualVersion.status != ApprovalStatus.DELETED,
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

    def get_scene_version_by_content(
        self,
        *,
        script_scene_id: int,
        landmarks_json: str,
        spatial_relations_json: str,
        camera_presets_json: str,
        object_states_json: str,
        color_palette_json: str,
        lighting_state_json: str,
    ) -> SceneVisualVersion | None:
        """按内容匹配版本，保留删除/归档标记供自动派生识别用户舍弃意图。"""

        statement = (
            select(SceneVisualVersion)
            .where(
                SceneVisualVersion.script_scene_id == script_scene_id,
                SceneVisualVersion.landmarks_json == landmarks_json,
                SceneVisualVersion.spatial_relations_json == spatial_relations_json,
                SceneVisualVersion.camera_presets_json == camera_presets_json,
                SceneVisualVersion.object_states_json == object_states_json,
                SceneVisualVersion.color_palette_json == color_palette_json,
                SceneVisualVersion.lighting_state_json == lighting_state_json,
            )
            .order_by(SceneVisualVersion.version.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def next_scene_version(self, script_scene_id: int) -> int:
        current = self.session.scalar(
            select(func.max(SceneVisualVersion.version)).where(
                SceneVisualVersion.script_scene_id == script_scene_id
            )
        )
        return int(current or 0) + 1

    def create_scene_version(
        self, *, apply_to_scene: bool = False,
        expected_visual_version_id: int | None = None, **values: Any,
    ) -> SceneVisualVersion:
        """仅更新目标场景；原绑定变化时回滚新增版本及确认状态。"""
        version = SceneVisualVersion(**values)
        self.session.add(version)
        try:
            if apply_to_scene:
                version.status = ApprovalStatus.APPROVED
                version.approved_at = utc_now()
                self.session.flush()
                result = self.session.execute(
                    update(ScriptScene).where(
                        ScriptScene.id == version.script_scene_id,
                        ScriptScene.selected_visual_version_id == expected_visual_version_id,
                    ).values(selected_visual_version_id=version.id).execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    raise AppError(code="visual.configuration_binding_changed", status_code=409)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
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

    def configuration_bindings(
        self, entity: OutfitVariant | SceneVisualVersion,
    ) -> list[ScriptCharacter | ScriptScene]:
        """查询所有脚本任务中的绑定，删除共享服装不能只处理当前分段。"""
        if isinstance(entity, OutfitVariant):
            statement = select(ScriptCharacter).where(ScriptCharacter.outfit_variant_id == entity.id)
        else:
            statement = select(ScriptScene).where(ScriptScene.selected_visual_version_id == entity.id)
        return list(self.session.scalars(statement))

    def retire_configuration(
        self, entity: OutfitVariant | SceneVisualVersion, status: ApprovalStatus,
    ) -> None:
        """同一事务解除绑定并记录删除/归档；保留行和原图，避免历史溯源断裂。"""
        for binding in self.configuration_bindings(entity):
            if isinstance(binding, ScriptCharacter):
                binding.outfit_variant_id = None
            else:
                binding.selected_visual_version_id = None
        entity.status = status
        self.session.commit()

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
        commit: bool = True,
        reference_subject_id: int | None = None,
        outfit_variant_id: int | None = None,
    ) -> VisualAsset:
        asset = VisualAsset(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            role=role,
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
            reference_subject_id=reference_subject_id,
            outfit_variant_id=outfit_variant_id,
            derived_from_asset_id=derived_from_asset_id,
            crop_metadata_json=crop_metadata_json,
            mask_asset_id=mask_asset_id,
            approved_at=approved_at,
        )
        self.session.add(asset)
        if status == ApprovalStatus.APPROVED:
            # 先获得新素材 id，与同槽旧图的撤回一起提交，不能留下两个当前参考图。
            self.session.flush()
            self.set_asset_approval_status(asset, status, commit=False)
        if commit:
            self.session.commit()
            self.session.refresh(asset)
        else:
            # 三件套批准需要三个资产与候选状态在同一事务中提交。
            self.session.flush()
        return asset

    def set_approval_status(
        self,
        entity: OutfitVariant | StyleProfile | SceneVisualVersion | VisualAsset,
        status: ApprovalStatus,
    ):
        if isinstance(entity, VisualAsset):
            return self.set_asset_approval_status(entity, status)
        entity.status = status
        entity.approved_at = utc_now() if status == ApprovalStatus.APPROVED else None
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def set_asset_approval_status(self, asset: VisualAsset, status: ApprovalStatus, *, commit: bool = True):
        """确认图与同用途、同适用范围旧图的撤回在同一事务中完成；旧图回到候选。"""
        changed_ids = [asset.id]
        if status == ApprovalStatus.APPROVED:
            scope = self._reference_slot_scope(asset)
            if scope is not None:
                changed_ids.extend(self.session.scalars(update(VisualAsset).where(
                    VisualAsset.id != asset.id, VisualAsset.status == ApprovalStatus.APPROVED, *scope,
                ).values(status=ApprovalStatus.DRAFT, approved_at=None).returning(VisualAsset.id)))
        previously_approved = asset.status == ApprovalStatus.APPROVED
        asset.status = status
        if status != ApprovalStatus.APPROVED:
            asset.approved_at = None
        elif not previously_approved or asset.approved_at is None:
            asset.approved_at = utc_now()
        self.session.flush()
        runs = self.session.scalars(select(CharacterReferenceGenerationRun).where(
            CharacterReferenceGenerationRun.id.in_(select(CharacterReferenceImage.run_id).where(
                CharacterReferenceImage.promoted_asset_id.in_(changed_ids)))))
        for run in runs:
            # promoted_asset_id 保留转存关联；是否可用由素材当前状态决定，便于再次确认同一原图。
            run.review_status = ApprovalStatus.APPROVED if any(
                image.promoted_asset and image.promoted_asset.status == ApprovalStatus.APPROVED
                for image in run.images) else ApprovalStatus.DRAFT
        if commit:
            self.session.commit()
            self.session.refresh(asset)
        return asset

    def _reference_slot_scope(self, asset: VisualAsset):
        """仅三个参考类别互斥，控制图与历史风格不参与；人物用途和场景范围不能互相撤回。"""
        scope = [VisualAsset.project_id == asset.project_id, VisualAsset.entity_type == asset.entity_type,
                 VisualAsset.role == asset.role]
        if asset.entity_type == VisualEntityType.CHARACTER and asset.role in {
            VisualAssetRole.IDENTITY_FACE, VisualAssetRole.IDENTITY_FULL_BODY,
            VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK,
        }:
            scope.append(VisualAsset.entity_id == asset.entity_id)
            if asset.role != VisualAssetRole.IDENTITY_FACE:
                scope.append(VisualAsset.outfit_variant_id == asset.outfit_variant_id)
        elif asset.entity_type == VisualEntityType.SCENE and asset.role == VisualAssetRole.SCENE_MASTER:
            scope.append(VisualAsset.entity_id == asset.entity_id)
            subject_id = asset.reference_subject_id
            if asset.entity_id is not None:
                version = self.get_scene_version(asset.entity_id)
                subject_id = subject_id or (version.script_scene.reference_subject_id if version else None)
                # 旧版本专用图没有目录 id；只与本版本当前条目的新图互斥，避免波及已改绑条目。
                scope.append(or_(VisualAsset.reference_subject_id == subject_id,
                                 VisualAsset.reference_subject_id.is_(None)))
            else:
                scope.append(VisualAsset.reference_subject_id == subject_id)
                if subject_id is None:
                    scope.append(VisualAsset.entity_key == asset.entity_key)
        elif asset.entity_type == VisualEntityType.PROP and asset.role == VisualAssetRole.PROP_REFERENCE:
            scope.extend([VisualAsset.reference_subject_id == asset.reference_subject_id,
                          VisualAsset.entity_id == asset.entity_id])
            if asset.reference_subject_id is None:
                scope.append(VisualAsset.entity_key == asset.entity_key)
        else:
            return None
        return scope
