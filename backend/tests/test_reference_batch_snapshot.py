"""通过模拟 ComfyUI 与临时数据库验证整批预检查及暂停后的冻结输入。"""

from copy import deepcopy
import hashlib
from io import BytesIO
import json

from PIL import Image
import pytest
from sqlalchemy import select

from backend.i18n.errors import AppError
from backend.models.comic import ComicPage, GenerationRun, GenerationTask, ImageSpec, VisualAsset
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
    FakeShotPlannerAgent, _seed_project, _session,
)
from backend.tests.test_reference_inputs import _preset, _spec
from backend.utils.json_utils import canonical_json


def _png(color=(40, 70, 100)) -> bytes:
    content = BytesIO()
    Image.new("RGB", (16, 16), color).save(content, format="PNG")
    return content.getvalue()


class FakeComfyClient:
    """模拟所有图片/队列操作，确保测试不连接本地或远程生图服务。"""

    def __init__(self):
        self.base_url = "http://mock-comfy.invalid"
        self.uploads = []
        self.queued = []

    def upload_image(self, **kwargs):
        self.uploads.append(kwargs)
        return f"mock-upload-{len(self.uploads)}.png"

    def queue_prompt(self, workflow):
        self.queued.append(deepcopy(workflow))
        return f"mock-request-{len(self.queued)}"

    def get_history(self, external_id):
        return {external_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {"save": {"images": [{"filename": f"{external_id}.png", "type": "output"}]}},
        }}

    def get_queue(self):
        return {"queue_running": [], "queue_pending": []}

    def extract_output_images(self, _history, external_id):
        return [{"filename": f"{external_id}.png", "subfolder": "", "type": "output"}]

    def extract_execution_error(self, _history, _external_id):
        return None

    def download_view_image(self, **_kwargs):
        return _png()


class BatchShotPlanner(FakeShotPlannerAgent):
    """参考图测试显式声明第二页物品入镜，不再依赖前页拾取事件。"""

    async def plan(self, *, page, snapshot, **kwargs):
        plan = await super().plan(page=page, snapshot=snapshot, **kwargs)
        plan["scene"]["visible_prop_keys"] = ["brass_key"] if page["page_no"] == 2 else []
        for subject in plan["subjects"]:
            subject["visible_prop_keys"] = []
        return plan


async def _setup_batch(tmp_path, monkeypatch, *, capacity=3):
    def no_api_requests(*_args, **_kwargs):
        raise AssertionError("Tests must not contact an image API")
    monkeypatch.setattr("backend.services.renderer_backends.requests.post", no_api_requests)
    monkeypatch.setattr("backend.services.image_spec_service.ShotPlannerAgent", BatchShotPlanner)
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
@pytest.mark.parametrize("failure", ["invalid_binding", "missing_second_page_file"])
async def test_second_page_preflight_failure_has_zero_uploads_and_submissions(tmp_path, monkeypatch, failure):
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    if failure == "invalid_binding":
        bindings = json.loads(preset.bindings_json)
        bindings["bindings"][0]["node_id"] = "nonexistent-node"
        preset.bindings_json = json.dumps(bindings)
        session.commit()
    if failure == "missing_second_page_file":
        # brass_key 只在第二页入镜；第一页的所有参考均有效。
        prop = session.scalar(select(VisualAsset).where(VisualAsset.role == VisualAssetRole.PROP_REFERENCE))
        from pathlib import Path
        Path(prop.local_path).unlink()
    with pytest.raises((AppError, ValueError)):
        _events = [item async for item in service.stream_generate_for_script_task(task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL, candidates_per_page=1)]
    assert client.uploads == client.queued == []
    assert session.scalars(select(GenerationRun)).all() == []
    assert session.scalars(select(GenerationTask).where(GenerationTask.task_kind == GenerationTaskKind.BATCH)).all() == []


