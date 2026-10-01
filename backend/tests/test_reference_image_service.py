"""通用参考图目录和任务使用内存数据库与模拟 Provider，覆盖原图和归属边界。"""

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy.orm import sessionmaker

import backend.api.reference_images as reference_api
import backend.services.character_reference_service as runtime_module
from backend.api.reference_images import reference_task_response
from backend.api.schemas.reference_images import CreateReferenceTaskRequest
from backend.i18n.errors import AppError
from backend.models.comic import (ComicImage, ComicPage, ComicProject, OutfitVariant,
    SceneVisualVersion, ScriptGenerationTask, ScriptScene)
from backend.models.enums import (ApprovalStatus, GenerationRunStatus, GenerationTaskStatus, ImageGenerationProvider,
    ReferenceSourceMode, ScriptGenerationMode, VisualAssetRole, VisualEntityType)
from backend.repositories.character_reference_repository import CharacterReferenceRepository
from backend.repositories.reference_subject_repository import ReferenceSubjectRepository
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.reference_catalog import CHARACTER_REFERENCE_ROLES, selected_task_roles
from backend.services.reference_image_service import ReferenceImageService
from backend.services.reference_subject_service import ReferenceSubjectService
from backend.services.visual_bible_service import VisualBibleService
from backend.tests.test_character_reference_service import FakeRenderer, _png_bytes, reference_fixture


@pytest.fixture()
def catalog_fixture(reference_fixture):
    fixture = reference_fixture
    fixture["service"] = ReferenceImageService(CharacterReferenceRepository(fixture["session"]),
        output_dir=fixture["tmp_path"] / "outputs", asset_root=fixture["tmp_path"] / "visual-assets")
    fixture["subjects"] = ReferenceSubjectService(ReferenceSubjectRepository(fixture["session"]))
    fixture["assets"] = VisualBibleService(VisualBibleRepository(fixture["session"]),
        asset_root=fixture["tmp_path"] / "visual-assets")
    return fixture


def _selection(fixture, roles=(VisualAssetRole.IDENTITY_SIDE,), **overrides):
    return {"project_id": fixture["project"].id, "entity_type": VisualEntityType.CHARACTER,
        "entity_id": fixture["character"].id, "tool_preset_id": fixture["tool"].id,
        "roles": roles, **overrides}


def _task(fixture, **selection):
    preview = fixture["service"].preview_reference_prompts(**selection)
    return fixture["service"].create_reference_task(candidate_count=2,
        prompts=preview["prompts"], **selection)


def _face(fixture, *, approve=True):
    return fixture["assets"].upload_asset(project_id=fixture["project"].id,
        entity_type=VisualEntityType.CHARACTER, entity_id=fixture["character"].id, entity_key=None,
        role=VisualAssetRole.IDENTITY_FACE, content=_png_bytes(), approve=approve)


def _image_tool(fixture, *, requires_canvas=False, capacity=3):
    tool = fixture["openai_tool"]
    tool.capabilities_json = json.dumps({"features": ["txt2img", "img2img"],
        "reference_images": {"max_images": capacity, "label_format": "picture_N",
            "transport": "json_data_url", "edit_endpoint_path": "images/edits",
            "requires_canvas": requires_canvas}})
    fixture["session"].commit()
    return tool


@pytest.mark.parametrize("roles", [(VisualAssetRole.IDENTITY_BACK,),
    (VisualAssetRole.IDENTITY_FACE, VisualAssetRole.IDENTITY_SIDE), CHARACTER_REFERENCE_ROLES])
def test_selected_roles_determine_candidate_runs_without_style(catalog_fixture, roles):
    fixture = catalog_fixture
    task = _task(fixture, **_selection(fixture, roles))
    assert len(task.runs) == len(roles) * 2
    assert selected_task_roles(task) == roles
    assert task.style_profile_id is None
    response = reference_task_response(task)
    assert response.selected_roles == list(roles)
    assert response.subject_name == fixture["character"].name
    assert response.progress["total"] == len(roles) * 2
    assert all("Ink Graphic Novel" not in run.positive_prompt for run in task.runs)
    for run in task.runs:
        if run.role in {VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK}:
            assert "front-facing" not in run.positive_prompt


