"""浏览器验收用真实 API：隔离 SQLite，模拟模型、ComfyUI 和评测指标。"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=18124)
parser.add_argument("--artifacts", required=True)
args = parser.parse_args()
ARTIFACTS = Path(args.artifacts).resolve()
ARTIFACTS.relative_to(ROOT / ".codex-artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
database = ARTIFACTS / "test.sqlite3"
if database.exists():
    raise RuntimeError("Use a fresh E2E artifacts directory; existing databases are preserved.")
os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()

import requests
import uvicorn
from sqlalchemy import select
from backend.i18n.errors import AppError
from backend.main import app
from backend.models.database import SessionLocal, init_db
from backend.models.comic import ComicImage, ComicPage, ConsistencyEvaluationTask, GenerationRun, GenerationTask, ImageSpec, ImageSpecCompilation, ReferenceSubject, VisualAsset
from backend.models.enums import ApprovalStatus, ComicPageStatus, GenerationMode, GenerationTaskKind, GenerationTaskStatus, VisualAssetStorageKind, VisualEntityType
from backend.repositories.comic_repository import ComicRepository
from backend.services.image_generation_service import ImageGenerationService
import backend.api.image_generation as generation_api
import backend.api.consistency_evaluation as evaluation_api
import backend.api.settings as settings_api
import backend.api.visual_bible as visual_api
import backend.services.image_spec_service as spec_module
import backend.services.renderer_backends as render_module
import backend.services.consistency_evaluation_runtime as evaluation_runtime
from backend.services.consistency_evaluation_service import ConsistencyEvaluationService
from backend.tests.test_consistency_evaluation_service import (
    BelowBenchmarkRunner, FakeComfyClient as EvaluationComfyClient, _ready_runtime,
)
from backend.tests.test_image_spec_service import _seed_project
from backend.tests.test_reference_batch_snapshot import BatchShotPlanner, FakeComfyClient, _png
from backend.tests.test_reference_inputs import _preset
from backend.agents.outline_agent import OutlineAgent
from backend.services.visual_bible_service import VisualBibleService
from backend.services.workflow_compiler import parse_bindings, parse_capabilities


def deny_network(*_args, **_kwargs):
    raise AssertionError("E2E must not call a real LLM or image service")


requests.sessions.Session.request = deny_network
original_load_messages = OutlineAgent.load_conversation_messages


async def isolated_load_messages(cls, *, thread_id, **kwargs):
    return await original_load_messages(thread_id=thread_id, memory_path=ARTIFACTS / "outline-memory.sqlite3")


OutlineAgent.load_conversation_messages = classmethod(isolated_load_messages)
CONTROL = {"fail_page_no": None, "pause_next": False}
PLANNED = []
ORIGINAL_BYTES = {}
ORIGINAL_TOOL = {}


class E2EPlanner(BatchShotPlanner):
    async def translate_prompt_components(self, components, language):
        from backend.tests.test_prompt_language import TRANSLATIONS
        return dict(TRANSLATIONS[language])

    async def plan(self, *, page, **kwargs):
        PLANNED.append(page["page_id"])
        await asyncio.sleep(0.15)
        if CONTROL["fail_page_no"] == page["page_no"]:
            CONTROL["fail_page_no"] = None
            raise AppError("image_spec.shot_plan_invalid", status_code=422, params={"count": 1})
        return await super().plan(page=page, **kwargs)


class E2EClient(FakeComfyClient):
    def queue_prompt(self, workflow):
        result = super().queue_prompt(workflow)
        if CONTROL["pause_next"]:
            CONTROL["pause_next"] = False
            with SessionLocal() as db:
                batch = db.scalar(select(GenerationTask).where(
                    GenerationTask.task_kind == GenerationTaskKind.BATCH,
                    GenerationTask.status == GenerationTaskStatus.RUNNING,
                ).order_by(GenerationTask.id.desc()))
                batch.status = GenerationTaskStatus.SUSPENDED
                db.commit()
        return result


CLIENT = E2EClient()
spec_module.ShotPlannerAgent = E2EPlanner
render_module.ComfyUIClient = lambda *_args, **_kwargs: CLIENT


class E2EGenerationService(ImageGenerationService):
    def __init__(self, repository):
        super().__init__(repository, comfy_client=CLIENT, output_dir=ARTIFACTS / "generated")


generation_api.ImageGenerationService = E2EGenerationService


class E2EEvaluationService(ConsistencyEvaluationService):
    """使用低于参考值的固定指标，验收真实评测入库及人工采用流程。"""

    def __init__(self, repository):
        super().__init__(repository, output_dir=ARTIFACTS, comfy_client=EvaluationComfyClient(),
                         runtime_probe=_ready_runtime, process_runner=BelowBenchmarkRunner())


evaluation_api.ConsistencyEvaluationService = E2EEvaluationService
evaluation_runtime.ConsistencyEvaluationService = E2EEvaluationService
settings_api.ConsistencyEvaluationService = E2EEvaluationService


class E2EVisualService(VisualBibleService):
    def __init__(self, repository, **kwargs):
        super().__init__(repository, asset_root=ARTIFACTS, **kwargs)


visual_api.VisualBibleService = E2EVisualService
init_db()
with SessionLocal() as db:
    task, pages, _ = _seed_project(db)
    task.outline_version.confirmed_at = task.created_at
    subject = ReferenceSubject(project_id=task.project_id, entity_type=VisualEntityType.SCENE,
                               key="workshop-reference", name="Workshop reference")
    db.add(subject)
    db.flush()
    pages[0].script_scene.reference_subject_id = subject.id
    for index, asset in enumerate(db.scalars(select(VisualAsset)), 1):
        if asset.entity_type == VisualEntityType.SCENE:
            # 目录通用原图仍可供新场景版本选择，不把旧版本专用图冒充通用图。
            asset.entity_id, asset.reference_subject_id = None, subject.id
        original = ARTIFACTS / f"original-{asset.id}.png"
        content = _png((index * 20, 60, 90))
        original.write_bytes(content)
        ORIGINAL_BYTES[str(original)] = content
        asset.storage_kind = VisualAssetStorageKind.LOCAL_FILE
        asset.local_path, asset.renderer_locator = str(original), None
        asset.sha256 = hashlib.sha256(content).hexdigest()
        asset.mime_type, asset.width, asset.height = "image/png", 16, 16
    tool = _preset(comfy=True)
    bindings, workflow = json.loads(tool.bindings_json), json.loads(tool.workflow_json)
    bindings["bindings"].append({"source": "prompt.negative", "node_id": "6", "input_name": "text"})
    workflow["6"] = {"inputs": {"text": "old negative"}}
    tool.bindings_json = json.dumps(parse_bindings(json.dumps(bindings)).model_dump(mode="json"))
    tool.workflow_json = json.dumps(workflow)
    tool.capabilities_json = json.dumps(parse_capabilities(tool.capabilities_json).model_dump(mode="json"))
    tool.name, tool.is_default = "E2E simulated ComfyUI", True
    tool.seed_node_id, tool.seed_input_name = "2", "seed"
    tool.comfy_base_url = CLIENT.base_url
    ORIGINAL_TOOL = {key: getattr(tool, key) for key in (
        "seed_node_id", "seed_input_name", "workflow_json", "bindings_json", "capabilities_json",
    )}
    db.add(tool)
    old_path = ARTIFACTS / "existing-candidate.png"
    old_path.write_bytes(_png())
    old = ComicImage(page=pages[0], local_path=str(old_path), seed=7, is_selected=True,
                     width=16, height=16, prompt="Previous manually selected candidate")
    db.add(old)
    db.flush()
    pages[0].selected_image_id = old.id
    pages[0].status = ComicPageStatus.IMAGE_SELECTED
    db.commit()
    FIXTURE = {"project_id": task.project_id, "task_id": task.id,
               "page_ids": [page.id for page in pages], "old_image_id": old.id,
               "tool_id": tool.id, "character_id": pages[0].visual_characters[0].id,
               "scene_id": pages[0].scene_id}


@app.get("/__e2e/state")
def state():
    """仅测试进程提供观测接口，用数据库证据核对浏览器操作。"""
    with SessionLocal() as db:
        repo = ComicRepository(db)
        batches = db.scalars(select(GenerationTask).where(
            GenerationTask.task_kind == GenerationTaskKind.BATCH,
        ).order_by(GenerationTask.id)).all()
        return {**FIXTURE, "planned": PLANNED, "queued": CLIENT.queued,
                "compilations": [{"id": item.id, "status": item.status.value} for item in db.scalars(select(ImageSpecCompilation).order_by(ImageSpecCompilation.id))],
                "upload_count": len(CLIENT.uploads),
                "pages": [{"id": page.id, "selected_image_id": page.selected_image_id,
                           "images": [{"id": image.id, "selected": image.is_selected} for image in page.images]}
                          for page in repo.list_script_task_pages(FIXTURE["task_id"])],
                "specs": [{"id": spec.id, "page_id": spec.page_id, "type": spec.prompt_type.value,
                           "mode": spec.generation_mode.value, "shot_plan_id": spec.shot_plan_id,
                           "language": json.loads(spec.spec_json).get("prompt_language", "original")}
                          for spec in db.scalars(select(ImageSpec).order_by(ImageSpec.id))],
                "batches": [{"id": batch.id, "status": batch.status.value,
                             "mode": batch.generation_mode.value,
                             "snapshot": json.loads(batch.input_snapshot_json or "{}")}
                            for batch in batches],
                "evaluations": [{"id": task.id, "status": task.status.value, "batch_id": task.batch_task_id,
                                 "tracks": [{"id": track.id, "status": track.status.value,
                                             "image_ids": json.loads(track.image_ids_json),
                                             "adopted": track.adopted_at is not None} for track in task.tracks]}
                                for task in db.scalars(select(ConsistencyEvaluationTask).order_by(ConsistencyEvaluationTask.id))]}


@app.post("/__e2e/control")
def control(values: dict):
    """可重复构造本页过期、一次失败、暂停和冻结文件变动。"""
    if "fail_page_no" in values:
        CONTROL["fail_page_no"] = values["fail_page_no"]
    if "pause_next" in values:
        CONTROL["pause_next"] = bool(values["pause_next"])
    with SessionLocal() as db:
        if "stale_page_no" in values:
            page = db.scalar(select(ComicPage).where(ComicPage.page_no == values["stale_page_no"]))
            page.summary += " Visible E2E revision."
        if values.get("change_tool"):
            preset = ComicRepository(db).get_image_generation_tool_preset(FIXTURE["tool_id"])
            preset.seed_node_id = preset.seed_input_name = None
            preset.workflow_json = '{"invalid-current-tool": {"inputs": {}}}'
            preset.bindings_json = '{"bindings": []}'
        if values.get("restore_tool"):
            preset = ComicRepository(db).get_image_generation_tool_preset(FIXTURE["tool_id"])
            for key, value in ORIGINAL_TOOL.items():
                setattr(preset, key, value)
        if "missing_references" in values:
            for asset in db.scalars(select(VisualAsset)):
                asset.status = ApprovalStatus.DRAFT if values["missing_references"] else ApprovalStatus.APPROVED
        if values.get("legacy_frozen_mode"):
            # 构造旧已冻结批次；只改历史模式元数据，原 Prompt、工具、顺序和 seed 不变。
            batch = db.scalar(select(GenerationTask).where(
                GenerationTask.task_kind == GenerationTaskKind.BATCH,
            ).order_by(GenerationTask.id.desc()))
            batch.generation_mode = GenerationMode.FINAL
            snapshot = json.loads(batch.input_snapshot_json)
            for saved in snapshot["pages"].values():
                saved["spec"]["generation_mode"] = GenerationMode.FINAL.value
            batch.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            for child in db.scalars(select(GenerationTask).where(GenerationTask.parent_task_id == batch.id)):
                child.generation_mode = GenerationMode.FINAL
            for run in db.scalars(select(GenerationRun).where(GenerationRun.batch_task_id == batch.id)):
                run.generation_mode = GenerationMode.FINAL
        if values.get("corrupt_original"):
            asset = db.scalar(select(VisualAsset).where(VisualAsset.entity_type == "character"))
            Path(asset.local_path).write_bytes(b"changed original")
        if values.get("restore_original"):
            for original, content in ORIGINAL_BYTES.items():
                Path(original).write_bytes(content)
        db.commit()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off", log_level="warning")
