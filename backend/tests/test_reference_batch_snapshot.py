"""通过模拟 ComfyUI 与临时数据库验证整批预检查及暂停后的冻结输入。"""

from copy import deepcopy
import hashlib
from io import BytesIO
import json

from PIL import Image
import pytest
from sqlalchemy import select

from backend.i18n.errors import AppError
from backend.models.comic import ComicPage, GenerationRun, GenerationTask, VisualAsset
from backend.models.enums import (
    ApprovalStatus, ComicPageStatus, GenerationMode, GenerationTaskKind,
    GenerationTaskStatus, ImageGenerationProvider, ImagePromptType,
    PageScriptReviewStatus, SeedStrategy, VisualAssetRole, VisualAssetStorageKind,
)
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_generation_service import ImageGenerationService
from backend.services.image_spec_service import ImageSpecService
from backend.services.renderer_backends import ComfyUIBackend
from backend.tests.test_image_spec_service import (
    FakeContinuityEventAgent, FakeShotPlannerAgent, _seed_project, _session,
)
from backend.tests.test_reference_inputs import _preset, _spec


def _png(color=(40, 70, 100)) -> bytes:
    content = BytesIO()
    Image.new("RGB", (16, 16), color).save(content, format="PNG")
    return content.getvalue()


class FakeComfyClient:
    """模拟所有图片/队列操作，确保测试不连接本地或远程生图服务。"""

    def __init__(self):
        self.uploads = []
        self.queued = []

    def upload_image(self, **kwargs):
        self.uploads.append(kwargs)
        return f"mock-upload-{len(self.uploads)}.png"

    def queue_prompt(self, workflow):
        self.queued.append(deepcopy(workflow))
        return f"mock-request-{len(self.queued)}"

    def get_history(self, _external_id):
        return {}

    def extract_output_images(self, _history, external_id):
        return [{"filename": f"{external_id}.png", "subfolder": "", "type": "output"}]

    def download_view_image(self, **_kwargs):
        return _png()


async def _setup_batch(tmp_path, monkeypatch, *, capacity=3):
    def no_api_requests(*_args, **_kwargs):
        raise AssertionError("Tests must not contact an image API")
    monkeypatch.setattr("backend.services.renderer_backends.requests.post", no_api_requests)
    monkeypatch.setattr("backend.services.image_spec_service.ContinuityEventAgent", FakeContinuityEventAgent)
    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", FakeShotPlannerAgent)
    session = _session()
    task, pages, _style = _seed_project(session)
    for index, asset in enumerate(session.scalars(select(VisualAsset)).all(), 1):
        path = tmp_path / f"asset-{asset.id}.png"
        content = _png((index * 10, 40, 70))
        path.write_bytes(content)
        asset.storage_kind = VisualAssetStorageKind.LOCAL_FILE
        asset.local_path = str(path)
        asset.renderer_locator = None
        asset.mime_type = "image/png"
        asset.width = asset.height = 16
        asset.sha256 = hashlib.sha256(content).hexdigest()
    preset = _preset(comfy=True, capacity=capacity)
    bindings, workflow = json.loads(preset.bindings_json), json.loads(preset.workflow_json)
    bindings["bindings"].append({"source": "prompt.negative", "node_id": "6", "input_name": "text"})
    workflow["6"] = {"inputs": {"text": "old negative"}}
    preset.bindings_json, preset.workflow_json = json.dumps(bindings), json.dumps(workflow)
    session.add(preset)
    session.commit()
    spec_service = ImageSpecService(ImageSpecRepository(session))
    events = [item async for item in spec_service.stream_compile_task(task_id=task.id, style_profile_id=None, shot_planner_preset_id=None, negative_prompt_preset_id=None, generation_mode=GenerationMode.FINAL, concurrency=1)]
    assert events[-1][0] == "done"
    client = FakeComfyClient()
    service = ImageGenerationService(ComicRepository(session), comfy_client=client, output_dir=tmp_path / "generated")
    return session, task, pages, preset, client, service


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["capacity", "missing_second_page_file"])
async def test_second_page_preflight_failure_has_zero_uploads_and_submissions(tmp_path, monkeypatch, failure):
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch, capacity=2 if failure == "capacity" else 3)
    if failure == "missing_second_page_file":
        # brass_key 只在第二页入镜；第一页的所有参考均有效。
        prop = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.PROP_REFERENCE))
        from pathlib import Path
        Path(prop.local_path).unlink()
    with pytest.raises(AppError):
        _events = [item async for item in service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL, candidates_per_page=1)]
    assert client.uploads == client.queued == []
    assert session.scalars(select(GenerationRun)).all() == []
    assert session.scalars(select(GenerationTask).where(GenerationTask.task_kind == GenerationTaskKind.BATCH)).all() == []


