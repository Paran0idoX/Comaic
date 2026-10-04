import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.comic import (
    ComicImage,
    ComicPage,
    ComicProject,
    ImageSpec,
    OutlineCharacter,
    OutlineVersion,
    OutfitVariant,
    ReferenceSubject,
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
    ImageSpecStaleReason,
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
    assert "holding brass_key" not in tag_spec["positive_prompt"]
    assert "object north_door closed" in tag_spec["positive_prompt"]
    assert "never change eye color" in tag_spec["negative_prompt"]
    assert "no red coat" in tag_spec["negative_prompt"]
    assert "no extra windows" in tag_spec["negative_prompt"]
    assert "lora" not in tag_spec["required_capabilities"]
    assert tag_spec["spec"]["subjects"][0]["props"] == []
    assert hybrid_spec["positive_prompt"] == (
        f"{natural_spec['positive_prompt']}\n{tag_spec['positive_prompt']}"
    )
    assert len({item["shot_plan_id"] for item in page_two_specs}) == 1
    assert tag_spec["spec"]["reference_plan"] == natural_spec["spec"]["reference_plan"] == hybrid_spec["spec"]["reference_plan"]
    assert tag_spec["spec"]["style"] == {}
    assert session.get(ImageSpec, tag_spec["id"]).style_profile_id is None
    assert "clean comic line art" not in tag_spec["positive_prompt"]
    session.refresh(pages[0])
    assert pages[0].status == ComicPageStatus.SPEC_READY

    compilation = service.repository.list_compilations(task.id)[0]
    page_states = {
        snapshot.page.page_no: json.loads(snapshot.state_json)
        for snapshot in compilation.snapshots
    }
    assert page_states[1]["scene"]["object_states"]["north_door"] == "closed"
    assert page_states[2]["scene"]["object_states"]["north_door"] == "closed"
    assert page_states[2]["characters"][0]["held_props"] == []
    assert compilation.events == []
    assert compilation.llm_config_id is None and compilation.llm_model is None
    assert not {"continuity", "continuity_progress"} & {name for name, _ in events}
    assert page_states[1]["page_script"]["summary"] == pages[0].summary
    assert page_states[1]["characters"][0]["identity"] == page_states[2]["characters"][0]["identity"]
    assert all("amber eyes and a small left-eyebrow scar" in item["positive_prompt"] for item in specs)


@pytest.mark.asyncio
async def test_spec_list_reports_current_pages_and_stale_reasons(monkeypatch) -> None:
    """就绪度读取实时来源，页面修改只使本页失效，历史提示词和快照保持不变。"""

    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", FakeShotPlannerAgent)
    session = _session()
    task, pages, _style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))
    async for _event in service.stream_compile_task(
        task_id=task.id, style_profile_id=None, shot_planner_preset_id=None,
        negative_prompt_preset_id=None, generation_mode=GenerationMode.PREVIEW,
    ):
        pass
    original = service.list_task_specs(task_id=task.id)
    assert len(original) == 6
    assert all(not item["spec_stale"] and not item["stale_reasons"] for item in original)
    pages[0].summary += " revised"
    session.commit()
    updated = service.list_task_specs(task_id=task.id)
    assert all(item["spec_stale"] for item in updated if item["page_id"] == pages[0].id)
    assert all(not item["spec_stale"] for item in updated if item["page_id"] == pages[1].id)
    assert all(ImageSpecStaleReason.PAGE_SCRIPT_CHANGED in item["stale_reasons"]
               for item in updated if item["page_id"] == pages[0].id)
    asset = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.IDENTITY_FACE))
    asset.version += 1
    session.commit()
    updated = service.list_task_specs(task_id=task.id)
    assert all(ImageSpecStaleReason.CHARACTER_INPUTS_CHANGED in item["stale_reasons"] for item in updated)
    scene = pages[0].script_scene.selected_visual_version
    scene.status = ApprovalStatus.DRAFT
    session.commit()
    updated = service.list_task_specs(task_id=task.id)
    assert all(ImageSpecStaleReason.SCENE_INPUTS_CHANGED in item["stale_reasons"] for item in updated)
    for item in updated:
        spec = session.get(ImageSpec, item["id"])
        spec.source_hash = "old-rules"
    session.commit()
    updated = service.list_task_specs(task_id=task.id)
    assert all(ImageSpecStaleReason.PROMPT_RULES_CHANGED in item["stale_reasons"] for item in updated)
    assert [(item["id"], item["positive_prompt"], item["snapshot_id"]) for item in updated] == [
        (item["id"], item["positive_prompt"], item["snapshot_id"]) for item in original
    ]


def test_reference_changes_stale_source_and_historical_style_changes_do_not() -> None:
    session = _session()
    task, pages, style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))
    initial = service.current_page_context_source_hash(task.id)
    style.positive_tag = "changed historical style"
    style_asset = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.STYLE_REFERENCE))
    style_asset.version += 1
    session.commit()
    assert service.current_page_context_source_hash(task.id) == initial

    character_asset = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.IDENTITY_FACE))
    character_asset.version += 1
    session.commit()
    revised = service.current_page_context_source_hash(task.id)
    assert revised != initial
    character_asset.status = ApprovalStatus.DRAFT
    session.commit()
    revoked = service.current_page_context_source_hash(task.id)
    assert revoked != revised
    character_asset.status = ApprovalStatus.APPROVED
    session.commit()
    assert service.current_page_context_source_hash(task.id) == revised

    subject = ReferenceSubject(project_id=task.project_id, entity_type=VisualEntityType.SCENE, key="catalog_room", name="Catalog room", description="round skylight")
    session.add(subject)
    session.flush()
    pages[0].script_scene.reference_subject_id = subject.id
    session.commit()
    bound = service.current_page_context_source_hash(task.id)
    assert bound != revised
    subject.description = "square skylight"
    session.commit()
    assert service.current_page_context_source_hash(task.id) != bound


