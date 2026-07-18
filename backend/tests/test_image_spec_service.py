import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.comic import (
    ComicImage,
    ComicPage,
    ComicProject,
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
    OutlineVersionStatus,
    PageScriptReviewStatus,
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
from backend.repositories.comic_repository import ComicRepository
from backend.services.image_spec_service import ImageSpecService
from backend.services.script_service import ScriptService
from backend.i18n.errors import AppError


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
            script_review_status=PageScriptReviewStatus.PASSED,
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
        positive_tag="clean comic line art",
        negative_tag="photorealistic",
        positive_natural_language="Use clean comic line art.",
        negative_natural_language="Do not use photorealistic rendering.",
        color_palette_json="[]",
        lighting="cinematic contrast",
        status=ApprovalStatus.APPROVED,
    )
    session.add_all([character, *pages, scene_version, style])
    session.flush()

    def asset(
        entity_type,
        entity_id,
        role,
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
                storage_kind=VisualAssetStorageKind.RENDERER_LOCATOR,
                renderer_locator=role.value,
                sha256=role.value.encode().hex().ljust(64, "0")[:64],
                version=1,
                status=ApprovalStatus.APPROVED,
                source=VisualAssetSource.RENDERER_LOCATOR,
            )
        )

    asset(VisualEntityType.CHARACTER, outline_character.id, VisualAssetRole.IDENTITY_FACE)
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
    return task, pages, style


def test_page_compilation_failure_preserves_final_readiness_code() -> None:
    session = _session()
    _task, pages, _style = _seed_project(session)

    failure = ImageSpecService._page_compilation_failure(
        pages[0],
        ValueError(
            "Final image spec is missing canonical conditions: "
            "image_spec.identity_asset_missing"
        ),
    )

    assert failure["code"] == "image_spec.final_conditions_missing"


def test_manual_page_edit_preserves_scene_and_character_bindings() -> None:
    session = _session()
    task, pages, _style = _seed_project(session)
    original = pages[0]
    original_scene_id = original.scene_id
    original_character_ids = [item.id for item in original.visual_characters]

    updated = ScriptService(ComicRepository(session)).upsert_manual_page_script(
        project_id=task.project_id,
        page_no=original.page_no,
        task_id=task.id,
        summary="Updated repair step",
        characters=original.characters,
        clothing=original.clothing,
        scene=original.scene,
        composition=original.composition,
        character_action=original.character_action,
        dialogue=original.dialogue,
    )

    assert updated.scene_id == original_scene_id
    assert [item.id for item in updated.visual_characters] == original_character_ids
    assert updated.script_review_status == PageScriptReviewStatus.UNREVIEWED


def test_manual_page_edit_clears_stale_selection_but_preserves_candidate() -> None:
    session = _session()
    task, pages, _style = _seed_project(session)
    original = pages[0]
    candidate = ComicImage(
        page=original,
        image_url="/api/images/selected.png",
        local_path="outputs/selected.png",
        seed=123,
        is_selected=True,
    )
    session.add(candidate)
    session.flush()
    original.selected_image_id = candidate.id
    session.commit()

    updated = ScriptService(ComicRepository(session)).upsert_manual_page_script(
        project_id=task.project_id,
        page_no=original.page_no,
        task_id=task.id,
        summary="A revised repair step",
        characters=original.characters,
        clothing=original.clothing,
        scene=original.scene,
        composition=original.composition,
        character_action=original.character_action,
        dialogue=original.dialogue,
    )

    assert updated.selected_image_id is None
    assert session.get(ComicImage, candidate.id) is candidate
    assert candidate.is_selected is False


def test_image_spec_compile_rejects_manually_edited_unreviewed_page() -> None:
    session = _session()
    task, pages, style = _seed_project(session)
    original = pages[0]
    ScriptService(ComicRepository(session)).upsert_manual_page_script(
        project_id=task.project_id,
        page_no=original.page_no,
        task_id=task.id,
        summary="A revised repair step",
        characters=original.characters,
        clothing=original.clothing,
        scene=original.scene,
        composition=original.composition,
        character_action=original.character_action,
        dialogue=original.dialogue,
    )

    with pytest.raises(AppError) as exc_info:
        ImageSpecService(ImageSpecRepository(session))._prepare_context(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
        )

    assert exc_info.value.code == "script.pages_not_reviewed"
    assert exc_info.value.status_code == 409
    assert exc_info.value.params == {"pages": "1"}


