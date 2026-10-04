"""确认互斥与候选重选的离线回归：使用临时数据库、图片和模拟 Provider。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.services.character_reference_service as runtime_module
from backend.api.reference_images import reference_task_response
from backend.models.comic import ComicProject, OutfitVariant, VisualAsset
from backend.models.database import Base
from backend.models.enums import ApprovalStatus, ReferenceSourceMode, VisualAssetRole, VisualAssetSource, VisualAssetStorageKind, VisualEntityType
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.reference_selection_service import ReferenceSelectionService
from backend.tests.test_character_reference_service import reference_fixture, FakeRenderer, _png_bytes
from backend.tests.test_reference_image_service import catalog_fixture, _bound_scene_version, _selection, _task


def upload(fixture, role, *, category=VisualEntityType.CHARACTER, entity_id=None, subject_id=None, outfit_id=None, approve=False):
    """所有来源共用现有素材入口，默认创建人物原图。"""
    return fixture["assets"].upload_asset(project_id=fixture["project"].id, entity_type=category,
        entity_id=fixture["character"].id if category == VisualEntityType.CHARACTER else entity_id,
        entity_key=None, reference_subject_id=subject_id, outfit_variant_id=outfit_id,
        role=role, content=_png_bytes(), approve=approve)


@pytest.mark.parametrize("role", [VisualAssetRole.IDENTITY_FACE, VisualAssetRole.IDENTITY_FULL_BODY,
    VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK])
def test_character_each_view_replaces_only_its_own_confirmed_image(catalog_fixture, role):
    fixture = catalog_fixture
    images = [upload(fixture, view, approve=True) for view in (
        VisualAssetRole.IDENTITY_FACE, VisualAssetRole.IDENTITY_FULL_BODY, VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK)]
    old = next(image for image in images if image.role == role)
    candidate = upload(fixture, role)
    assert old.status == ApprovalStatus.APPROVED
    fixture["assets"].set_asset_status(asset_id=candidate.id, status=ApprovalStatus.APPROVED)
    assert candidate.status == ApprovalStatus.APPROVED
    assert old.status == ApprovalStatus.DRAFT and old.approved_at is None
    assert all(image.status == ApprovalStatus.APPROVED for image in images if image is not old)
    fixture["assets"].set_asset_status(asset_id=old.id, status=ApprovalStatus.APPROVED)
    assert candidate.status == ApprovalStatus.DRAFT and old.status == ApprovalStatus.APPROVED
    assert old.local_path and old.version < candidate.version


@pytest.mark.parametrize("role", [VisualAssetRole.IDENTITY_FULL_BODY, VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK])
def test_body_views_keep_general_and_different_outfits_independent(catalog_fixture, role):
    fixture = catalog_fixture
    outfits = [OutfitVariant(project_id=fixture["project"].id, outline_character_id=fixture["character"].id,
        key=f"look-{i}", name=f"Look {i}", version=1) for i in range(2)]
    fixture["session"].add_all(outfits); fixture["session"].commit()
    general = upload(fixture, role, approve=True)
    first = upload(fixture, role, outfit_id=outfits[0].id, approve=True)
    second = upload(fixture, role, outfit_id=outfits[1].id, approve=True)
    replacement = upload(fixture, role, outfit_id=outfits[0].id, approve=True)
    assert first.status == ApprovalStatus.DRAFT
    assert all(image.status == ApprovalStatus.APPROVED for image in (general, second, replacement))
    faces = [upload(fixture, VisualAssetRole.IDENTITY_FACE, outfit_id=outfit.id, approve=True) for outfit in outfits]
    assert faces[0].status == ApprovalStatus.DRAFT and faces[1].status == ApprovalStatus.APPROVED


@pytest.mark.parametrize("category,role", [(VisualEntityType.SCENE, VisualAssetRole.SCENE_MASTER),
    (VisualEntityType.PROP, VisualAssetRole.PROP_REFERENCE)])
def test_named_subject_replacement_is_project_and_owner_scoped(catalog_fixture, category, role):
    fixture = catalog_fixture
    subjects = [fixture["subjects"].create(project_id=fixture["project"].id, entity_type=category, name=f"Owner {i}") for i in range(2)]
    old = upload(fixture, role, category=category, subject_id=subjects[0].id, approve=True)
    other = upload(fixture, role, category=category, subject_id=subjects[1].id, approve=True)
    replacement = upload(fixture, role, category=category, subject_id=subjects[0].id)
    foreign_project = ComicProject(title="Foreign"); fixture["session"].add(foreign_project); fixture["session"].commit()
    foreign_subject = fixture["subjects"].create(project_id=foreign_project.id, entity_type=category, name="Foreign owner")
    foreign = fixture["assets"].upload_asset(project_id=foreign_project.id, entity_type=category, entity_id=None,
        entity_key=None, reference_subject_id=foreign_subject.id, role=role, content=_png_bytes(), approve=True)
    fixture["assets"].set_asset_status(asset_id=replacement.id, status=ApprovalStatus.APPROVED)
    assert old.status == ApprovalStatus.DRAFT
    assert all(image.status == ApprovalStatus.APPROVED for image in (other, foreign, replacement))


def test_scene_generic_versions_and_legacy_version_images_are_separate(catalog_fixture):
    fixture = catalog_fixture
    subject, scene, version = _bound_scene_version(fixture)
    _, _, other_version = _bound_scene_version(fixture, subject=subject)
    options = dict(category=VisualEntityType.SCENE, subject_id=subject.id)
    general = upload(fixture, VisualAssetRole.SCENE_MASTER, **options, approve=True)
    legacy = upload(fixture, VisualAssetRole.SCENE_MASTER, category=VisualEntityType.SCENE, entity_id=version.id, approve=True)
    dedicated = upload(fixture, VisualAssetRole.SCENE_MASTER, **options, entity_id=version.id, approve=True)
    independent = upload(fixture, VisualAssetRole.SCENE_MASTER, **options, entity_id=other_version.id, approve=True)
    assert legacy.status == ApprovalStatus.DRAFT
    replacement = upload(fixture, VisualAssetRole.SCENE_MASTER, **options, entity_id=version.id, approve=True)
    assert dedicated.status == ApprovalStatus.DRAFT
    assert all(image.status == ApprovalStatus.APPROVED for image in (general, independent, replacement))


@pytest.mark.parametrize("category,role", [(VisualEntityType.CHARACTER, VisualAssetRole.IDENTITY_FACE),
    (VisualEntityType.SCENE, VisualAssetRole.SCENE_MASTER), (VisualEntityType.PROP, VisualAssetRole.PROP_REFERENCE)])
def test_generated_candidates_can_be_reselected_without_duplicate_assets(catalog_fixture, monkeypatch, category, role):
    fixture = catalog_fixture
    subject = None if category == VisualEntityType.CHARACTER else fixture["subjects"].create(
        project_id=fixture["project"].id, entity_type=category, name="Generated owner")
    task = _task(fixture, **_selection(fixture, (role,), entity_type=category,
        entity_id=fixture["character"].id if subject is None else None,
        reference_subject_id=subject.id if subject else None, source_mode=ReferenceSourceMode.NONE))
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *args, **kwargs: FakeRenderer())
    task = asyncio.run(fixture["service"].run_task(task.id))
    first, second = [run.images[0] for run in task.runs]
    original = fixture["service"].approve_image(first.id)
    replacement = fixture["service"].approve_image(second.id)
    assert original.status == ApprovalStatus.DRAFT and replacement.status == ApprovalStatus.APPROVED
    responses = reference_task_response(task).candidates
    assert responses[0].roles[role.value].images[0].promoted_asset_status == ApprovalStatus.DRAFT
    assert task.runs[0].review_status == ApprovalStatus.DRAFT
    assert fixture["service"].approve_image(first.id).id == original.id
    assert replacement.status == ApprovalStatus.DRAFT and original.status == ApprovalStatus.APPROVED
    approved_at = original.approved_at
    assert fixture["service"].approve_image(first.id).approved_at == approved_at
    assert len(fixture["assets"].list_assets(project_id=fixture["project"].id)) == 2
    # 手动选回较老版本后，编译必须消费人工选中的旧图，不能再按版本号覆盖选择。
    if subject:
        snapshot = {"scene": {"scene_key": subject.key, "reference_subject_id": subject.id, "catalog_assets": []},
            "prop_catalog": [{"key": subject.key, "id": subject.id, "assets": []}]}
        selected = {"id": original.id, "role": role.value, "version": original.version,
            "reference_subject_id": subject.id, "entity_id": None}
        snapshot["scene"]["catalog_assets"] = [selected] if category == VisualEntityType.SCENE else []
        snapshot["prop_catalog"][0]["assets"] = [selected]
        plan = ReferenceSelectionService.select(snapshot=snapshot, shot_plan={"scene": {"background_visible": True, "visible_prop_keys": [subject.key]}})
        assert original.id in [item["asset_id"] for item in plan["items"]]


def test_failed_confirmation_rolls_back_old_and_new_states(catalog_fixture, monkeypatch):
    fixture = catalog_fixture
    old = upload(fixture, VisualAssetRole.IDENTITY_FACE, approve=True)
    task = _task(fixture, **_selection(fixture, (VisualAssetRole.IDENTITY_FACE,), source_mode=ReferenceSourceMode.NONE))
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *args, **kwargs: FakeRenderer())
    task = asyncio.run(fixture["service"].run_task(task.id))
    image = task.runs[0].images[0]
    monkeypatch.setattr(fixture["session"], "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        fixture["service"].approve_image(image.id)
    assert old.status == ApprovalStatus.APPROVED and image.promoted_asset_id is None
    assert len(fixture["assets"].list_assets(project_id=fixture["project"].id)) == 1


def test_concurrent_confirmation_keeps_exactly_one_approved_slot(tmp_path):
    """SQLite 写事务串行替换同槽图，两个同时成功的请求也不能留下多张确认图。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'approval.sqlite3'}", connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as session:
        project = ComicProject(title="Concurrent approval"); session.add(project); session.flush()
        assets = [VisualAsset(project_id=project.id, entity_type=VisualEntityType.PROP, entity_id=None,
            entity_key="clock", role=VisualAssetRole.PROP_REFERENCE, version=i + 1, status=ApprovalStatus.DRAFT,
            source=VisualAssetSource.UPLOAD, storage_kind=VisualAssetStorageKind.LOCAL_FILE) for i in range(2)]
        session.add_all(assets); session.commit(); ids = [asset.id for asset in assets]
    barrier = Barrier(2)
    def approve(asset_id):
        with sessions() as session:
            repo = VisualBibleRepository(session); asset = repo.get_asset(asset_id); barrier.wait(timeout=10)
            repo.set_asset_approval_status(asset, ApprovalStatus.APPROVED)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(approve, ids))
        with sessions() as session:
            assert len(list(session.scalars(select(VisualAsset).where(VisualAsset.status == ApprovalStatus.APPROVED)))) == 1
    finally:
        engine.dispose()