@pytest.mark.asyncio
async def test_unstarted_historical_context_is_stale_before_any_submission(tmp_path, monkeypatch):
    """旧连续性来源的未开始规格必须重新准备，不能混入新的按页上下文批次。"""
    session, task, _pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    spec = session.scalar(select(ImageSpec))
    spec.snapshot.state_hash = "0" * 64
    session.commit()
    with pytest.raises(ValueError, match="ImageSpec is stale"):
        _events = [item async for item in service._stream_generate_pages(
            script_task=task, pages=_pages, preset=preset, generation_mode=GenerationMode.PREVIEW,
            candidates_per_page=1, poll_interval_seconds=2, wait_timeout_seconds=600,
            seed_strategy=SeedStrategy.PER_PAGE, existing_batch_task=None,
        )]
    assert client.uploads == client.queued == []
    assert session.scalars(select(GenerationRun)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_prompt", [False, True])
@pytest.mark.parametrize("historical_mode", [False, True])
async def test_continue_uses_frozen_page_ids_tool_images_prompt_and_seeds(tmp_path, monkeypatch, legacy_prompt, historical_mode):
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
    frozen = json.loads(batch.input_snapshot_json)
    if historical_mode:
        # 模拟退役选择器以前的已冻结 FINAL 批次，续跑参数不能改写其策略。
        batch.generation_mode = GenerationMode.FINAL
        for saved in frozen["pages"].values():
            saved["spec"]["generation_mode"] = GenerationMode.FINAL.value
        for child in session.scalars(select(GenerationTask).where(GenerationTask.parent_task_id == batch_id)):
            child.generation_mode = GenerationMode.FINAL
        for run in session.scalars(select(GenerationRun).where(GenerationRun.batch_task_id == batch_id)):
            run.generation_mode = GenerationMode.FINAL
    if legacy_prompt:
        # 模拟升级前保存的 Prompt，续跑不能用新编译器或编号逻辑重建它。
        historical_spec = frozen["pages"][str(pages[1].id)]["spec"]
        historical_spec["prompt"]["positive"] = "Historical frozen positive prompt with original image labels."
        historical_spec["prompt"]["negative"] = "Historical frozen negative prompt."
        historical_spec["compiler"]["version"] = "historical"
    batch.input_snapshot_json = canonical_json(frozen)
    session.commit()
    before_snapshot = batch.input_snapshot_json
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
        page.scene_conditions_json = json.dumps({"time_of_day": "day", "weather": "snow", "lighting": "daylight", "atmosphere": "calm"})
    later_page = ComicPage(project_id=task.project_id, section=pages[0].section, page_no=3, summary="added later", status=ComicPageStatus.SCRIPT_READY, script_review_status=PageScriptReviewStatus.UNREVIEWED)
    session.add(later_page)
    for asset in session.scalars(select(VisualAsset)).all():
        asset.status = ApprovalStatus.DRAFT
    session.commit()

    def no_live_sources(*_args, **_kwargs):
        raise AssertionError("Frozen continuation must not consult current source hashes")
    monkeypatch.setattr(ImageSpecService, "current_page_context_source_hash", no_live_sources)
    monkeypatch.setattr(ImageSpecService, "current_page_context_hashes", no_live_sources)
    monkeypatch.setattr(ImageSpecService, "current_image_spec_source_hash", no_live_sources)
    monkeypatch.setattr("backend.services.reference_inputs.apply_reference_prompt", no_live_sources)
    monkeypatch.setattr("backend.services.image_spec_compilers.BaseImageSpecCompiler.compile", no_live_sources)
    continued = [item async for item in service.stream_continue_for_batch(batch_task_id=batch_id, tool_preset_id=original_tool_id, seed_strategy=SeedStrategy.PER_PAGE, candidates_per_page=1)]
    assert continued[-1][0] == "done"
    assert continued[-1][1]["total"] == 1
    assert continued[-1][1]["failed"] == 0
    assert len(client.queued) == 2
    assert client.queued[-1]["1"]["inputs"]["text"] == saved_page["spec"]["prompt"]["positive"]
    assert client.queued[-1]["6"]["inputs"]["text"] == saved_page["spec"]["prompt"]["negative"]
    assert client.queued[-1]["2"]["inputs"]["seed"] == frozen_seed
    resumed_run = session.scalars(select(GenerationRun).where(GenerationRun.page_id == pages[1].id)).one()
    assert resumed_run.tool_preset_id == original_tool_id
    assert resumed_run.provider == ImageGenerationProvider.COMFYUI
    assert resumed_run.prompt_type == ImagePromptType.NATURAL_LANGUAGE
    assert resumed_run.generation_mode == (GenerationMode.FINAL if historical_mode else GenerationMode.PREVIEW)
    assert resumed_run.bindings_json == original_bindings
    applied = json.loads(resumed_run.applied_spec_json)
    assert [item["asset_id"] for item in applied["reference_inputs"]["items"]] == frozen_asset_ids
    assert session.get(GenerationTask, batch_id).input_snapshot_json == before_snapshot
    assert session.get(GenerationTask, batch_id).status == GenerationTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_partial_failure_keeps_batch_retryable_and_only_retries_missing_page(tmp_path, monkeypatch):
    """批次部分失败不能显示为全部成功；继续仅补齐失败页面且沿用冻结 seed。"""
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    queue = client.queue_prompt
    failed_once = False

    def fail_second_submission_once(workflow):
        nonlocal failed_once
        if len(client.queued) == 1 and not failed_once:
            failed_once = True
            raise RuntimeError("Simulated temporary submission failure")
        return queue(workflow)

    monkeypatch.setattr(client, "queue_prompt", fail_second_submission_once)
    events = [item async for item in service.stream_generate_for_script_task(
        task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL,
        candidates_per_page=1,
    )]
    batch_id = events[0][1]["task_id"]
    assert events[-1][0] == "done"
    assert events[-1][1]["status"] == GenerationTaskStatus.FAILED.value
    assert events[-1][1]["succeeded"] == events[-1][1]["failed"] == 1
    assert session.get(GenerationTask, batch_id).status == GenerationTaskStatus.FAILED
    failed_run = session.scalars(select(GenerationRun).where(GenerationRun.page_id == pages[1].id)).one()

    continued = [item async for item in service.stream_continue_for_batch(
        batch_task_id=batch_id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL,
        seed_strategy=SeedStrategy.PER_PAGE, candidates_per_page=1,
    )]
    assert [payload["page_id"] for event, payload in continued if event == "page_done"] == [pages[1].id]
    assert continued[-1][1]["status"] == GenerationTaskStatus.SUCCEEDED.value
    assert continued[-1][1]["total"] == 1
    assert len(client.queued) == 2
    retried_run = session.scalars(select(GenerationRun).order_by(GenerationRun.id.desc())).first()
    assert retried_run.candidate_index == failed_run.candidate_index
    assert retried_run.seed == failed_run.seed


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_snapshot", [False, True])
async def test_fifty_page_resume_preserves_numeric_page_order(tmp_path, monkeypatch, legacy_snapshot):
    """两位数页 ID 经规范 JSON 排序后，续跑仍必须按冻结的页序提交。"""
    session, task, pages, preset, client, service = await _setup_batch(tmp_path, monkeypatch)
    template = session.scalar(select(ImageSpec).where(
        ImageSpec.page_id == pages[-1].id,
        ImageSpec.prompt_type == ImagePromptType.NATURAL_LANGUAGE,
    ))
    # 模拟分段并行落库：页面主键与页码不一致，不能按数字 page_id 修复。
    for page_no in range(50, 2, -1):
        page = ComicPage(project_id=task.project_id, section=pages[-1].section,
                         page_no=page_no, summary=f"Page {page_no}",
                         status=ComicPageStatus.SPEC_READY,
                         script_review_status=PageScriptReviewStatus.PASSED)
        session.add(page)
        session.flush()
        # 只放大已编译的本地 fixture，测试提交顺序而不调用规划/生图模型。
        values = {column.name: getattr(template, column.name)
                  for column in ImageSpec.__table__.columns
                  if column.name not in {"id", "page_id", "created_at"}}
        session.add(ImageSpec(page_id=page.id, **values))
        pages.append(page)
    pages.sort(key=lambda page: page.page_no)
    session.commit()
    monkeypatch.setattr(ImageSpecService, "current_page_context_hashes",
                        lambda _self, _task_id, **_kwargs: {
                            item.page_id: item.snapshot.state_hash
                            for item in session.scalars(select(ImageSpec)).all()
                        })
    monkeypatch.setattr(ImageSpecService, "current_image_spec_source_hash",
                        lambda _self, spec: spec.source_hash)

    batch_id = None
    completed_pages = []
    async for event, payload in service.stream_generate_for_script_task(
        task_id=task.id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL,
        candidates_per_page=1,
    ):
        if event == "start":
            batch_id = payload["task_id"]
        if event == "page_done":
            completed_pages.append(payload["page_no"])
            if len(completed_pages) == 3:
                service.suspend_generation_task(batch_id)
    assert completed_pages == [1, 2, 3]
    batch = session.get(GenerationTask, batch_id)
    snapshot = json.loads(batch.input_snapshot_json)
    assert snapshot["page_order"] == [page.id for page in pages]
    assert list(snapshot["pages"]) != [str(page.id) for page in pages]
    if legacy_snapshot:
        snapshot.pop("page_order")
        batch.input_snapshot_json = canonical_json(snapshot)
        session.commit()
    before_snapshot = batch.input_snapshot_json

    continued = [item async for item in service.stream_continue_for_batch(
        batch_task_id=batch_id, tool_preset_id=preset.id, generation_mode=GenerationMode.FINAL,
        seed_strategy=SeedStrategy.PER_PAGE, candidates_per_page=1,
    )]
    assert [payload["page_no"] for event, payload in continued if event == "page_done"] == list(range(4, 51))
    assert continued[-1][1]["total"] == continued[-1][1]["succeeded"] == 47
    assert continued[-1][1]["failed"] == 0
    assert len(client.queued) == 50
    assert session.get(GenerationTask, batch_id).input_snapshot_json == before_snapshot
    assert [run.page.page_no for run in session.scalars(select(GenerationRun).order_by(GenerationRun.id))] == list(range(1, 51))


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
@pytest.mark.parametrize("output_index", [0, 1])
async def test_undeclared_reference_consumer_is_rejected_before_any_upload(tmp_path, output_index):
    preset, spec = _preset(comfy=True), _spec(tmp_path, count=1)
    workflow = json.loads(preset.workflow_json)
    # 第二槽为空；遗漏图片或 mask 消费者都会在移除 loader 后留下悬空连接。
    workflow["11"] = {"inputs": {"condition": ["4", output_index]}}
    preset.workflow_json = json.dumps(workflow)
    client = FakeComfyClient()
    with pytest.raises(ValueError, match="undeclared consumer"):
        await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=GenerationMode.FINAL)
    assert client.uploads == client.queued == []


