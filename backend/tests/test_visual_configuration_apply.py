"""编辑设定的一次保存只替换指定绑定，并保持版本和事务边界。"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.i18n.errors import AppError
from backend.models.comic import OutfitVariant, SceneVisualVersion, ScriptCharacter, ScriptScene, ScriptSection
from backend.models.enums import ApprovalStatus
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.script_service import ScriptService
from backend.services.visual_bible_service import VisualBibleService
from backend.tests.test_visual_bible_service import _session, _seed_script_context, _scene_payload, _character_payload


@pytest.fixture
def context():
    session = _session()
    project, outline, _, task, section = _seed_script_context(session)
    ScriptService(ComicRepository(session))._save_section_visual_settings(
        task_id=task.id, section_id=section.id, outline_version_id=outline.id,
        scenes=[_scene_payload()], characters=[_character_payload()],
    )
    service = VisualBibleService(VisualBibleRepository(session))
    for kind, model in (("outfit", OutfitVariant), ("scene", SceneVisualVersion)):
        item = session.scalar(select(model))
        service.set_configuration_status(kind=kind, item_id=item.id, status=ApprovalStatus.APPROVED)
    yield session, project, task, service
    session.close()


def create(context, kind, *, apply=True, **target_overrides):
    session, project, task, service = context
    if kind == "outfit":
        character = session.scalar(select(ScriptCharacter).order_by(ScriptCharacter.id))
        old = session.get(OutfitVariant, character.outfit_variant_id)
        target = dict(script_character_id=character.id, script_task_id=task.id, expected_outfit_variant_id=old.id)
        target.update(target_overrides)
        return service.create_outfit(
            project_id=project.id, outline_character_id=old.outline_character_id,
            key=old.key, name="修改后的造型", garment_components=["红色外套"],
            apply_to=target if apply else None,
        )
    scene = session.scalar(select(ScriptScene).order_by(ScriptScene.id))
    target = dict(script_task_id=task.id, expected_visual_version_id=scene.selected_visual_version_id)
    target.update(target_overrides)
    return service.create_scene_version(
        project_id=project.id, script_scene_id=scene.id, landmarks=["打开的门"],
        apply_to=target if apply else None,
    )


@pytest.mark.parametrize("kind,model,binding_model,field", [
    ("outfit", OutfitVariant, ScriptCharacter, "outfit_variant_id"),
    ("scene", SceneVisualVersion, ScriptScene, "selected_visual_version_id"),
])
def test_save_apply_preserves_old_version_and_other_bindings(context, kind, model, binding_model, field):
    session, _, task, _ = context
    target = session.scalar(select(binding_model))
    old = session.get(model, getattr(target, field))
    old_timestamp = old.approved_at
    if kind == "outfit":
        section = ScriptSection(task=task, section_no=2, page_start=3, page_end=4)
        other = ScriptCharacter(section=section, outline_character_id=target.outline_character_id,
                                character_key="lin", name="林", outfit_variant_id=old.id)
    else:
        other = ScriptScene(task=task, scene_key="other", name="另一场景")
    session.add(other)
    session.commit()
    other_binding = getattr(other, field)
    new = create(context, kind)
    assert new.status == ApprovalStatus.APPROVED and new.approved_at is not None
    assert new.id != old.id and new.version == old.version + 1
    assert getattr(target, field) == new.id
    assert getattr(other, field) == other_binding
    assert old.status == ApprovalStatus.APPROVED and old.approved_at == old_timestamp


@pytest.mark.parametrize("kind,model,binding_model,field", [
    ("outfit", OutfitVariant, ScriptCharacter, "outfit_variant_id"),
    ("scene", SceneVisualVersion, ScriptScene, "selected_visual_version_id"),
])
def test_draft_still_leaves_current_binding_unchanged(context, kind, model, binding_model, field):
    session, _, _, _ = context
    binding = session.scalar(select(binding_model))
    old_id = getattr(binding, field)
    new = create(context, kind, apply=False)
    assert new.status == ApprovalStatus.DRAFT and new.approved_at is None
    assert getattr(binding, field) == old_id


@pytest.mark.parametrize("kind,model,expected_field", [
    ("outfit", OutfitVariant, "expected_outfit_variant_id"),
    ("scene", SceneVisualVersion, "expected_visual_version_id"),
])
def test_changed_binding_rolls_back_created_and_approved_version(context, kind, model, expected_field):
    session, _, _, _ = context
    count = session.query(model).count()
    with pytest.raises(AppError) as error:
        create(context, kind, **{expected_field: None})
    assert error.value.code == "visual.configuration_binding_changed"
    assert error.value.status_code == 409
    assert session.query(model).count() == count


@pytest.mark.parametrize("kind,model", [("outfit", OutfitVariant), ("scene", SceneVisualVersion)])
def test_wrong_task_rejected_before_creating_a_version(context, kind, model):
    session, _, _, _ = context
    count = session.query(model).count()
    with pytest.raises(AppError) as error:
        create(context, kind, script_task_id=999)
    assert error.value.code == "visual.configuration_apply_target_invalid"
    assert session.query(model).count() == count


def test_outfit_cannot_apply_to_another_identity(context):
    session, project, task, service = context
    from backend.models.comic import OutlineCharacter
    old = session.scalar(select(OutfitVariant))
    character = session.scalar(select(ScriptCharacter))
    another = OutlineCharacter(outline_version_id=task.outline_version_id, character_key="other", name="其他人物")
    session.add(another)
    session.commit()
    with pytest.raises(AppError) as error:
        service.create_outfit(project_id=project.id, outline_character_id=another.id, key="other", name="误选",
                              apply_to=dict(script_character_id=character.id, script_task_id=task.id,
                                            expected_outfit_variant_id=old.id))
    assert error.value.code == "visual.configuration_apply_target_invalid"
    assert session.query(OutfitVariant).count() == 1
    assert character.outfit_variant_id == old.id


@pytest.mark.parametrize("kind,model,binding_model,field", [
    ("outfit", OutfitVariant, ScriptCharacter, "outfit_variant_id"),
    ("scene", SceneVisualVersion, ScriptScene, "selected_visual_version_id"),
])
def test_commit_failure_rolls_back_new_version_and_binding(context, monkeypatch, kind, model, binding_model, field):
    session, _, _, _ = context
    binding = session.scalar(select(binding_model))
    old_id = getattr(binding, field)
    def fail_commit():
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        create(context, kind)
    assert session.query(model).count() == 1
    assert getattr(binding, field) == old_id


def test_create_api_exposes_atomic_apply_and_requires_original_binding(context, monkeypatch):
    from backend.api import visual_bible
    session, project, task, _ = context
    @contextmanager
    def session_scope():
        yield session
    monkeypatch.setattr(visual_bible, "SessionLocal", session_scope)
    app = FastAPI()
    app.include_router(visual_bible.router)
    character = session.scalar(select(ScriptCharacter))
    payload = dict(outline_character_id=character.outline_character_id, key="manual", name="应用",
                   apply_to=dict(script_character_id=character.id, script_task_id=task.id))
    with TestClient(app) as client:
        url = f"/api/visual-bible/projects/{project.id}/outfits"
        assert client.post(url, json=payload).status_code == 422
        payload["apply_to"]["expected_outfit_variant_id"] = character.outfit_variant_id
        result = client.post(url, json=payload)
        assert result.status_code == 201 and result.json()["status"] == "approved"
        assert "apply_to" not in result.json()
        assert character.outfit_variant_id == result.json()["id"]
        conflict = client.post(url, json=payload)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "visual.configuration_binding_changed"