def test_asset_metadata_clothing_and_subject_association_are_part_of_source_hash() -> None:
    session = _session()
    task, pages, _style = _seed_project(session)
    service = ImageSpecService(ImageSpecRepository(session))
    asset = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.IDENTITY_FACE))
    previous = service.current_page_context_source_hash(task.id)
    for field, value in [("outfit_variant_id", pages[0].visual_characters[0].outfit_variant_id), ("mime_type", "image/webp"), ("width", 240), ("height", 360), ("local_path", "independent-original.webp")]:
        setattr(asset, field, value)
        session.commit()
        current = service.current_page_context_source_hash(task.id)
        assert current != previous
        previous = current


def test_scene_baseline_separates_generic_and_version_specific_subject_assets() -> None:
    session = _session()
    task, pages, _style = _seed_project(session)
    scene = pages[0].script_scene
    selected_version = scene.selected_visual_version
    first = ReferenceSubject(project_id=task.project_id, entity_type=VisualEntityType.SCENE, key="first_scene", name="First scene")
    second = ReferenceSubject(project_id=task.project_id, entity_type=VisualEntityType.SCENE, key="second_scene", name="Second scene")
    other_version = SceneVisualVersion(project_id=task.project_id, script_scene_id=scene.id, version=2, status=ApprovalStatus.APPROVED)
    session.add_all([first, second, other_version])
    session.flush()
    scene.reference_subject_id = first.id

    def scoped_asset(subject, entity_id, locator):
        asset = VisualAsset(project_id=task.project_id, entity_type=VisualEntityType.SCENE, reference_subject_id=subject.id, entity_id=entity_id, entity_key=subject.key, role=VisualAssetRole.SCENE_MASTER, version=1, storage_kind=VisualAssetStorageKind.RENDERER_LOCATOR, renderer_locator=locator, source=VisualAssetSource.RENDERER_LOCATOR, status=ApprovalStatus.APPROVED)
        session.add(asset)
        session.flush()
        return asset

    generic = scoped_asset(first, None, "first-generic.png")
    specific = scoped_asset(first, selected_version.id, "first-selected-version.png")
    other_specific = scoped_asset(first, other_version.id, "first-other-version.png")
    wrong_subject = scoped_asset(second, selected_version.id, "second-selected-version.png")
    session.commit()
    service = ImageSpecService(ImageSpecRepository(session))

    def baseline():
        context = service._prepare_context(task_id=task.id, style_profile_id=None, shot_planner_preset_id=None, negative_prompt_preset_id=None)
        return service._scene_baselines(context)[scene.scene_key]

    result = baseline()
    assert [asset["id"] for asset in result["catalog_assets"]] == [generic.id]
    version_ids = {asset["id"] for asset in result["assets"]}
    assert specific.id in version_ids
    assert wrong_subject.id not in version_ids
    assert other_specific.id not in version_ids
    # 老的NULL条目归属素材仍按当前选用版本兼容，不把entity_id解释成目录ID。
    assert any(asset["reference_subject_id"] is None for asset in result["assets"])

    scene.reference_subject_id = second.id
    session.commit()
    rebound = baseline()
    assert rebound["catalog_assets"] == []
    assert specific.id not in {asset["id"] for asset in rebound["assets"]}
    assert wrong_subject.id in {asset["id"] for asset in rebound["assets"]}


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
async def test_retired_mode_parameter_reuses_the_same_prepared_prompts(monkeypatch) -> None:
    class CountingShotPlanner(FakeShotPlannerAgent):
        calls: list[int] = []

        async def plan(self, *, page, **kwargs):
            type(self).calls.append(page["page_no"])
            return await super().plan(**kwargs)

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
    assert reused_plans == []
    resume = next(payload for event, payload in final_events if event == "resume")
    assert resume["completed_specs"] == 6
    assert next(payload for event, payload in final_events if event == "start")["generation_mode"] == "preview"


@pytest.mark.parametrize("kind,model", [(VisualEntityType.OUTFIT, OutfitVariant), (VisualEntityType.SCENE, SceneVisualVersion)])
def test_retiring_selected_settings_invalidates_source_hash_without_removing_images(kind, model):
    from backend.repositories.visual_bible_repository import VisualBibleRepository
    from backend.services.visual_bible_service import VisualBibleService
    session = _session()
    task, pages, _style = _seed_project(session)
    spec_service = ImageSpecService(ImageSpecRepository(session))
    previous = spec_service.current_page_context_source_hash(task.id)
    entity = session.scalar(select(model))
    asset_ids = list(session.scalars(select(VisualAsset.id)))
    VisualBibleService(VisualBibleRepository(session)).set_configuration_status(
        kind=kind.value, item_id=entity.id, status=ApprovalStatus.ARCHIVED,
    )
    assert spec_service.current_page_context_source_hash(task.id) != previous
    assert list(session.scalars(select(VisualAsset.id))) == asset_ids
    assert all(page.script_scene is not None and page.visual_characters for page in pages)
    session.close()
