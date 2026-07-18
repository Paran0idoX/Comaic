import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.comic import (
    ComicProject,
    OutlineCharacter,
    OutlineVersion,
    OutfitVariant,
    SceneVisualVersion,
    ScriptCharacter,
    ScriptGenerationTask,
    ScriptSection,
    ScriptScene,
    Session as BusinessSession,
)
from backend.models.database import Base
from backend.models.enums import (
    ApprovalStatus,
    OutlineVersionStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
    SessionPurpose,
    VisualAssetRole,
    VisualEntityType,
)
from backend.repositories.comic_repository import ComicRepository
from backend.services.visual_bible_service import VisualBibleService
from backend.services.script_service import ScriptService


class FakeRepository:
    def get_project(self, project_id):
        return SimpleNamespace(id=project_id)

    def get_outline_character(self, character_id):
        return SimpleNamespace(
            id=character_id,
            outline_version=SimpleNamespace(project_id=1),
        )


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_script_context(session):
    project = ComicProject(title="Visual draft integration")
    conversation = BusinessSession(
        project=project,
        thread_id="visual-draft-thread",
        purpose=SessionPurpose.OUTLINE,
    )
    outline = OutlineVersion(
        project=project,
        session=conversation,
        version_no=1,
        content="林在雨夜进入旧车站。",
        status=OutlineVersionStatus.ACTIVE,
    )
    character = OutlineCharacter(
        outline_version=outline,
        character_key="lin",
        name="林",
        appearance="黑色短发，琥珀色眼睛",
        visual_anchors="左眉尾小痣",
        negative_constraints="不要改变眼睛颜色",
        default_hairstyle="黑色短发",
        default_clothing="深蓝风衣",
        default_accessories="银色怀表",
        default_color_palette="深蓝、银灰",
    )
    task = ScriptGenerationTask(
        project=project,
        outline_version=outline,
        status=ScriptGenerationTaskStatus.RUNNING,
        mode=ScriptGenerationMode.BATCH,
        total_pages=4,
    )
    section = ScriptSection(
        task=task,
        section_no=1,
        page_start=1,
        page_end=2,
        title="抵达",
        description="林抵达旧车站。",
        status=ScriptSectionStatus.GENERATING,
    )
    session.add_all([project, character, task, section])
    session.commit()
    return project, outline, character, task, section


def _scene_payload(scene_key: str = "old_station") -> dict[str, str]:
    return {
        "scene_key": scene_key,
        "name": "旧车站",
        "location_type": "室内站台",
        "time_of_day": "深夜",
        "lighting": "冷白顶灯与远处暖光",
        "weather": "暴雨",
        "environment_details": "潮湿站台、旧木长椅和锈蚀站牌",
        "color_palette": "蓝灰、暗红",
        "visual_anchors": "中央圆钟与三号站牌",
        "negative_constraints": "不要增加现代电子屏",
    }


def _character_payload(clothing: str = "深蓝风衣") -> dict[str, str]:
    return {
        "character_key": "lin",
        "name": "林",
        "section_role": "调查者",
        "current_hairstyle": "被雨水打湿的黑色短发",
        "current_clothing": clothing,
        "current_accessories": "银色怀表",
        "current_state": "轻微疲惫",
        "emotion": "警觉",
        "temporary_changes": "衣角被雨水打湿",
        "visual_anchors": "左眉尾小痣和琥珀色眼睛",
        "negative_constraints": "不要改变眼睛颜色",
    }


def test_asset_roles_are_validated_without_model_family() -> None:
    service = VisualBibleService(FakeRepository())
    with pytest.raises(ValueError, match="not valid for character"):
        service.register_renderer_asset(
            project_id=1,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=10,
            entity_key=None,
            role=VisualAssetRole.SCENE_MASTER,
            renderer_locator="scene.png",
        )


def test_lora_assets_must_live_inside_comfyui_workflows() -> None:
    service = VisualBibleService(FakeRepository())
    with pytest.raises(ValueError, match="inside the ComfyUI workflow"):
        service.register_renderer_asset(
            project_id=1,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=10,
            entity_key=None,
            role=VisualAssetRole.LORA,
            renderer_locator="identity.safetensors",
            sha256="a" * 64,
        )