def test_new_api_rejects_style_and_wrong_category_roles(catalog_fixture):
    fixture = catalog_fixture
    values = _selection(fixture)
    values.pop("project_id")
    with pytest.raises(ValidationError):
        CreateReferenceTaskRequest(**values, prompts={}, style_profile_id=fixture["style"].id)
    with pytest.raises(AppError) as exc:
        fixture["service"].preview_reference_prompts(**_selection(fixture, (VisualAssetRole.SCENE_MASTER,)))
    assert exc.value.code == "reference.roles_invalid"


def test_automatic_face_falls_back_for_text_tool_and_freezes_actual_images(catalog_fixture):
    fixture = catalog_fixture
    face = _face(fixture)
    selection = _selection(fixture)
    preview = fixture["service"].preview_reference_prompts(**selection)
    assert preview["sources"] == []
    assert preview["warnings"] == ["reference.auto.text_only_tool"]
    text_task = _task(fixture, **selection)
    assert json.loads(text_task.source_asset_ids_json) == []
    assert json.loads(text_task.runs[0].applied_spec_json)["reference_plan"]["warnings"] == preview["warnings"]
    tool = _image_tool(fixture)
    selection["tool_preset_id"] = tool.id
    task = _task(fixture, **selection)
    assert json.loads(task.source_asset_ids_json) == [face.id]
    spec = json.loads(task.runs[0].applied_spec_json)
    assert spec["reference_inputs"]["items"][0]["asset_id"] == face.id
    assert spec["reference_inputs"]["items"][0]["label"] == "Picture 1"
    assert spec["reference_inputs"]["items"][0]["local_path"] == face.local_path
    assert spec["reference_inputs"]["items"][0]["owner"]["key"] == "hero"
    assert spec["reference_inputs"]["items"][0]["purpose"] == "identity"


def test_face_role_does_not_implicitly_copy_face_and_none_means_text_only(catalog_fixture):
    fixture = catalog_fixture
    face = _face(fixture)
    tool = _image_tool(fixture)
    task = _task(fixture, **_selection(fixture,
        (VisualAssetRole.IDENTITY_FACE, VisualAssetRole.IDENTITY_BACK), tool_preset_id=tool.id))
    for run in task.runs:
        inputs = json.loads(run.applied_spec_json)["reference_inputs"]["items"]
        assert [item["asset_id"] for item in inputs] == ([] if run.role == VisualAssetRole.IDENTITY_FACE else [face.id])
    task = _task(fixture, **_selection(fixture, tool_preset_id=tool.id, source_mode=ReferenceSourceMode.NONE))
    assert json.loads(task.source_asset_ids_json) == []


def test_manual_inputs_reject_unapproved_foreign_and_unsupported_tool(catalog_fixture):
    fixture = catalog_fixture
    draft = _face(fixture, approve=False)
    selection = _selection(fixture, source_mode=ReferenceSourceMode.MANUAL, source_asset_ids=[draft.id])
    with pytest.raises(AppError) as exc:
        _task(fixture, **selection)
    assert exc.value.code == "reference.sources_invalid"
    face = _face(fixture)
    selection["source_asset_ids"] = [face.id]
    with pytest.raises(AppError) as exc:
        _task(fixture, **selection)
    assert exc.value.code == "reference.tool_capability_missing"
    other = ComicProject(title="Other")
    fixture["session"].add(other)
    fixture["session"].commit()
    selection["project_id"] = other.id
    with pytest.raises(AppError) as exc:
        fixture["service"]._source_assets(project_id=other.id, entity_type=VisualEntityType.CHARACTER,
            entity_id=None, roles=selection["roles"], source_mode=ReferenceSourceMode.MANUAL, source_asset_ids=[face.id])
    assert exc.value.code == "reference.sources_invalid"