@pytest.mark.asyncio
async def test_full_compile_generates_three_prompt_specs_from_shared_visual_truth(
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
    task, pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    events = [
        item
        async for item in service.stream_compile_task(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.FINAL,
            concurrency=2,
        )
    ]

    assert events[-1][0] == "done"
    assert events[-1][1]["total_specs"] == 6
    specs = service.list_task_specs(task_id=task.id)
    assert len(specs) == 6
    page_two_specs = [item for item in specs if item["page_no"] == 2]
    tag_spec = next(item for item in page_two_specs if item["prompt_type"] == "tag")
    natural_spec = next(
        item for item in page_two_specs if item["prompt_type"] == "natural_language"
    )
    hybrid_spec = next(item for item in page_two_specs if item["prompt_type"] == "hybrid")

    assert "free text that must not override" not in tag_spec["positive_prompt"]
    assert "navy repair coat" in tag_spec["positive_prompt"]
    assert "holding brass_key" in tag_spec["positive_prompt"]
    assert "object north_door open" in tag_spec["positive_prompt"]
    assert "never change eye color" in tag_spec["negative_prompt"]
    assert "no red coat" in tag_spec["negative_prompt"]
    assert "no extra windows" in tag_spec["negative_prompt"]
    assert "lora" not in tag_spec["required_capabilities"]
    assert tag_spec["spec"]["subjects"][0]["props"][0]["prop_key"] == "brass_key"
    assert hybrid_spec["positive_prompt"] == (
        f"{natural_spec['positive_prompt']}\n{tag_spec['positive_prompt']}"
    )
    assert len({item["shot_plan_id"] for item in page_two_specs}) == 1
    session.refresh(pages[0])
    assert pages[0].status == ComicPageStatus.SPEC_READY

    compilation = service.repository.list_compilations(task.id)[0]
    page_states = {
        snapshot.page.page_no: json.loads(snapshot.state_json)
        for snapshot in compilation.snapshots
    }
    assert page_states[1]["scene"]["object_states"]["north_door"] == "closed"
    assert page_states[2]["scene"]["object_states"]["north_door"] == "open"
    assert page_states[2]["characters"][0]["held_props"] == ["brass_key"]


@pytest.mark.asyncio
async def test_llm_cannot_override_locked_accessory_description(monkeypatch) -> None:
    class AccessoryOverrideAgent:
        VERSION = "test"

        async def extract(self, **_kwargs):
            return [
                {
                    "page_no": 1,
                    "sequence_no": 1,
                    "event_type": "set_accessory",
                    "target_type": "character",
                    "target_key": "alice",
                    "timing": "after_page",
                    "payload": {
                        "accessory_key": "tool_belt",
                        "value": "removed and placed on the desk",
                    },
                }
            ]

    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        AccessoryOverrideAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        FakeShotPlannerAgent,
    )
    session = _session()
    task, _pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    async for _event in service.stream_compile_task(
        task_id=task.id,
        style_profile_id=style.id,
        shot_planner_preset_id=None,
        negative_prompt_preset_id=None,
        generation_mode=GenerationMode.FINAL,
    ):
        pass

    compilation = service.repository.list_compilations(task.id)[0]
    page_two = next(item for item in compilation.snapshots if item.page.page_no == 2)
    character = json.loads(page_two.state_json)["characters"][0]
    assert character["accessories"]["description"] == "red tool belt"
    assert character["accessories"]["states"] == {}


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
    task, _pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))
    async for _event in service.stream_compile_task(
        task_id=task.id,
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


@pytest.mark.asyncio
async def test_continuity_reducer_failure_retries_with_persisted_audit(monkeypatch) -> None:
    class RetryContinuityAgent:
        VERSION = "test"
        calls = 0

        async def extract(self, **_kwargs):
            type(self).calls += 1
            if type(self).calls == 1:
                return [
                    {
                        "page_no": 1,
                        "sequence_no": 1,
                        "event_type": "drop_prop",
                        "target_type": "character",
                        "target_key": "alice",
                        "timing": "before_page",
                        "payload": {"prop_key": "brass_key"},
                    }
                ]
            return []

    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        RetryContinuityAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        FakeShotPlannerAgent,
    )
    session = _session()
    task, _pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    events = [
        item
        async for item in service.stream_compile_task(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.PREVIEW,
        )
    ]

    assert events[-1][0] == "done"
    attempts = service.repository.list_compilations(task.id)
    assert [item.status.value for item in attempts[:2]] == ["succeeded", "failed"]
    assert "does not hold prop" in (attempts[1].error_message or "")
    assert RetryContinuityAgent.calls == 2


