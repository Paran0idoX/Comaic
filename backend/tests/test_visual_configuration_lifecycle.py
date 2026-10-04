"""验证设定删除/归档的绑定、原图、派生去重和 API 边界。"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.i18n.errors import AppError
from backend.models.comic import OutfitVariant, SceneVisualVersion, ScriptCharacter, ScriptScene
from backend.models.enums import ApprovalStatus, VisualEntityType
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.script_service import ScriptService
from backend.services.visual_bible_service import VisualBibleService
from backend.tests.test_visual_bible_service import (
    _session, _seed_script_context, _scene_payload, _character_payload,
)


@pytest.fixture
def context():
    session = _session()
    project, outline, _, task, section = _seed_script_context(session)
    ScriptService(ComicRepository(session))._save_section_visual_settings(
        task_id=task.id, section_id=section.id, outline_version_id=outline.id,
        scenes=[_scene_payload()], characters=[_character_payload()],
    )
    service = VisualBibleService(VisualBibleRepository(session))
    yield session, project, task, section, service
    session.close()


@pytest.mark.parametrize("kind,model,binding_model,field", [
    (VisualEntityType.OUTFIT, OutfitVariant, ScriptCharacter, "outfit_variant_id"),
    (VisualEntityType.SCENE, SceneVisualVersion, ScriptScene, "selected_visual_version_id"),
])
def test_delete_unbinds_keeps_originals_and_only_changed_content_reappears(
    context, tmp_path, kind, model, binding_model, field,
):
    session, project, task, section, service = context
    entity = session.scalar(select(model))
    binding = session.scalar(select(binding_model))
    # 通过现有上传入口建立真实原图，删除设定不能移除它或抹掉造型归属。
    from io import BytesIO
    from PIL import Image
    from backend.models.enums import VisualAssetRole
    content = BytesIO()
    Image.new("RGB", (8, 8)).save(content, format="PNG")
    service.asset_root = tmp_path
    asset = service.upload_asset(
        project_id=project.id, entity_type=kind, entity_id=entity.id, entity_key=None,
        role=VisualAssetRole.OUTFIT_FRONT if kind == VisualEntityType.OUTFIT else VisualAssetRole.SCENE_MASTER,
        content=content.getvalue(), approve=True,
    )
    from pathlib import Path
    original = Path(asset.local_path)
    assert service.configuration_usage(kind=kind, item_id=entity.id)["binding_count"] == 1
    service.delete_configuration_draft(kind=kind, item_id=entity.id)
    session.expire_all()
    assert getattr(binding, field) is None
    assert entity.status == ApprovalStatus.DELETED
    assert original.read_bytes() == content.getvalue()
    assert asset.entity_id == entity.id
    assert not (service.list_outfits(project_id=project.id) if kind == VisualEntityType.OUTFIT
                else service.list_scene_versions(project_id=project.id))
    service.derive_script_visual_drafts(
        project_id=project.id, scenes=list(session.scalars(select(ScriptScene))),
        characters=list(session.scalars(select(ScriptCharacter))),
    )
    assert session.query(model).count() == 1
    assert getattr(binding, field) is None
    with pytest.raises(AppError) as error:
        service.set_configuration_status(kind=kind.value, item_id=entity.id, status=ApprovalStatus.APPROVED)
    assert error.value.code == "visual.configuration_deleted"
    # 新内容仍可派生，不能将用户舍弃意图扩大为永久禁用该角色/场景。
    if kind == VisualEntityType.OUTFIT:
        binding.current_clothing = "红色衬衫"
    else:
        binding.environment_details = "新建玻璃站台"
    session.commit()
    service.derive_script_visual_drafts(
        project_id=project.id, scenes=list(session.scalars(select(ScriptScene))),
        characters=list(session.scalars(select(ScriptCharacter))),
    )
    assert session.query(model).count() == 2
    assert getattr(binding, field) != entity.id
    assert getattr(binding, field) is not None


@pytest.mark.parametrize("kind,model,binding_model,field", [
    (VisualEntityType.OUTFIT, OutfitVariant, ScriptCharacter, "outfit_variant_id"),
    (VisualEntityType.SCENE, SceneVisualVersion, ScriptScene, "selected_visual_version_id"),
])
def test_approved_versions_archive_and_cannot_be_deleted(context, kind, model, binding_model, field):
    session, project, _, _, service = context
    entity = session.scalar(select(model))
    service.set_configuration_status(kind=kind.value, item_id=entity.id, status=ApprovalStatus.APPROVED)
    approved_at = entity.approved_at
    with pytest.raises(AppError) as error:
        service.delete_configuration_draft(kind=kind, item_id=entity.id)
    assert error.value.status_code == 409
    service.set_configuration_status(kind=kind.value, item_id=entity.id, status=ApprovalStatus.ARCHIVED)
    assert entity.approved_at == approved_at
    assert getattr(session.scalar(select(binding_model)), field) is None
    service.derive_script_visual_drafts(
        project_id=project.id, scenes=list(session.scalars(select(ScriptScene))),
        characters=list(session.scalars(select(ScriptCharacter))),
    )
    assert session.query(model).count() == 1
    assert getattr(session.scalar(select(binding_model)), field) is None


def test_delete_api_is_idempotent_and_rejects_status_resurrection(context, monkeypatch):
    from backend.api import visual_bible
    session, project, _, _, _ = context
    @contextmanager
    def session_scope():
        yield session
    monkeypatch.setattr(visual_bible, "SessionLocal", session_scope)
    app = FastAPI()
    app.include_router(visual_bible.router)
    with TestClient(app) as client:
        item = session.scalar(select(OutfitVariant))
        url = f"/api/visual-bible/configurations/outfit/{item.id}"
        assert client.get(url + "/usage").json()["binding_count"] == 1
        assert client.delete(url).status_code == 200
        assert client.delete(url).status_code == 200
        assert client.get(f"/api/visual-bible/projects/{project.id}/outfits").json() == []
        error = client.post(url + "/status", json={"status": "approved"}, headers={"X-Locale": "en"})
        assert error.status_code == 409
        assert error.json()["detail"]["code"] == "visual.configuration_deleted"
        assert client.post(url + "/status", json={"status": "deleted"}).status_code == 422
        assert client.delete("/api/visual-bible/configurations/style/1").status_code == 422
        assert client.delete("/api/visual-bible/configurations/scene/999").status_code == 404


def test_deleting_shared_outfit_clears_bindings_in_other_tasks(context):
    from backend.models.comic import ScriptGenerationTask, ScriptSection
    from backend.models.enums import ScriptGenerationMode
    session, project, task, _, service = context
    outfit = session.scalar(select(OutfitVariant))
    second_task = ScriptGenerationTask(
        project_id=project.id, outline_version_id=task.outline_version_id,
        total_pages=2, mode=ScriptGenerationMode.BATCH,
    )
    second_section = ScriptSection(task=second_task, section_no=1, page_start=1, page_end=2)
    second_character = ScriptCharacter(
        section=second_section, outline_character_id=outfit.outline_character_id,
        character_key="lin", name="林", outfit_variant_id=outfit.id,
    )
    session.add(second_character)
    session.commit()
    usage = service.configuration_usage(kind=VisualEntityType.OUTFIT, item_id=outfit.id)
    assert usage["binding_count"] == 2
    service.delete_configuration_draft(kind=VisualEntityType.OUTFIT, item_id=outfit.id)
    assert all(item.outfit_variant_id is None for item in session.scalars(select(ScriptCharacter)))


def test_unbound_draft_can_be_deleted(context):
    session, project, _, _, service = context
    outfit = session.scalar(select(OutfitVariant))
    character = session.scalar(select(ScriptCharacter))
    service.assign_outfit(script_character_id=character.id, outfit_variant_id=None)
    assert service.configuration_usage(kind=VisualEntityType.OUTFIT, item_id=outfit.id)["binding_count"] == 0
    service.delete_configuration_draft(kind=VisualEntityType.OUTFIT, item_id=outfit.id)
    assert service.list_outfits(project_id=project.id) == []