@pytest.mark.asyncio
async def test_continue_uses_frozen_page_ids_tool_images_prompt_and_seeds(tmp_path, monkeypatch):
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    original_tool_id = preset.id
    original_bindings = preset.bindings_json
    batch_id = None
    events = []
    async for event, payload in service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL, candidates_per_page=1):
        events.append(event)
        if event == "start":
            batch_id = payload["task_id"]
        if event == "page_done":
            service.suspend_generation_task(batch_id)
    assert events[-1] == "suspended"
    assert len(client.queued) == 1
    batch = session.get(GenerationTask, batch_id)
    before_snapshot = batch.input_snapshot_json
    frozen = json.loads(before_snapshot)
    saved_page = frozen["pages"][str(pages[1].id)]
    frozen_asset_ids = [item["asset_id"] for item in saved_page["spec"]["reference_inputs"]["items"]]
    frozen_seed = saved_page["seeds"][0][1]

    # 同一工具可修改 Provider、容量、workflow 和 prompt type，但原批次继续用冻结配置。
    preset.provider = ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE
    preset.prompt_type = ImagePromptType.TAG
    preset.workflow_json = "{}"
    preset.bindings_json = "{}"
    preset.capabilities_json = json.dumps({"features": ["txt2img"], "reference_images": {"max_images": 0}})
    preset.api_base_url, preset.model = "https://should-not-be-called.invalid", "changed-model"
    for page in pages:
        page.script_review_status = PageScriptReviewStatus.UNREVIEWED
        page.character_action = "changed after batch start"
    later_page = ComicPage(project_id=task.project_id, section=pages[0].section, page_no=3, summary="added later", status=ComicPageStatus.SCRIPT_READY, script_review_status=PageScriptReviewStatus.UNREVIEWED)
    session.add(later_page)
    for asset in session.scalars(select(VisualAsset)).all():
        asset.status = ApprovalStatus.DRAFT
    session.commit()

    def no_live_sources(*_args, **_kwargs):
        raise AssertionError("Frozen continuation must not consult current source hashes")
    monkeypatch.setattr(ImageSpecService, "current_continuity_source_hash", no_live_sources)
    monkeypatch.setattr(ImageSpecService, "current_image_spec_source_hash", no_live_sources)
    continued = [item async for item in service.stream_continue_for_batch(batch_task_id=batch_id, tool_preset_id=original_tool_id, generation_mode=GenerationMode.FINAL, seed_strategy=SeedStrategy.PER_PAGE, candidates_per_page=1)]
    assert continued[-1][0] == "done"
    assert continued[-1][1]["total"] == 1
    assert continued[-1][1]["failed"] == 0
    assert len(client.queued) == 2
    assert client.queued[-1]["1"]["inputs"]["text"] == saved_page["spec"]["prompt"]["positive"]
    assert client.queued[-1]["2"]["inputs"]["seed"] == frozen_seed
    resumed_run = session.scalars(select(GenerationRun).where(GenerationRun.page_id == pages[1].id)).one()
    assert resumed_run.tool_preset_id == original_tool_id
    assert resumed_run.provider == ImageGenerationProvider.COMFYUI
    assert resumed_run.prompt_type == ImagePromptType.NATURAL_LANGUAGE
    assert resumed_run.bindings_json == original_bindings
    applied = json.loads(resumed_run.applied_spec_json)
    assert [item["asset_id"] for item in applied["reference_inputs"]["items"]] == frozen_asset_ids
    assert session.get(GenerationTask, batch_id).input_snapshot_json == before_snapshot
    assert session.get(GenerationTask, batch_id).status == GenerationTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_missing_explicit_control_is_rejected_before_any_reference_upload(tmp_path):
    preset, spec = _preset(comfy=True), _spec(tmp_path, count=1)
    capabilities = json.loads(preset.capabilities_json)
    capabilities["features"].append("pose")
    preset.capabilities_json = json.dumps(capabilities)
    bindings, workflow = json.loads(preset.bindings_json), json.loads(preset.workflow_json)
    bindings["bindings"].append({"source": "subjects[0].controls.pose", "node_id": "7", "input_name": "image"})
    workflow["7"] = {"inputs": {"image": "example-pose.png"}}
    preset.bindings_json, preset.workflow_json = json.dumps(bindings), json.dumps(workflow)
    spec["subjects"] = [{"controls": {"pose": {"storage_kind": "local_file", "local_path": str(tmp_path / "missing-pose.png"), "role": "pose"}}}]
    spec["required_capabilities"].append("pose")
    client = FakeComfyClient()
    with pytest.raises(AppError):
        await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=GenerationMode.FINAL)
    assert client.uploads == client.queued == []


@pytest.mark.asyncio
async def test_miswired_reference_consumer_is_rejected_before_any_upload(tmp_path):
    preset, spec = _preset(comfy=True), _spec(tmp_path, count=1)
    workflow = json.loads(preset.workflow_json)
    workflow["8"] = {"inputs": {"image": "unrelated-example.png"}}
    # 声明的第一个slot是loader3，而消费节点实际上仍指向样例loader8。
    workflow["10"]["inputs"]["image1"] = ["8", 0]
    preset.workflow_json = json.dumps(workflow)
    client = FakeComfyClient()
    with pytest.raises((AppError, ValueError)):
        await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=GenerationMode.FINAL)
    assert client.uploads == client.queued == []


@pytest.mark.asyncio
async def test_legacy_renderer_name_child_binding_still_resolves_after_local_preflight(tmp_path):
    preset = _preset(comfy=True)
    original = _spec(tmp_path, count=1)["reference_plan"]["items"][0]
    spec = {"prompt": {"positive": "legacy prompt", "negative": ""}, "subjects": [{"identity": {"references": [original]}}], "scene": {}, "required_capabilities": ["txt2img", "reference_image"]}
    bindings = json.loads(preset.bindings_json)
    bindings["reference_slots"] = []
    bindings["bindings"].append({"source": "subjects[0].identity.references[0].renderer_name", "node_id": "3", "input_name": "image"})
    preset.bindings_json = json.dumps(bindings)
    client = FakeComfyClient()
    submitted = await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=GenerationMode.FINAL)
    assert client.uploads[0]["content"] == b"original image 0"
    assert submitted.workflow["3"]["inputs"]["image"] == "mock-upload-1.png"
