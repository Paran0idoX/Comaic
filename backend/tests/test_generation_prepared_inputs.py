"""漫画出图仅消费已准备的提示词，不触发镜头规划或语言转换。"""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from backend.api.schemas.image_generation import GenerateImagesRequest
from backend.i18n.errors import AppError, app_error_from_exception
from backend.models.comic import GenerationRun, GenerationTask, ImageSpec, ImagePromptPreset
from backend.models.enums import GenerationMode
from backend.tests.test_reference_batch_snapshot import BatchShotPlanner, _setup_batch
from backend.api.image_generation import page_to_response
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.utils.json_utils import canonical_hash, canonical_json


async def deny_planning(*_args, **_kwargs):
    raise AssertionError("Image generation must not prepare prompts")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [True, False])
@pytest.mark.parametrize("single_page", [True, False])
async def test_missing_or_stale_prompts_fail_before_upload_without_model_calls(tmp_path, monkeypatch, missing, single_page):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    if missing:
        session.execute(delete(ImageSpec).where(ImageSpec.page_id == pages[1].id))
    else:
        pages[1].summary += " Changed input."
    session.commit()
    before = session.scalars(select(ImageSpec.id)).all()
    monkeypatch.setattr(BatchShotPlanner, "plan", deny_planning)
    stream = service.stream_generate_for_page(page_id=pages[1].id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL) if single_page else service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL)
    events = []
    with pytest.raises(ValueError) as exc:
        async for item in stream:
            events.append(item)
    assert app_error_from_exception(exc.value).code == ("image_spec.not_found" if missing else "image_spec.stale")
    assert not events
    assert client.queued == client.uploads == []
    assert session.scalars(select(ImageSpec.id)).all() == before
    assert not session.scalars(select(GenerationRun)).all()
    assert not session.scalars(select(GenerationTask)).all()
    session.close()


@pytest.mark.asyncio
async def test_prepared_subset_generates_without_modifying_any_prompt(tmp_path, monkeypatch):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    before = {spec.id: spec.spec_json for spec in session.scalars(select(ImageSpec))}
    monkeypatch.setattr(BatchShotPlanner, "plan", deny_planning)
    events = [item async for item in service.stream_generate_for_script_task(
        task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL,
        page_ids=[pages[1].id],
    )]
    assert not any(event.startswith("preparation_") for event, _ in events)
    assert len(client.queued) == 1
    assert all(spec.generation_mode == GenerationMode.PREVIEW for spec in session.scalars(select(ImageSpec)))
    assert session.scalar(select(GenerationTask)).generation_mode == GenerationMode.PREVIEW
    assert {spec.id: spec.spec_json for spec in session.scalars(select(ImageSpec))} == before
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["script", "negative_preset"])
async def test_page_response_marks_existing_outdated_prompts_without_preparing(tmp_path, monkeypatch, change):
    session, task, pages, _, client, service = await _setup_batch(tmp_path, monkeypatch)
    spec_service = ImageSpecService(ImageSpecRepository(session))
    hashes = spec_service.current_page_context_hashes(task.id)
    response = page_to_response(pages[1], service.repository, current_context_hash=hashes[pages[1].id])
    assert response.latest_spec_id is not None
    assert not response.spec_stale
    spec = session.get(ImageSpec, response.latest_spec_id)
    before = spec.spec_json
    if change == "script":
        pages[1].summary += " Changed script."
    else:
        session.get(ImagePromptPreset, spec.negative_prompt_preset_id).tag_content += ", extra exclusion"
    session.commit()
    monkeypatch.setattr(BatchShotPlanner, "plan", deny_planning)
    hashes = spec_service.current_page_context_hashes(task.id)
    response = page_to_response(pages[1], service.repository, current_context_hash=hashes[pages[1].id])
    assert response.spec_stale
    assert spec.spec_json == before
    assert client.queued == client.uploads == []
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("version,change", [
    ("page-context-v2", None),
    ("page-context-v2", "script"),
    ("page-context-v2", "negative_preset"),
    ("page-context-v2", "snapshot_tampering"),
    ("page-context-v1", None),
])
async def test_context_marker_compatibility_preserves_prompts_and_real_stale_checks(
    tmp_path, monkeypatch, version, change,
):
    """仅标记升级可直接出图；输入变化、快照损坏和旧事件版本仍零提交。"""
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    spec_service = ImageSpecService(ImageSpecRepository(session))
    specs = session.scalars(select(ImageSpec).where(ImageSpec.page_id == pages[1].id)).all()
    snapshot = specs[0].snapshot
    state = json.loads(snapshot.state_json)
    state["context_builder_version"] = version
    snapshot.state_json, snapshot.state_hash = canonical_json(state), canonical_hash(state)
    for spec in specs:
        spec.source_hash = spec_service.current_image_spec_source_hash(spec)
    if change == "script":
        pages[1].summary += " Changed page input."
    elif change == "negative_preset":
        session.get(ImagePromptPreset, specs[0].negative_prompt_preset_id).tag_content += ", new constraint"
    elif change == "snapshot_tampering":
        state["page_no"] = 999
        snapshot.state_json = canonical_json(state)
    session.commit()
    before = {spec.id: (spec.spec_json, spec.source_hash, spec.positive_prompt) for spec in specs}
    before_snapshot = (snapshot.state_json, snapshot.state_hash)
    monkeypatch.setattr(BatchShotPlanner, "plan", deny_planning)
    hashes = spec_service.current_page_context_hashes(task.id)
    response = page_to_response(pages[1], service.repository, current_context_hash=hashes[pages[1].id])
    compatible = version == "page-context-v2" and change is None
    assert response.spec_stale is not compatible
    stream = service.stream_generate_for_page(page_id=pages[1].id, tool_preset_id=preset.id)
    if compatible:
        events = [item async for item in stream]
        assert events[-1][0] == "done"
        assert len(client.queued) == 1
    else:
        with pytest.raises(ValueError) as exc:
            _events = [item async for item in stream]
        assert app_error_from_exception(exc.value).code == "image_spec.stale"
        assert client.queued == client.uploads == []
    assert {spec.id: (spec.spec_json, spec.source_hash, spec.positive_prompt) for spec in specs} == before
    assert (snapshot.state_json, snapshot.state_hash) == before_snapshot
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page_ids", [[], [999999]])
async def test_invalid_page_scope_rejected(tmp_path, monkeypatch, page_ids):
    session, task, _, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    with pytest.raises(AppError) as exc:
        _events = [item async for item in service.stream_generate_for_script_task(
            task_id=task.id, tool_preset_id=preset.id, page_ids=page_ids,
        )]
    assert exc.value.code == "image_generation.page_scope_invalid"
    assert client.queued == client.uploads == []
    session.close()