def test_canvas_must_be_explicit_and_all_inputs_must_fit(catalog_fixture):
    fixture = catalog_fixture
    face = _face(fixture)
    tool = _image_tool(fixture, requires_canvas=True, capacity=1)
    selection = _selection(fixture, tool_preset_id=tool.id)
    with pytest.raises(AppError) as exc:
        _task(fixture, **selection)
    assert exc.value.code == "reference.input.canvas_required"
    task = _task(fixture, **{**selection, "canvas_asset_id": face.id})
    items = json.loads(task.runs[0].applied_spec_json)["reference_inputs"]["items"]
    assert len(items) == 1 and items[0]["purpose"] == "canvas"
    second = fixture["assets"].upload_asset(project_id=fixture["project"].id,
        entity_type=VisualEntityType.CHARACTER, entity_id=fixture["character"].id, entity_key=None,
        role=VisualAssetRole.IDENTITY_HALF_BODY, content=_png_bytes((1, 2, 3)), approve=True)
    with pytest.raises(AppError) as exc:
        _task(fixture, **{**selection, "canvas_asset_id": second.id})
    assert exc.value.code == "reference.input.capacity_exceeded"


def test_named_subjects_and_script_binding_are_project_scoped_and_idempotent(catalog_fixture):
    fixture = catalog_fixture
    session = fixture["session"]
    project = fixture["project"]
    task = ScriptGenerationTask(project_id=project.id, mode=ScriptGenerationMode.BATCH, total_pages=1)
    scene = ScriptScene(task=task, scene_key="station", name="Old station", environment_details="round clock")
    session.add_all([task, scene])
    session.commit()
    fixture["assets"].derive_script_visual_drafts(project_id=project.id, scenes=[scene], characters=[])
    assert scene.reference_subject_id is not None
    first = fixture["subjects"].list(project.id)
    fixture["subjects"].list(project.id)
    assert len(first) == 1
    assert first[0].key == f"script_scene_{scene.id}"
    explicit = fixture["subjects"].create(project_id=project.id, entity_type=VisualEntityType.SCENE,
        key="custom_station", name="Station with changes")
    fixture["subjects"].assign_scene(scene.id, explicit.id)
    fixture["subjects"].sync_script_scenes(project.id)
    assert scene.reference_subject_id == explicit.id
    with pytest.raises(AppError) as exc:
        fixture["subjects"].create(project_id=project.id, entity_type=VisualEntityType.SCENE,
            key=explicit.key, name="Duplicate")
    assert exc.value.code == "reference.subject_key_exists"
    other = ComicProject(title="Other")
    session.add(other)
    session.commit()
    foreign = fixture["subjects"].create(project_id=other.id, entity_type=VisualEntityType.SCENE, name="Foreign")
    with pytest.raises(AppError) as exc:
        fixture["subjects"].assign_scene(scene.id, foreign.id)
    assert exc.value.code == "reference.owner_invalid"


@pytest.mark.parametrize("category,role", [(VisualEntityType.SCENE, VisualAssetRole.SCENE_MASTER),
    (VisualEntityType.PROP, VisualAssetRole.PROP_REFERENCE)])
def test_subject_upload_and_generation_preserve_explicit_owner(catalog_fixture, category, role, monkeypatch):
    fixture = catalog_fixture
    subject = fixture["subjects"].create(project_id=fixture["project"].id, entity_type=category,
        name="Round clock", description="bronze case", negative_constraints="no numerals replaced")
    uploaded = fixture["assets"].upload_asset(project_id=fixture["project"].id,
        entity_type=category, entity_id=None, entity_key=None, reference_subject_id=subject.id,
        role=role, content=_png_bytes(), approve=True)
    assert uploaded.reference_subject_id == subject.id and uploaded.entity_id is None
    assert uploaded.entity_key == subject.key
    selection = _selection(fixture, (role,), entity_type=category, entity_id=None, reference_subject_id=subject.id)
    task = _task(fixture, **selection)
    assert task.outline_character_id is None
    assert "bronze case" in task.runs[0].positive_prompt
    assert "no numerals replaced" in task.runs[0].negative_prompt
    renderer = FakeRenderer(fail_wait_calls={2})
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *args, **kwargs: renderer)
    result = asyncio.run(fixture["service"].run_task(task.id))
    assert result.status == GenerationTaskStatus.FAILED
    image = next(run.images[0] for run in result.runs if run.status == GenerationRunStatus.SUCCEEDED)
    approved = fixture["service"].approve_image(image.id)
    assert approved.reference_subject_id == subject.id and approved.entity_id is None
    assert approved.status == ApprovalStatus.APPROVED
    assert fixture["service"].approve_image(image.id).id == approved.id
    assert result.approved_candidate_index is None