@pytest.mark.asyncio
async def test_all_declared_consumers_are_disconnected_for_empty_reference_slot(tmp_path):
    preset, spec = _preset(comfy=True), _spec(tmp_path, count=1)
    workflow, bindings = json.loads(preset.workflow_json), json.loads(preset.bindings_json)
    workflow["11"] = {"inputs": {"mask": ["4", 1], "strength": 0.5}}
    bindings["reference_slots"][1]["disconnect"].append({"node_id": "11", "input_name": "mask"})
    preset.workflow_json, preset.bindings_json = json.dumps(workflow), json.dumps(bindings)
    client = FakeComfyClient()
    submission = await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=GenerationMode.FINAL)
    assert "4" not in submission.workflow
    assert submission.workflow["11"]["inputs"] == {"strength": 0.5}
    assert len(client.uploads) == len(client.queued) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["capacity", "missing_file"])
async def test_comfy_reference_omissions_are_reported_as_run_degradations(tmp_path, failure):
    preset, spec = _preset(comfy=True, capacity=2), _spec(tmp_path)
    mode = GenerationMode.FINAL
    if failure == "missing_file":
        spec["reference_plan"]["items"][1]["local_path"] = str(tmp_path / "missing-auxiliary.png")
        mode = GenerationMode.PREVIEW
    client = FakeComfyClient()
    submission = await ComfyUIBackend(preset, client).submit(spec=spec, seed=10, mode=mode)
    # 未选中的辅助图不传输；它的文件缺失不会阻止能成功提交的主图。
    expected = "reference.capacity_exceeded"
    assert [item["code"] for item in submission.degradations] == [expected]
    assert submission.degradations == submission.applied_spec["reference_inputs"]["degradations"]
    assert [item["asset_id"] for item in submission.applied_spec["reference_inputs"]["items"]] == [1, 3]
    assert len(client.uploads) == 2


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