def test_script_visual_settings_create_and_reuse_visual_bible_drafts() -> None:
    session = _session()
    project, outline, _outline_character, task, first_section = _seed_script_context(
        session
    )
    service = ScriptService(ComicRepository(session))

    first = service._save_section_visual_settings(
        task_id=task.id,
        section_id=first_section.id,
        outline_version_id=outline.id,
        scenes=[_scene_payload()],
        characters=[_character_payload()],
    )

    assert first.created_outfits == 1
    assert first.created_scenes == 1
    outfit = session.scalars(select(OutfitVariant)).one()
    scene_version = session.scalars(select(SceneVisualVersion)).one()
    script_character = session.scalars(select(ScriptCharacter)).one()
    script_scene = session.scalars(select(ScriptScene)).one()
    assert outfit.status == ApprovalStatus.DRAFT
    assert scene_version.status == ApprovalStatus.DRAFT
    assert script_character.outfit_variant_id == outfit.id
    assert script_scene.selected_visual_version_id == scene_version.id
    assert json.loads(outfit.garment_components_json) == ["深蓝风衣"]
    assert json.loads(outfit.accessories_json) == ["银色怀表"]
    assert json.loads(outfit.colors_json) == ["深蓝、银灰"]
    assert json.loads(scene_version.landmarks_json) == [
        "中央圆钟与三号站牌",
        "潮湿站台、旧木长椅和锈蚀站牌",
    ]
    assert json.loads(scene_version.lighting_state_json) == {
        "lighting": "冷白顶灯与远处暖光",
        "time_of_day": "深夜",
        "weather": "暴雨",
    }

    retry = service._save_section_visual_settings(
        task_id=task.id,
        section_id=first_section.id,
        outline_version_id=outline.id,
        scenes=[_scene_payload()],
        characters=[_character_payload()],
    )
    assert retry.preserved_outfits == 1
    assert retry.preserved_scenes == 1
    assert len(session.scalars(select(OutfitVariant)).all()) == 1
    assert len(session.scalars(select(SceneVisualVersion)).all()) == 1

    second_section = ScriptSection(
        task_id=task.id,
        section_no=2,
        page_start=3,
        page_end=4,
        title="追踪",
        description="林继续在车站追踪线索。",
        status=ScriptSectionStatus.GENERATING,
    )
    session.add(second_section)
    session.commit()
    second = service._save_section_visual_settings(
        task_id=task.id,
        section_id=second_section.id,
        outline_version_id=outline.id,
        scenes=[_scene_payload()],
        characters=[
            {
                **_character_payload("深蓝风衣，衣角被雨水打湿并沾有灰尘"),
                "current_accessories": "银色怀表（此时握在手中）",
                "negative_constraints": "不要显示追踪者正脸",
            }
        ],
    )
    assert second.reused_outfits == 1
    assert second.preserved_scenes == 1
    assigned_outfit_ids = {
        item.outfit_variant_id
        for item in session.scalars(select(ScriptCharacter)).all()
    }
    assert assigned_outfit_ids == {outfit.id}
    assert len(session.scalars(select(OutfitVariant)).all()) == 1
    assert outfit.negative_constraints == "不要改变眼睛颜色"


def test_continue_backfill_preserves_manual_bindings_and_skips_unmapped_character() -> None:
    session = _session()
    project, _outline, outline_character, task, section = _seed_script_context(session)
    manual_outfit = OutfitVariant(
        project_id=project.id,
        outline_character_id=outline_character.id,
        key="manual",
        version=1,
        name="人工确认造型",
        status=ApprovalStatus.APPROVED,
    )
    scene = ScriptScene(task=task, **_scene_payload("manual_station"))
    session.add_all([manual_outfit, scene])
    session.flush()
    manual_scene_version = SceneVisualVersion(
        project_id=project.id,
        script_scene=scene,
        version=1,
        landmarks_json='["人工场景母版"]',
        status=ApprovalStatus.APPROVED,
    )
    session.add(manual_scene_version)
    session.flush()
    scene.selected_visual_version_id = manual_scene_version.id
    mapped_character = ScriptCharacter(
        section=section,
        outline_character=outline_character,
        outfit_variant=manual_outfit,
        **_character_payload("人工确认风衣"),
    )
    unmapped_character = ScriptCharacter(
        section=section,
        character_key="passerby",
        name="路人",
        section_role="背景人物",
        current_clothing="灰色外套",
        visual_anchors="模糊背影",
    )
    session.add_all([mapped_character, unmapped_character])
    session.commit()

    summary = ScriptService(ComicRepository(session))._ensure_task_visual_bible_drafts(
        task.id
    )

    session.refresh(mapped_character)
    session.refresh(scene)
    assert summary.preserved_outfits == 1
    assert summary.preserved_scenes == 1
    assert summary.skipped_characters == 1
    assert mapped_character.outfit_variant_id == manual_outfit.id
    assert scene.selected_visual_version_id == manual_scene_version.id
    assert len(session.scalars(select(OutfitVariant)).all()) == 1
    assert len(session.scalars(select(SceneVisualVersion)).all()) == 1
