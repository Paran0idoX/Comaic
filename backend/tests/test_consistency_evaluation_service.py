import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.evaluation.runtime import METRIC_VERSION, RuntimeReadiness
from backend.i18n.errors import AppError
from backend.models.comic import (
    Base,
    ComicImage,
    ComicPage,
    ComicProject,
    GenerationRun,
    GenerationTask,
    ImageGenerationToolPreset,
    OutlineCharacter,
    OutlineVersion,
    ScriptCharacter,
    ScriptGenerationTask,
    ScriptSection,
    Session as ComicSession,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
    CharacterVisualType,
    ComicPageStatus,
    ConsistencyEvaluationStatus,
    ConsistencyTrackStatus,
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskKind,
    GenerationTaskStatus,
    ImageGenerationProvider,
    ImagePromptType,
    OutlineVersionStatus,
    PageScriptReviewStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
    SeedStrategy,
    SessionPurpose,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.repositories.consistency_evaluation_repository import (
    ConsistencyEvaluationRepository,
)
from backend.services.consistency_evaluation_service import ConsistencyEvaluationService


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def _ready_runtime() -> RuntimeReadiness:
    return RuntimeReadiness(
        ready=True,
        python_executable="python",
        source_root="third_party/vistorybench",
        pretrain_root="data/models/vistorybench",
        missing_modules=[],
        missing_source_files=[],
        missing_weights=[],
        torch_version="test",
        cuda_available=True,
        cuda_device="test-gpu",
    )


class FakeComfyClient:
    def __init__(self) -> None:
        self.freed = False

    def get_queue(self):
        return {"queue_running": [], "queue_pending": []}

    @staticmethod
    def queue_is_idle(payload):
        return not payload["queue_running"] and not payload["queue_pending"]

    def free_memory(self, *, unload_models=True):
        assert unload_models is True
        self.freed = True
        return {}


class PassingRunner:
    def run(self, *, manifest, work_dir):
        del work_dir
        return {
            "metric_version": METRIC_VERSION,
            "tracks": [
                {
                    "candidate_index": track["candidate_index"],
                    "metrics": {
                        "cids_cross": 0.70,
                        "cids_self": 0.75,
                        "csd_cross": 0.65,
                        "csd_self": 0.72,
                        "occm": 95.0,
                        "copy_paste": 0.10,
                    },
                    "applicability": {
                        "cids_cross": True,
                        "cids_self": True,
                        "csd_cross": True,
                        "csd_self": True,
                        "occm": True,
                        "copy_paste": True,
                    },
                    "details": {},
                }
                for track in manifest["tracks"]
            ],
        }


class BelowBenchmarkRunner(PassingRunner):
    def run(self, **kwargs):
        result = super().run(**kwargs)
        for track in result["tracks"]:
            track["metrics"]["cids_cross"] = 0.01
        return result


class FailingRunner:
    def run(self, *, manifest, work_dir):
        del manifest, work_dir
        raise RuntimeError("intentional worker failure")


@pytest.fixture()
def evaluation_fixture(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        project = ComicProject(title="Consistency")
        outline_session = ComicSession(
            project=project,
            thread_id="consistency-test",
            purpose=SessionPurpose.OUTLINE,
        )
        outline = OutlineVersion(
            project=project,
            session=outline_session,
            version_no=1,
            content="test",
            status=OutlineVersionStatus.ACTIVE,
        )
        character = OutlineCharacter(
            outline_version=outline,
            character_key="hero",
            name="Hero",
            appearance="red-haired comic hero",
            visual_type=CharacterVisualType.STYLIZED_HUMAN,
        )
        script_task = ScriptGenerationTask(
            project=project,
            outline_version=outline,
            status=ScriptGenerationTaskStatus.SUCCEEDED,
            mode=ScriptGenerationMode.BATCH,
            total_pages=2,
        )
        section = ScriptSection(
            task=script_task,
            section_no=1,
            page_start=1,
            page_end=2,
            status=ScriptSectionStatus.COMPLETED,
        )
        script_character = ScriptCharacter(
            section=section,
            outline_character=character,
            character_key="hero",
            name="Hero",
        )
        pages = []
        for page_no in (1, 2):
            page = ComicPage(
                project=project,
                section=section,
                page_no=page_no,
                summary=f"page {page_no}",
                scene="room",
                composition="medium shot",
                character_action="standing",
                status=ComicPageStatus.IMAGE_READY,
                script_review_status=PageScriptReviewStatus.PASSED,
            )
            page.visual_characters.append(script_character)
            pages.append(page)
        preset = ImageGenerationToolPreset(
            name="Comfy",
            provider=ImageGenerationProvider.COMFYUI,
            prompt_type=ImagePromptType.NATURAL_LANGUAGE,
        )
        session.add_all([project, preset])
        session.flush()
        batch = GenerationTask(
            project_id=project.id,
            script_task_id=script_task.id,
            tool_preset_id=preset.id,
            task_kind=GenerationTaskKind.BATCH,
            generation_mode=GenerationMode.FINAL,
            seed_strategy=SeedStrategy.SHARED_CANDIDATE,
            candidate_count=1,
            status=GenerationTaskStatus.SUCCEEDED,
            batch_size=2,
        )
        session.add(batch)
        session.flush()
        generated_paths = []
        for page in pages:
            page_task = GenerationTask(
                project_id=project.id,
                page_id=page.id,
                script_task_id=script_task.id,
                tool_preset_id=preset.id,
                parent_task_id=batch.id,
                task_kind=GenerationTaskKind.PAGE,
                generation_mode=GenerationMode.FINAL,
                seed_strategy=SeedStrategy.SHARED_CANDIDATE,
                candidate_count=1,
                status=GenerationTaskStatus.SUCCEEDED,
            )
            session.add(page_task)
            session.flush()
            run = GenerationRun(
                generation_task_id=page_task.id,
                batch_task_id=batch.id,
                page_id=page.id,
                image_spec_id=10_000 + page.id,
                tool_preset_id=preset.id,
                provider=ImageGenerationProvider.COMFYUI,
                prompt_type=ImagePromptType.NATURAL_LANGUAGE,
                candidate_index=1,
                seed=123,
                seed_strategy=SeedStrategy.SHARED_CANDIDATE,
                generation_mode=GenerationMode.FINAL,
                status=GenerationRunStatus.SUCCEEDED,
            )
            session.add(run)
            session.flush()
            path = tmp_path / f"page-{page.page_no}.png"
            _image(path, (page.page_no * 30, 50, 70))
            generated_paths.append(path)
            session.add(
                ComicImage(
                    page_id=page.id,
                    generation_run_id=run.id,
                    artifact_index=1,
                    local_path=str(path),
                    sha256=_sha(path),
                )
            )
        reference_path = tmp_path / "hero-reference.png"
        _image(reference_path, (100, 20, 20))
        reference = VisualAsset(
            project_id=project.id,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=character.id,
            entity_key=character.character_key,
            role=VisualAssetRole.IDENTITY_FULL_BODY,
            storage_kind=VisualAssetStorageKind.LOCAL_FILE,
            local_path=str(reference_path),
            mime_type="image/png",
            sha256=_sha(reference_path),
            version=1,
            status=ApprovalStatus.APPROVED,
            source=VisualAssetSource.UPLOAD,
        )
        session.add(reference)
        session.commit()
        yield {
            "session": session,
            "tmp_path": tmp_path,
            "script_task_id": script_task.id,
            "batch_id": batch.id,
            "reference": reference,
        }


def _service(fixture, *, runner=None, comfy=None):
    return ConsistencyEvaluationService(
        ConsistencyEvaluationRepository(fixture["session"]),
        output_dir=fixture["tmp_path"] / "outputs",
        runtime_probe=_ready_runtime,
        process_runner=runner or PassingRunner(),
        comfy_client=comfy or FakeComfyClient(),
    )


def test_evaluation_checks_its_own_reference_baseline(
    evaluation_fixture,
) -> None:
    service = _service(evaluation_fixture)
    assert service.batch_readiness(evaluation_fixture["batch_id"])["ready"] is True

    evaluation_fixture["session"].delete(evaluation_fixture["reference"])
    evaluation_fixture["session"].commit()
    readiness = service.batch_readiness(evaluation_fixture["batch_id"])
    assert readiness["ready"] is False
    assert {item["code"] for item in readiness["errors"]} >= {
        "consistency.reference_missing"
    }


def test_readiness_snapshots_approved_reference_assets_as_the_cross_baseline(
    evaluation_fixture,
) -> None:
    readiness = _service(evaluation_fixture).batch_readiness(
        evaluation_fixture["batch_id"]
    )

    baseline = readiness["reference_baseline"]
    assert readiness["ready"] is True
    assert baseline["mode"] == "approved_identity_assets"
    assert baseline["reference_count"] == 1
    assert baseline["characters"] == [
        {
            "character_id": evaluation_fixture["reference"].entity_id,
            "character_key": f"char_{evaluation_fixture['reference'].entity_id}",
            "character_name": "Hero",
            "reference_count": 1,
            "references": [
                {
                    "asset_id": evaluation_fixture["reference"].id,
                    "role": "identity_full_body",
                    "version": 1,
                    "sha256": evaluation_fixture["reference"].sha256,
                }
            ],
        }
    ]
    manifest = readiness["manifest"]
    assert manifest["schema_version"] == 2
    assert manifest["reference_baseline"] == baseline
    assert manifest["characters"][0]["references"][0]["asset_id"] == (
        evaluation_fixture["reference"].id
    )


def test_new_approved_generated_reference_changes_the_evaluation_baseline(
    evaluation_fixture,
) -> None:
    service = _service(evaluation_fixture)
    before = service.batch_readiness(evaluation_fixture["batch_id"])
    reference = evaluation_fixture["reference"]
    generated_reference_path = evaluation_fixture["tmp_path"] / "hero-face.png"
    _image(generated_reference_path, (120, 40, 30))
    generated_reference = VisualAsset(
        project_id=reference.project_id,
        entity_type=VisualEntityType.CHARACTER,
        entity_id=reference.entity_id,
        entity_key=reference.entity_key,
        role=VisualAssetRole.IDENTITY_FACE,
        storage_kind=VisualAssetStorageKind.LOCAL_FILE,
        local_path=str(generated_reference_path),
        mime_type="image/png",
        sha256=_sha(generated_reference_path),
        version=1,
        status=ApprovalStatus.APPROVED,
        source=VisualAssetSource.GENERATED_IMAGE,
    )
    evaluation_fixture["session"].add(generated_reference)
    evaluation_fixture["session"].commit()

    after = service.batch_readiness(evaluation_fixture["batch_id"])

    assert after["source_hash"] != before["source_hash"]
    assert after["reference_baseline"]["reference_count"] == 2
    assert {
        item["asset_id"]
        for item in after["reference_baseline"]["characters"][0]["references"]
    } == {reference.id, generated_reference.id}


def test_back_references_never_enter_face_identity_evaluation_or_satisfy_readiness(evaluation_fixture) -> None:
    session = evaluation_fixture["session"]
    reference = evaluation_fixture["reference"]
    reference.role = VisualAssetRole.IDENTITY_BACK
    session.commit()
    service = _service(evaluation_fixture)
    # 模拟调用方返回过宽资产，服务层仍需防御性过滤背面图。
    service.repository.list_approved_identity_assets = lambda **_kwargs: [reference]
    readiness = service.batch_readiness(evaluation_fixture["batch_id"])
    assert readiness["ready"] is False
    assert readiness["manifest"] is None
    assert readiness["reference_baseline"] is None
    assert "consistency.reference_missing" in {item["code"] for item in readiness["errors"]}


def test_side_references_remain_eligible_face_visible_inputs(evaluation_fixture) -> None:
    session = evaluation_fixture["session"]
    reference = evaluation_fixture["reference"]
    reference.role = VisualAssetRole.IDENTITY_SIDE
    session.commit()
    readiness = _service(evaluation_fixture).batch_readiness(evaluation_fixture["batch_id"])
    assert readiness["ready"] is True
    assert readiness["manifest"]["characters"][0]["references"][0]["role"] == "identity_side"


def test_advisory_evaluation_and_threshold_changes_do_not_invalidate_manual_selection(
    evaluation_fixture,
) -> None:
    comfy = FakeComfyClient()
    service = _service(evaluation_fixture, comfy=comfy)
    task = service.create_task(evaluation_fixture["batch_id"])
    assert service.create_task(evaluation_fixture["batch_id"]).id == task.id

    task = service.run_task(task.id)
    assert task.status == ConsistencyEvaluationStatus.SUCCEEDED
    assert comfy.freed is True
    assert len(task.tracks) == 1
    track = task.tracks[0]
    assert track.status == ConsistencyTrackStatus.PASSED
    assert track.passed is True
    assert json.loads(track.details_json)["reference_baseline"]["reference_count"] == 1

    service.adopt_track(track.id)
    gate = service.script_gate(evaluation_fixture["script_task_id"])
    assert gate["passed"] is True
    assert gate["track_id"] is None

    service.update_config(
        cids_cross_min=0.9,
        cids_self_min=0.6,
        csd_cross_min=0.35,
        csd_self_min=0.6,
        occm_min=70,
        copy_paste_max=0.3,
    )
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is True
    with pytest.raises(AppError) as exc_info:
        service.adopt_track(track.id)
    assert exc_info.value.code == "consistency.result_stale"


def test_optional_reference_batches_can_be_evaluated_and_low_scores_can_be_adopted(evaluation_fixture):
    session = evaluation_fixture["session"]
    batch = session.get(GenerationTask, evaluation_fixture["batch_id"])
    batch.generation_mode = GenerationMode.PREVIEW
    for run in session.query(GenerationRun).filter_by(batch_task_id=batch.id):
        run.generation_mode = GenerationMode.PREVIEW
    session.commit()
    service = _service(evaluation_fixture, runner=BelowBenchmarkRunner())
    assert service.batch_readiness(batch.id)["ready"]
    task = service.run_task(service.create_task(batch.id).id)
    assert task.status == ConsistencyEvaluationStatus.SUCCEEDED
    track = task.tracks[0]
    assert track.status == ConsistencyTrackStatus.FAILED
    assert not track.passed
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is False
    service.adopt_track(track.id)
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is True


def test_manual_selection_completes_without_evaluation_or_a_reference_baseline(evaluation_fixture):
    session = evaluation_fixture["session"]
    session.delete(evaluation_fixture["reference"])
    pages = session.query(ComicPage).all()
    for page in pages:
        image = page.images[0]
        page.selected_image_id = image.id
        image.is_selected = True
    session.commit()
    service = _service(evaluation_fixture)
    assert not service.batch_readiness(evaluation_fixture["batch_id"])["ready"]
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is True
    pages[0].selected_image_id = None
    session.commit()
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is False


def test_failed_evaluation_does_not_invalidate_existing_manual_selection(evaluation_fixture):
    service = _service(evaluation_fixture)
    task = service.run_task(service.create_task(evaluation_fixture["batch_id"]).id)
    service.adopt_track(task.tracks[0].id)
    service.update_config(cids_cross_min=0.99, cids_self_min=0.6, csd_cross_min=0.35, csd_self_min=0.6, occm_min=70, copy_paste_max=0.3)
    service.process_runner = FailingRunner()
    failed = service.run_task(service.create_task(evaluation_fixture["batch_id"]).id)
    assert failed.status == ConsistencyEvaluationStatus.FAILED
    assert service.script_gate(evaluation_fixture["script_task_id"])["passed"] is True


def test_gate_uses_and_and_skips_only_explicitly_inapplicable_metrics() -> None:
    thresholds = {
        "cids_cross_min": 0.45,
        "cids_self_min": 0.60,
        "csd_cross_min": 0.35,
        "csd_self_min": 0.60,
        "occm_min": 70.0,
        "copy_paste_max": 0.30,
    }
    raw = {
        "metrics": {
            "cids_cross": 0.45,
            "cids_self": None,
            "csd_cross": 0.35,
            "csd_self": 0.60,
            "occm": 70.0,
            "copy_paste": 0.31,
        },
        "applicability": {"cids_self": False},
    }
    status, checks = ConsistencyEvaluationService._gate_track(raw, thresholds)
    assert status == ConsistencyTrackStatus.FAILED
    assert checks["cids_self"]["passed"] is True
    assert checks["copy_paste"]["passed"] is False


def test_failed_snapshot_retry_reuses_the_idempotent_task(evaluation_fixture) -> None:
    failed_service = _service(evaluation_fixture, runner=FailingRunner())
    first = failed_service.create_task(evaluation_fixture["batch_id"])
    failed = failed_service.run_task(first.id)
    assert failed.status == ConsistencyEvaluationStatus.FAILED

    retry = _service(evaluation_fixture).create_task(evaluation_fixture["batch_id"])
    assert retry.id == first.id
    assert retry.status == ConsistencyEvaluationStatus.PENDING
    assert all(track.status == ConsistencyTrackStatus.PENDING for track in retry.tracks)