def test_legacy_scene_version_owner_and_catalog_owner_do_not_share_id_namespace(catalog_fixture):
    fixture = catalog_fixture
    task = ScriptGenerationTask(project_id=fixture["project"].id, mode=ScriptGenerationMode.BATCH, total_pages=1)
    scene = ScriptScene(task=task, scene_key="room", name="Room")
    version = SceneVisualVersion(project_id=fixture["project"].id, script_scene=scene, version=1)
    fixture["session"].add_all([task, scene, version])
    fixture["session"].commit()
    subject = fixture["subjects"].create(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE, name="Independent room")
    old = fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE,
        entity_id=version.id, entity_key=None, role=VisualAssetRole.SCENE_MASTER, content=_png_bytes())
    new = fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE,
        entity_id=None, entity_key=None, reference_subject_id=subject.id, role=VisualAssetRole.SCENE_MASTER, content=_png_bytes())
    assert old.entity_id == version.id and old.reference_subject_id is None
    assert new.entity_id is None and new.reference_subject_id == subject.id
    with pytest.raises(AppError):
        fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE,
            entity_id=version.id, entity_key=None, reference_subject_id=subject.id,
            role=VisualAssetRole.SCENE_MASTER, content=_png_bytes())


def _bound_scene_version(fixture, *, project_id=None, subject=None):
    project_id = project_id or fixture["project"].id
    subject = subject or fixture["subjects"].create(project_id=project_id,
        entity_type=VisualEntityType.SCENE, name="Station", description="round clock", negative_constraints="no clock replaced")
    script_task = ScriptGenerationTask(project_id=project_id, mode=ScriptGenerationMode.BATCH, total_pages=1)
    scene = ScriptScene(task=script_task, scene_key="station", name="Station", reference_subject_id=subject.id,
        negative_constraints="no modern screens")
    version = SceneVisualVersion(project_id=project_id, script_scene=scene, version=2,
        landmarks_json='["round clock"]', lighting_state_json='{"time_of_day":"night","lamp":"warm"}')
    fixture["session"].add_all([script_task, scene, version])
    fixture["session"].commit()
    return subject, scene, version


def test_scene_generic_and_version_specific_images_keep_both_owners(catalog_fixture, monkeypatch):
    """同一命名场景的通用图和版本图独立保存，版本提示词与确认不丢失双归属。"""
    fixture = catalog_fixture
    subject, scene, version = _bound_scene_version(fixture)
    generic = fixture["assets"].upload_asset(project_id=fixture["project"].id,
        entity_type=VisualEntityType.SCENE, entity_id=None, entity_key=None, reference_subject_id=subject.id,
        role=VisualAssetRole.SCENE_MASTER, content=_png_bytes(), approve=True)
    dedicated = fixture["assets"].upload_asset(project_id=fixture["project"].id,
        entity_type=VisualEntityType.SCENE, entity_id=version.id, entity_key=None, reference_subject_id=subject.id,
        role=VisualAssetRole.SCENE_MASTER, content=_png_bytes(), approve=True)
    assert generic.entity_id is None and dedicated.entity_id == version.id
    assert generic.reference_subject_id == dedicated.reference_subject_id == subject.id
    assert generic.entity_key == dedicated.entity_key == subject.key
    selection = _selection(fixture, (VisualAssetRole.SCENE_MASTER,), entity_type=VisualEntityType.SCENE,
        entity_id=version.id, reference_subject_id=subject.id)
    preview = fixture["service"].preview_reference_prompts(**selection)
    assert "night" in preview["prompts"]["scene_master"]["positive"]
    assert "no modern screens" in preview["prompts"]["scene_master"]["negative"]
    task = _task(fixture, **selection)
    snapshot = json.loads(task.subject_snapshot_json)
    assert snapshot["scene_version"]["id"] == version.id
    assert snapshot["scene_version"]["script_scene_id"] == scene.id
    response = reference_task_response(task)
    assert response.entity_id == version.id and response.reference_subject_id == subject.id
    renderer = FakeRenderer()
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *args, **kwargs: renderer)
    result = asyncio.run(fixture["service"].run_task(task.id))
    generated = fixture["service"].approve_image(result.runs[0].images[0].id)
    assert generated.entity_id == version.id and generated.reference_subject_id == subject.id
    assert generated.entity_key == subject.key
    assert fixture["service"].approve_image(result.runs[0].images[0].id).id == generated.id
    item = fixture["service"]._reference_item(dedicated, 1)
    assert item["owner"]["id"] == subject.id
    assert item["entity_id"] == version.id and item["reference_subject_id"] == subject.id