@pytest.mark.parametrize("page_ids", [[], [0], [-1]])
def test_request_rejects_invalid_page_ids(page_ids):
    with pytest.raises(ValidationError):
        GenerateImagesRequest(tool_preset_id=1, page_ids=page_ids)


def test_comic_size_request_defaults_and_validation():
    request = GenerateImagesRequest(tool_preset_id=1)
    assert (request.width, request.height) == (1024, 1536)
    assert GenerateImagesRequest(tool_preset_id=1, width=768, height=1024).width == 768
    for invalid in [0, 255, 1025, 2080, True, "1024"]:
        with pytest.raises(ValidationError):
            GenerateImagesRequest(tool_preset_id=1, width=invalid)
        with pytest.raises(ValidationError):
            GenerateImagesRequest(tool_preset_id=1, height=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("single_page", [False, True])
async def test_requested_comic_size_is_applied_and_frozen(tmp_path, monkeypatch, single_page):
    """单页和批量都应用本次宽高，不能改写已准备的模型无关规格。"""
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    before = {spec.id: spec.spec_json for spec in session.scalars(select(ImageSpec))}
    workflow, bindings = json.loads(preset.workflow_json), json.loads(preset.bindings_json)
    workflow["7"] = {"inputs": {"width": 1024, "height": 1536}}
    bindings["bindings"].extend([
        {"source": "render.width", "node_id": "7", "input_name": "width"},
        {"source": "render.height", "node_id": "7", "input_name": "height"},
    ])
    preset.workflow_json, preset.bindings_json = json.dumps(workflow), json.dumps(bindings)
    session.commit()
    kwargs = dict(tool_preset_id=preset.id, width=768, height=1024)
    stream = service.stream_generate_for_page(page_id=pages[1].id, **kwargs) if single_page else service.stream_generate_for_script_task(task_id=task.id, page_ids=[pages[1].id], **kwargs)
    events = [item async for item in stream]
    assert events[-1][0] == "done"
    assert client.queued[0]["7"]["inputs"] == {"width": 768, "height": 1024}
    batch = session.scalar(select(GenerationTask).where(GenerationTask.input_snapshot_json.is_not(None)))
    frozen = json.loads(batch.input_snapshot_json)["pages"][str(pages[1].id)]["spec"]
    assert frozen["render"] == {"width": 768, "height": 1024}
    assert {spec.id: spec.spec_json for spec in session.scalars(select(ImageSpec))} == before
    session.close()
