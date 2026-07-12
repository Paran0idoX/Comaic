import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.comic import (
    ComicPage,
    ComicProject,
    ModelProfile,
    OutlineCharacter,
    OutlineVersion,
    OutfitVariant,
    SceneVisualVersion,
    ScriptCharacter,
    ScriptGenerationTask,
    ScriptScene,
    ScriptSection,
    Session as BusinessSession,
    StyleProfile,
    VisualAsset,
)
from backend.models.database import Base
from backend.models.enums import (
    ApprovalStatus,
    ComicPageStatus,
    GenerationMode,
    ModelFamily,
    OutlineVersionStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
    SessionPurpose,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService


class FakeContinuityEventAgent:
    VERSION = "test"

    async def extract(self, **_kwargs):
        return [
            {
                "page_no": 1,
                "sequence_no": 1,
                "event_type": "pick_up_prop",
                "target_type": "character",
                "target_key": "alice",
                "timing": "after_page",
                "payload": {"prop_key": "brass_key"},
            },
            {
                "page_no": 1,
                "sequence_no": 2,
                "event_type": "set_door_state",
                "target_type": "scene",
                "target_key": "workshop",
                "timing": "after_page",
                "payload": {"door_key": "north_door", "value": "open"},
            },
        ]


class FakeShotPlannerAgent:
    VERSION = "test"

    def __init__(self, **_kwargs):
        pass

    async def plan(self, *, snapshot, **_kwargs):
        return {
            "camera": {
                "shot_type": "medium shot",
                "angle": "eye level",
                "lens_mm": 50,
            },
            "subjects": [
                {
                    "character_key": character["character_key"],
                    "action": "checks the generator",
                    "pose": "leaning forward",
                    "expression": "focused",
                    "gaze": "generator",
                    "orientation": "three-quarter view",
                    "region": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.5,
                        "height": 0.8,
                    },
                    "depth_order": 1,
                    "control_requirements": [],
                }
                for character in snapshot["characters"]
            ],
            "scene": {
                "framing_notes": "generator remains behind Alice",
                "focal_point": "Alice and the generator",
                "negative_space": "upper right",
                "control_requirements": [],
            },
            "render_text": False,
        }


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_project(session):
    project = ComicProject(title="Consistency")
    conversation = BusinessSession(
        project=project,
        thread_id="thread-1",
        purpose=SessionPurpose.OUTLINE,
    )
    outline = OutlineVersion(
        project=project,
        session=conversation,
        version_no=1,
        content="Alice repairs an old generator.",
        status=OutlineVersionStatus.ACTIVE,
    )
    outline_character = OutlineCharacter(
        outline_version=outline,
        character_key="alice",
        name="Alice",
        role="mechanic",
        appearance="amber eyes and a small left-eyebrow scar",
        visual_anchors="small scar below the left eyebrow",
        negative_constraints="never change eye color",
        default_hairstyle="short black bob",
        default_clothing="work shirt",
    )
    task = ScriptGenerationTask(
        project=project,
        outline_version=outline,
        status=ScriptGenerationTaskStatus.SUCCEEDED,
        mode=ScriptGenerationMode.BATCH,
        total_pages=2,
    )
    section = ScriptSection(
        task=task,
        section_no=1,
        page_start=1,
        page_end=2,
        title="Repair",
        description="Repair the generator",
        status=ScriptSectionStatus.COMPLETED,
    )
    scene = ScriptScene(
        task=task,
        scene_key="workshop",
        name="Old workshop",
        location_type="interior",
        time_of_day="night",
        lighting="warm desk lamp",
        weather="rain",
        environment_details="dense shelves and a rusted generator",
        visual_anchors="arched east window",
        negative_constraints="no extra windows",
    )
    session.add_all([project, outline_character, task, section, scene])
    session.flush()

    outfit = OutfitVariant(
        project_id=project.id,
        outline_character_id=outline_character.id,
        key="repair_coat",
        version=1,
        name="Repair coat",
        garment_components_json='["navy repair coat"]',
        layer_order_json='["shirt","coat"]',
        colors_json='["navy","brass"]',
        materials_json='["canvas"]',
        patterns_json="[]",
        accessories_json='["red tool belt"]',
        trigger_tokens_json='["repair_coat_v1"]',
        negative_constraints="no red coat",
        status=ApprovalStatus.APPROVED,
    )
    session.add(outfit)
    session.flush()
    character = ScriptCharacter(
        section=section,
        outline_character=outline_character,
        outfit_variant=outfit,
        character_key="alice",
        name="Alice",
        current_hairstyle="short black bob",
        current_clothing="free text that must not override the outfit",
        current_accessories="red tool belt",
        current_state="alert",
        negative_constraints="keep the eyebrow scar",
    )
    pages = [
        ComicPage(
            project=project,
            section=section,
            script_scene=scene,
            page_no=page_no,
            summary=f"Repair step {page_no}",
            characters="Alice",
            clothing="repair coat",
            scene="workshop",
            composition="medium shot",
            character_action="checks the generator",
            dialogue="No text",
            status=ComicPageStatus.SCRIPT_READY,
        )
        for page_no in (1, 2)
    ]
    for page in pages:
        page.visual_characters.append(character)
    scene_version = SceneVisualVersion(
        project_id=project.id,
        script_scene=scene,
        version=1,
        landmarks_json='["arched east window"]',
        spatial_relations_json='{"generator":"below_window"}',
        camera_presets_json="[]",
        object_states_json='{"north_door":"closed"}',
        color_palette_json='["navy","amber"]',
        lighting_state_json='{"desk_lamp":"on"}',
        status=ApprovalStatus.APPROVED,
    )
    scene.selected_visual_version = scene_version
    style = StyleProfile(
        project_id=project.id,
        key="comic",
        version=1,
        name="Comic",
        model_family=ModelFamily.GENERIC,
        positive_tokens="clean comic line art",
        negative_tokens="photorealistic",
        color_palette_json="[]",
        lighting="cinematic contrast",
        render_defaults_json='{"width":1024,"height":1536}',
        status=ApprovalStatus.APPROVED,
    )
    anima = ModelProfile(
        name="Anima local",
        family=ModelFamily.ANIMA,
        variant="local",
        checkpoint_name="anima.safetensors",
        compiler_key="anima_v1",
        compiler_version="1",
        component_manifest_json="{}",
        default_render_json='{"steps":28}',
        is_enabled=True,
        is_default=True,
    )
    z_image = ModelProfile(
        name="Z-Image local",
        family=ModelFamily.Z_IMAGE,
        variant="local",
        checkpoint_name="z-image.safetensors",
        compiler_key="z_image_v1",
        compiler_version="1",
        component_manifest_json="{}",
        default_render_json='{"steps":30}',
        is_enabled=True,
        is_default=True,
    )
    session.add_all([character, *pages, scene_version, style, anima, z_image])
    session.flush()

    def asset(
        entity_type,
        entity_id,
        role,
        family=ModelFamily.GENERIC,
        *,
        entity_key=None,
    ):
        session.add(
            VisualAsset(
                project_id=project.id,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_key=entity_key,
                role=role,
                model_family=family,
                storage_kind=VisualAssetStorageKind.RENDERER_LOCATOR,
                renderer_locator=f"{role.value}-{family.value}",
                sha256=(role.value + family.value).encode().hex().ljust(64, "0")[:64],
                version=1,
                status=ApprovalStatus.APPROVED,
                source=VisualAssetSource.RENDERER_LOCATOR,
            )
        )

    asset(VisualEntityType.CHARACTER, outline_character.id, VisualAssetRole.IDENTITY_FACE)
    asset(
        VisualEntityType.CHARACTER,
        outline_character.id,
        VisualAssetRole.LORA,
        ModelFamily.Z_IMAGE,
    )
    asset(VisualEntityType.OUTFIT, outfit.id, VisualAssetRole.OUTFIT_FRONT)
    asset(VisualEntityType.SCENE, scene_version.id, VisualAssetRole.SCENE_MASTER)
    asset(VisualEntityType.STYLE, style.id, VisualAssetRole.STYLE_REFERENCE)
    asset(
        VisualEntityType.PROP,
        None,
        VisualAssetRole.PROP_REFERENCE,
        entity_key="brass_key",
    )
    session.commit()
    return task, pages, style, anima, z_image