def test_scene_dual_owner_rejects_wrong_binding_and_cross_project(catalog_fixture):
    fixture = catalog_fixture
    subject, scene, version = _bound_scene_version(fixture)
    wrong = fixture["subjects"].create(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE, name="Different station")
    other = ComicProject(title="Other")
    fixture["session"].add(other)
    fixture["session"].commit()
    foreign_subject, _, foreign_version = _bound_scene_version(fixture, project_id=other.id)
    pairs = [(wrong.id, version.id), (subject.id, foreign_version.id), (foreign_subject.id, version.id)]
    for subject_id, version_id in pairs:
        selection = _selection(fixture, (VisualAssetRole.SCENE_MASTER,), entity_type=VisualEntityType.SCENE,
            entity_id=version_id, reference_subject_id=subject_id)
        with pytest.raises(AppError) as exc:
            fixture["service"].preview_reference_prompts(**selection)
        assert exc.value.code == "reference.owner_invalid"
        with pytest.raises(AppError) as exc:
            fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=VisualEntityType.SCENE,
                entity_id=version_id, entity_key=None, reference_subject_id=subject_id,
                role=VisualAssetRole.SCENE_MASTER, content=_png_bytes())
        assert exc.value.code == "reference.owner_invalid"
    scene.reference_subject_id = None
    fixture["session"].commit()
    with pytest.raises(AppError) as exc:
        fixture["assets"].register_renderer_asset(project_id=fixture["project"].id,
            entity_type=VisualEntityType.SCENE, entity_id=version.id, entity_key=None,
            reference_subject_id=subject.id, role=VisualAssetRole.SCENE_MASTER, renderer_locator="scene.png")
    assert exc.value.code == "reference.owner_invalid"


def test_props_still_reject_legacy_entity_id_with_named_subject(catalog_fixture):
    fixture = catalog_fixture
    subject = fixture["subjects"].create(project_id=fixture["project"].id, entity_type=VisualEntityType.PROP, name="Compass")
    selection = _selection(fixture, (VisualAssetRole.PROP_REFERENCE,), entity_type=VisualEntityType.PROP,
        entity_id=1, reference_subject_id=subject.id)
    with pytest.raises(AppError) as exc:
        fixture["service"].preview_reference_prompts(**selection)
    assert exc.value.code == "reference.owner_invalid"
    with pytest.raises(AppError) as exc:
        fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=VisualEntityType.PROP,
            entity_id=1, entity_key=None, reference_subject_id=subject.id,
            role=VisualAssetRole.PROP_REFERENCE, content=_png_bytes())
    assert exc.value.code == "reference.owner_invalid"