@pytest.mark.asyncio
async def test_partial_shot_plans_are_persisted_and_next_compile_resumes(monkeypatch) -> None:
    class PartialShotPlanner(FakeShotPlannerAgent):
        async def plan(self, *, page, **kwargs):
            if page["page_no"] == 2:
                raise ValueError("simulated page two planning failure")
            return await super().plan(**kwargs)

    class CountingShotPlanner(FakeShotPlannerAgent):
        calls: list[int] = []

        async def plan(self, *, page, **kwargs):
            type(self).calls.append(page["page_no"])
            return await super().plan(**kwargs)

    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        FakeContinuityEventAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        PartialShotPlanner,
    )
    session = _session()
    task, _pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    first_events = []
    with pytest.raises(AppError, match="ImageSpec compilation"):
        async for item in service.stream_compile_task(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.PREVIEW,
            concurrency=2,
        ):
            first_events.append(item)
    assert len(service.list_task_specs(task_id=task.id)) == 3
    first_attempt = service.list_image_spec_compilations(task.id)[0]
    assert first_attempt["status"] == "failed"
    assert first_attempt["completed_pages"] == 1
    assert [item["page_no"] for item in first_attempt["failed_pages"]] == [2]
    assert any(event == "page_error" for event, _payload in first_events)

    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        CountingShotPlanner,
    )
    second_events = [
        item
        async for item in service.stream_compile_task(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.PREVIEW,
            concurrency=2,
        )
    ]

    assert CountingShotPlanner.calls == [2]
    assert any(
        event == "resume" and payload["page_nos"] == [1]
        for event, payload in second_events
    )
    assert len(service.list_task_specs(task_id=task.id)) == 6
    assert service.list_image_spec_compilations(task.id)[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_prompt_mode_change_reuses_model_independent_shot_plans(monkeypatch) -> None:
    class CountingShotPlanner(FakeShotPlannerAgent):
        calls: list[int] = []

        async def plan(self, *, page, **kwargs):
            type(self).calls.append(page["page_no"])
            return await super().plan(**kwargs)

    monkeypatch.setattr(
        "backend.services.image_spec_service.ContinuityEventAgent",
        FakeContinuityEventAgent,
    )
    monkeypatch.setattr(
        "backend.services.image_spec_service.ShotPlannerAgent",
        CountingShotPlanner,
    )
    session = _session()
    task, _pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))

    async for _event in service.stream_compile_task(
        task_id=task.id,
        style_profile_id=style.id,
        shot_planner_preset_id=None,
        negative_prompt_preset_id=None,
        generation_mode=GenerationMode.PREVIEW,
    ):
        pass
    assert sorted(CountingShotPlanner.calls) == [1, 2]
    CountingShotPlanner.calls.clear()

    final_events = [
        item
        async for item in service.stream_compile_task(
            task_id=task.id,
            style_profile_id=style.id,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            generation_mode=GenerationMode.FINAL,
        )
    ]

    assert CountingShotPlanner.calls == []
    reused_plans = [
        payload for event, payload in final_events if event == "shot_plan"
    ]
    assert len(reused_plans) == 2
    assert all(item["reused"] for item in reused_plans)