@pytest.mark.asyncio
async def test_full_compile_uses_current_visual_truth_and_model_compatible_assets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        FakeContinuityEventAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        FakeShotPlannerAgent,
    )
    session = _session()
    task, pages, style, anima, z_image = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    events = [
        item
        async for item in service.stream_compile_task(
            task_id=task.id,
            model_profile_ids=[anima.id, z_image.id],
            primary_model_profile_id=anima.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.FINAL,
            concurrency=2,
        )
    ]

    assert events[-1][0] == "done"
    assert events[-1][1]["total_specs"] == 4
    specs = service.list_task_specs(task_id=task.id)
    assert len(specs) == 4
    page_two_specs = [item for item in specs if item["page_no"] == 2]
    anima_spec = next(item for item in page_two_specs if item["model_family"] == "anima")
    z_image_spec = next(item for item in page_two_specs if item["model_family"] == "z_image")

    assert "free text that must not override" not in anima_spec["positive_prompt"]
    assert "navy repair coat" in anima_spec["positive_prompt"]
    assert "holding brass_key" in anima_spec["positive_prompt"]
    assert "object north_door open" in anima_spec["positive_prompt"]
    assert "never change eye color" in anima_spec["negative_prompt"]
    assert "no red coat" in anima_spec["negative_prompt"]
    assert "no extra windows" in anima_spec["negative_prompt"]
    assert anima_spec["spec"]["subjects"][0]["identity"]["loras"] == []
    assert len(z_image_spec["spec"]["subjects"][0]["identity"]["loras"]) == 1
    assert "lora" not in anima_spec["required_capabilities"]
    assert "lora" in z_image_spec["required_capabilities"]
    assert anima_spec["spec"]["subjects"][0]["props"][0]["prop_key"] == "brass_key"
    assert pages[0].image_prompt

    compilation = service.repository.list_compilations(task.id)[0]
    page_states = {
        snapshot.page.page_no: json.loads(snapshot.state_json)
        for snapshot in compilation.snapshots
    }
    assert page_states[1]["scene"]["object_states"]["north_door"] == "closed"
    assert page_states[2]["scene"]["object_states"]["north_door"] == "open"
    assert page_states[2]["characters"][0]["held_props"] == ["brass_key"]


@pytest.mark.asyncio
async def test_manual_event_revision_recomputes_current_system_events(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        FakeContinuityEventAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        FakeShotPlannerAgent,
    )
    session = _session()
    task, _pages, style, anima, _z_image = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))
    async for _event in service.stream_compile_task(
        task_id=task.id,
        model_profile_ids=[anima.id],
        primary_model_profile_id=anima.id,
        style_profile_id=style.id,
        shot_planner_preset_id=None,
        negative_prompt_preset_id=None,
        generation_mode=GenerationMode.FINAL,
    ):
        pass
    original = service.repository.list_compilations(task.id)[0]

    character = session.scalar(select(ScriptCharacter))
    character.current_state = "calm"
    session.commit()
    revised = await service.replace_events(compilation_id=original.id, events=[])
    first_snapshot = min(revised.snapshots, key=lambda item: item.page.page_no)
    state = json.loads(first_snapshot.state_json)

    assert state["characters"][0]["conditions"]["section_state"] == "calm"