def test_resume_uses_frozen_face_tool_seed_and_only_missing_run(catalog_fixture, monkeypatch):
    fixture = catalog_fixture
    face = _face(fixture)
    tool = _image_tool(fixture)
    task = _task(fixture, **_selection(fixture, tool_preset_id=tool.id))
    snapshots = {run.id: json.loads(run.applied_spec_json) for run in task.runs}
    seeds = {run.id: run.seed for run in task.runs}
    def pause(wait_call):
        if wait_call == 1:
            fixture["service"].suspend_task(task.id)
    first = FakeRenderer(on_wait=pause)
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *args, **kwargs: first)
    assert asyncio.run(fixture["service"].run_task(task.id)).status == GenerationTaskStatus.SUSPENDED
    _face(fixture)
    tool.model = "changed-model"
    tool.capabilities_json = '{"features":["txt2img"]}'
    tool.provider = ImageGenerationProvider.COMFYUI
    tool.workflow_json = "{}"
    fixture["session"].commit()
    fixture["service"].prepare_continue(task.id)
    second = FakeRenderer()
    recovered_tool = []
    def backend(preset, **kwargs):
        recovered_tool.append(preset)
        return second
    monkeypatch.setattr(runtime_module, "backend_for_preset", backend)
    assert asyncio.run(fixture["service"].run_task(task.id)).status == GenerationTaskStatus.SUCCEEDED
    assert len(second.submissions) == 1
    spec, seed, _ = second.submissions[0]
    missing = task.runs[1]
    assert seed == seeds[missing.id]
    assert spec["reference_inputs"] == snapshots[missing.id]["reference_inputs"]
    assert spec["renderer_config"] == snapshots[missing.id]["renderer_config"]
    assert spec["reference_inputs"]["items"][0]["asset_id"] == face.id
    assert recovered_tool[0].model == "fake-image-model"
    assert recovered_tool[0].provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE
    assert spec["render"]["seed"] == seed


def test_selected_outfit_and_promotion_validate_same_character_owner(catalog_fixture):
    fixture = catalog_fixture
    outfit = OutfitVariant(project_id=fixture["project"].id, outline_character_id=fixture["character"].id,
        key="coat", version=1, name="Red coat", garment_components_json='["red coat"]', status=ApprovalStatus.APPROVED)
    fixture["session"].add(outfit)
    fixture["session"].commit()
    selection = _selection(fixture, outfit_variant_id=outfit.id)
    assert "red coat" in fixture["service"].preview_reference_prompts(**selection)["prompts"]["identity_side"]["positive"]
    selection["entity_id"] = fixture["unused_character"].id
    with pytest.raises(AppError) as exc:
        fixture["service"].preview_reference_prompts(**selection)
    assert exc.value.code == "reference.outfit_invalid"
    page = ComicPage(project_id=fixture["project"].id, page_no=1)
    source = fixture["tmp_path"] / "comic.png"
    source.write_bytes(_png_bytes())
    image = ComicImage(page=page, local_path=str(source))
    fixture["session"].add(image)
    fixture["session"].commit()
    subject = fixture["subjects"].create(project_id=fixture["project"].id, entity_type=VisualEntityType.PROP, name="Compass")
    asset = fixture["assets"].promote_image(image_id=image.id, entity_type=VisualEntityType.PROP,
        entity_id=None, entity_key=None, reference_subject_id=subject.id, role=VisualAssetRole.PROP_REFERENCE, approve=True)
    assert asset.reference_subject_id == subject.id and asset.source_image_id == image.id


def test_api_catalog_history_and_old_route_share_task_ids(catalog_fixture, monkeypatch):
    fixture = catalog_fixture
    session_factory = sessionmaker(bind=fixture["session"].bind, future=True)
    monkeypatch.setattr(reference_api, "SessionLocal", session_factory)
    queued = []
    monkeypatch.setattr(reference_api.character_reference_runtime, "submit", queued.append)
    app = FastAPI()
    app.include_router(reference_api.router)
    client = TestClient(app)
    catalog = client.get("/api/reference-images/catalog").json()
    assert [item["entity_type"] for item in catalog["categories"]] == ["character", "scene", "prop"]
    assert catalog["categories"][0]["roles"][0]["label_key"] == "visualBible.roleLabels.identity_face"
    payload = {key: value for key, value in _selection(fixture).items() if key != "project_id"}
    preview = client.post(f"/api/reference-images/projects/{fixture['project'].id}/prompt-preview", json=payload)
    assert preview.status_code == 200
    response = client.post(f"/api/reference-images/projects/{fixture['project'].id}/tasks",
        json={**payload, "prompts": preview.json()["prompts"], "candidate_count": 1})
    assert response.status_code == 202
    task = response.json()
    assert queued == [task["id"]]
    fetched = client.get(f"/api/reference-images/tasks/{task['id']}")
    assert fetched.status_code == 200 and fetched.json()["selected_roles"] == ["identity_side"]
    history = client.get(f"/api/reference-images/projects/{fixture['project'].id}/tasks").json()["items"]
    assert [item["id"] for item in history] == [task["id"]]
