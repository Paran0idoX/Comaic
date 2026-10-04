"""基于 ViStoryBench 的旁路一致性评测，不限制人工选图。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

from backend.evaluation import REFERENCE_BASELINE_MODE
from backend.evaluation.runtime import (
    METRIC_VERSION,
    RuntimeReadiness,
    ViStoryBenchProcessRunner,
    probe_runtime,
)
from backend.i18n.errors import AppError
from backend.models.comic import (
    ComicImage,
    ConsistencyEvaluationConfig,
    ConsistencyEvaluationTask,
    ConsistencyEvaluationTrack,
    GenerationRun,
    OutlineCharacter,
)
from backend.models.enums import (
    ConsistencyEvaluationStatus,
    ConsistencyTrackStatus,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationProvider,
)
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.consistency_evaluation_repository import (
    ConsistencyEvaluationRepository,
    FACE_VISIBLE_IDENTITY_ASSET_ROLES,
)
from backend.repositories.generation_repository import GenerationRepository
from backend.services.task_runtime import RuntimeTaskType, running_task_registry
from backend.tools.comfyui_client import ComfyUIClient
from backend.utils.json_utils import canonical_hash


THRESHOLD_FIELDS = (
    "cids_cross_min",
    "cids_self_min",
    "csd_cross_min",
    "csd_self_min",
    "occm_min",
    "copy_paste_max",
)


class ConsistencyEvaluationService:
    """检查评测自身的输入并执行官方指标，阈值仅供参考。"""

    def __init__(
        self,
        repository: ConsistencyEvaluationRepository,
        *,
        output_dir: str | Path = "outputs",
        comfy_client: ComfyUIClient | None = None,
        runtime_probe: Callable[[], RuntimeReadiness] = probe_runtime,
        process_runner: ViStoryBenchProcessRunner | None = None,
    ):
        self.repository = repository
        self.session = repository.session
        self.comic_repository = ComicRepository(self.session)
        self.generation_repository = GenerationRepository(self.session)
        self.output_dir = Path(output_dir)
        self._comfy_client_override = comfy_client
        self.comfy_client = comfy_client or ComfyUIClient(
            os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
        )
        self.runtime_probe = runtime_probe
        self.process_runner = process_runner or ViStoryBenchProcessRunner()

    def get_config(self) -> ConsistencyEvaluationConfig:
        return self.repository.get_config()

    def update_config(self, **values: float) -> ConsistencyEvaluationConfig:
        for field_name in THRESHOLD_FIELDS:
            if field_name not in values:
                raise AppError(
                    code="consistency.threshold_invalid",
                    debug_message=f"Missing threshold field: {field_name}",
                )
        for field_name, value in values.items():
            upper = 100.0 if field_name == "occm_min" else 1.0
            if not 0.0 <= float(value) <= upper:
                raise AppError(
                    code="consistency.threshold_invalid",
                    debug_message=f"{field_name} must be between 0 and {upper}",
                )
        return self.repository.update_config(**values)

    def runtime_readiness(self) -> dict[str, Any]:
        return self.runtime_probe().to_dict()

    def batch_readiness(
        self,
        batch_task_id: int,
        *,
        include_runtime: bool = True,
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        manifest = self._build_manifest(batch_task_id, errors=errors, warnings=warnings)
        runtime = self.runtime_probe().to_dict() if include_runtime else None
        if include_runtime and runtime and not runtime["ready"]:
            errors.append(
                {
                    "code": "consistency.runtime_not_ready",
                    "message": "ViStoryBench runtime, weights, or CUDA is not ready.",
                    "details": runtime,
                }
            )
        return {
            "ready": not errors and manifest is not None,
            "batch_task_id": batch_task_id,
            "metric_version": METRIC_VERSION,
            "errors": errors,
            "warnings": warnings,
            "runtime": runtime,
            "track_count": len(manifest["tracks"]) if manifest else 0,
            "incomplete_tracks": manifest.get("incomplete_tracks", [])
            if manifest
            else [],
            "source_hash": canonical_hash(manifest) if manifest else None,
            "reference_baseline": (
                manifest.get("reference_baseline") if manifest else None
            ),
            "manifest": manifest,
        }

    def create_task(self, batch_task_id: int) -> ConsistencyEvaluationTask:
        readiness = self.batch_readiness(batch_task_id)
        if not readiness["ready"]:
            first = readiness["errors"][0]
            raise AppError(
                code=first["code"],
                status_code=409,
                debug_message=first["message"],
            )
        manifest = readiness["manifest"]
        source_hash = readiness["source_hash"]
        assert manifest is not None and source_hash is not None
        existing = self.repository.find_same_evaluation(
            batch_task_id=batch_task_id,
            source_hash=source_hash,
            metric_version=METRIC_VERSION,
        )
        if existing is not None:
            if existing.status == ConsistencyEvaluationStatus.FAILED:
                return self.repository.reset_failed_task(existing.id)
            return existing
        return self.repository.create_task(
            batch_task_id=batch_task_id,
            script_task_id=int(manifest["script_task_id"]),
            source_hash=source_hash,
            thresholds=manifest["thresholds"],
            manifest=manifest,
            metric_version=METRIC_VERSION,
        )

    def get_task(self, task_id: int) -> ConsistencyEvaluationTask:
        task = self.repository.get_task(task_id)
        if task is None:
            raise AppError(
                code="consistency.task_not_found",
                status_code=404,
                debug_message=f"ConsistencyEvaluationTask not found: {task_id}",
            )
        return task

    def run_task(self, task_id: int) -> ConsistencyEvaluationTask:
        """在后台串行 worker 中执行；所有终态都会注销心跳。"""

        task = self.get_task(task_id)
        if task.status == ConsistencyEvaluationStatus.SUCCEEDED:
            return task
        running_task_registry.register(
            RuntimeTaskType.CONSISTENCY_EVALUATION_TASK, task.id
        )
        try:
            self.repository.update_task(
                task_id=task.id,
                status=ConsistencyEvaluationStatus.WAITING_RESOURCE,
                progress={"phase": "waiting_comfyui", "completed": 0},
            )
            comfy_result = self._wait_and_release_comfyui(
                task.id,
                batch_task_id=task.batch_task_id,
            )
            self.repository.update_task(
                task_id=task.id,
                status=ConsistencyEvaluationStatus.RUNNING,
                progress={
                    "phase": "vistorybench",
                    "completed": 0,
                    "comfyui": comfy_result,
                },
            )
            task = self.get_task(task.id)
            manifest = json.loads(task.manifest_json)
            attempt = int(time.time() * 1000)
            work_dir = (
                self.output_dir
                / "consistency_evaluations"
                / f"task-{task.id}"
                / f"attempt-{attempt}"
            )
            result = self.process_runner.run(manifest=manifest, work_dir=work_dir)
            if result.get("metric_version") != task.metric_version:
                raise RuntimeError(
                    "ViStoryBench worker metric version does not match task snapshot"
                )
            result_by_candidate = {
                int(item["candidate_index"]): item for item in result["tracks"]
            }
            thresholds = json.loads(task.thresholds_json)
            for index, track in enumerate(task.tracks, start=1):
                raw = result_by_candidate.get(track.candidate_index)
                if raw is None:
                    self.repository.update_track(
                        track_id=track.id,
                        status=ConsistencyTrackStatus.ERROR,
                        error_code="consistency.worker_result_missing",
                        error_message="Worker result is missing this candidate track.",
                    )
                else:
                    status, checks = self._gate_track(raw, thresholds)
                    details = dict(raw.get("details") or {})
                    # 基准溯源以数据库中的不可变任务快照为准，不信任 worker 回传路径。
                    details["reference_baseline"] = manifest.get(
                        "reference_baseline", {}
                    )
                    details["applicability"] = raw.get("applicability") or {}
                    details["checks"] = checks
                    self.repository.update_track(
                        track_id=track.id,
                        status=status,
                        metrics=raw.get("metrics") or {},
                        details=details,
                    )
                self.repository.update_task(
                    task_id=task.id,
                    progress={
                        "phase": "vistorybench",
                        "completed": index,
                        "total": len(task.tracks),
                        "comfyui": comfy_result,
                    },
                )
            return self.repository.update_task(
                task_id=task.id,
                status=ConsistencyEvaluationStatus.SUCCEEDED,
                progress={
                    "phase": "complete",
                    "completed": len(task.tracks),
                    "total": len(task.tracks),
                    "comfyui": comfy_result,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 必须持久化外部评估失败
            code = (
                exc.code
                if isinstance(exc, AppError)
                else "consistency.evaluation_failed"
            )
            return self.repository.update_task(
                task_id=task.id,
                status=ConsistencyEvaluationStatus.FAILED,
                progress={"phase": "failed"},
                error_code=code,
                error_message=str(exc),
            )
        finally:
            running_task_registry.unregister(
                RuntimeTaskType.CONSISTENCY_EVALUATION_TASK,
                task.id,
            )

    def adopt_track(self, track_id: int) -> ConsistencyEvaluationTrack:
        track = self.repository.get_track(track_id)
        if track is None:
            raise AppError(
                code="consistency.track_not_found",
                status_code=404,
                debug_message=f"ConsistencyEvaluationTrack not found: {track_id}",
            )
        if (
            track.status not in {ConsistencyTrackStatus.PASSED, ConsistencyTrackStatus.FAILED}
            or track.task.status != ConsistencyEvaluationStatus.SUCCEEDED
        ):
            raise AppError(
                code="consistency.track_not_ready",
                status_code=409,
                debug_message=f"Consistency track has not been evaluated: {track_id}",
            )
        current = self.batch_readiness(track.task.batch_task_id, include_runtime=False)
        if not current["ready"] or current["source_hash"] != track.task.source_hash:
            raise AppError(
                code="consistency.result_stale",
                status_code=409,
                debug_message=f"Consistency result is stale: {track_id}",
            )
        return self.repository.adopt_track(track_id)

    def script_gate(self, script_task_id: int) -> dict[str, Any]:
        """兼容历史准出查询；完成条件只看人工选图，不依赖评测分数。"""

        script_task = self.comic_repository.get_script_task(script_task_id)
        if script_task is None:
            raise AppError(
                code="consistency.script_task_not_found",
                status_code=404,
                debug_message=f"ScriptGenerationTask not found: {script_task_id}",
            )
        pages = self.comic_repository.list_script_task_pages(script_task_id)
        return {
            "passed": (
                {page.page_no for page in pages} == set(range(1, script_task.total_pages + 1))
                and bool(pages)
                and all(page.selected_image_id is not None for page in pages)
            ),
            "script_task_id": script_task_id,
            "batch_task_id": None,
            "evaluation_task_id": None,
            "track_id": None,
            "candidate_index": None,
            "source_hash": None,
        }

    def _build_manifest(
        self,
        batch_task_id: int,
        *,
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        batch = self.comic_repository.get_generation_batch(batch_task_id)
        if batch is None:
            errors.append(
                self._issue(
                    "consistency.batch_not_found", "Generation batch not found."
                )
            )
            return None
        if batch.script_task_id is None:
            errors.append(
                self._issue(
                    "consistency.batch_legacy",
                    "Legacy batch has no script-task identity.",
                )
            )
            return None
        if batch.status != GenerationTaskStatus.SUCCEEDED:
            errors.append(
                self._issue(
                    "consistency.batch_not_complete",
                    "Generation batch is not complete.",
                )
            )
        script_task = self.comic_repository.get_script_task(batch.script_task_id)
        if script_task is None:
            errors.append(
                self._issue(
                    "consistency.script_task_not_found", "Script task not found."
                )
            )
            return None
        pages = self.comic_repository.list_script_task_pages(script_task.id)
        expected_page_nos = set(range(1, script_task.total_pages + 1))
        actual_page_nos = {page.page_no for page in pages}
        if actual_page_nos != expected_page_nos:
            errors.append(
                self._issue(
                    "consistency.script_pages_incomplete",
                    "Script task does not contain the complete page range.",
                    missing_pages=sorted(expected_page_nos - actual_page_nos),
                )
            )
        runs = [
            run
            for run in self.generation_repository.list_batch_runs(batch.id)
            if run.status == GenerationRunStatus.SUCCEEDED
        ]
        latest_runs: dict[tuple[int, int], GenerationRun] = {}
        for run in runs:
            latest_runs[(run.candidate_index, run.page_id)] = run
        tracks: list[dict[str, Any]] = []
        incomplete_tracks: list[dict[str, Any]] = []
        for candidate_index in range(1, batch.candidate_count + 1):
            images: list[dict[str, Any]] = []
            missing_pages: list[int] = []
            for page in pages:
                run = latest_runs.get((candidate_index, page.id))
                image = self._primary_image(run) if run else None
                if image is None:
                    missing_pages.append(page.page_no)
                    continue
                path = self._validate_local_image(
                    image.local_path,
                    expected_sha=image.sha256,
                    issue_prefix="generated",
                    identifier=image.id,
                    errors=errors,
                )
                if path is None:
                    missing_pages.append(page.page_no)
                    continue
                images.append(
                    {
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "image_id": image.id,
                        "generation_run_id": run.id,
                        "path": str(path),
                        "sha256": self._sha256_file(path),
                    }
                )
            if missing_pages:
                incomplete_tracks.append(
                    {"candidate_index": candidate_index, "missing_pages": missing_pages}
                )
            else:
                tracks.append({"candidate_index": candidate_index, "images": images})
        if not tracks:
            errors.append(
                self._issue(
                    "consistency.no_complete_track",
                    "No candidate track covers every script page.",
                    incomplete_tracks=incomplete_tracks,
                )
            )

        character_by_id: dict[int, OutlineCharacter] = {}
        page_character_ids: dict[int, list[int]] = defaultdict(list)
        for page in pages:
            for script_character in page.visual_characters:
                outline_character = script_character.outline_character
                if outline_character is None:
                    errors.append(
                        self._issue(
                            "consistency.character_binding_missing",
                            "Page character cannot be traced to an outline character.",
                            page_no=page.page_no,
                            script_character_id=script_character.id,
                        )
                    )
                    continue
                character_by_id[outline_character.id] = outline_character
                if outline_character.id not in page_character_ids[page.id]:
                    page_character_ids[page.id].append(outline_character.id)
        if not character_by_id:
            errors.append(
                self._issue(
                    "consistency.characters_missing",
                    "The script task has no structured character bindings.",
                )
            )
        assets = self.repository.list_approved_identity_assets(
            project_id=script_task.project_id,
            outline_character_ids=set(character_by_id),
        )
        assets_by_character: dict[int, list[Any]] = defaultdict(list)
        for asset in assets:
            # 在清单层再检查一次，避免自定义 Repository 或历史数据把背面图交给人脸指标。
            if asset.entity_id is not None and asset.role in FACE_VISIBLE_IDENTITY_ASSET_ROLES:
                assets_by_character[asset.entity_id].append(asset)
        characters: list[dict[str, Any]] = []
        baseline_characters: list[dict[str, Any]] = []
        character_key_by_id: dict[int, str] = {}
        for character_id, character in sorted(character_by_id.items()):
            references: list[dict[str, Any]] = []
            for asset in assets_by_character.get(character_id, []):
                path = self._validate_local_image(
                    asset.local_path,
                    expected_sha=asset.sha256,
                    issue_prefix="reference",
                    identifier=asset.id,
                    errors=errors,
                )
                if path is not None:
                    references.append(
                        {
                            "asset_id": asset.id,
                            "path": str(path),
                            "sha256": self._sha256_file(path),
                            "role": asset.role.value,
                            "version": asset.version,
                        }
                    )
            if not references:
                errors.append(
                    self._issue(
                        "consistency.reference_missing",
                        "An on-stage character has no approved local face-visible identity reference.",
                        character_id=character.id,
                        character_name=character.name,
                    )
                )
            key = f"char_{character.id}"
            character_key_by_id[character.id] = key
            characters.append(
                {
                    "id": character.id,
                    "key": key,
                    "name": character.name or character.character_key,
                    "visual_type": character.visual_type.value,
                    "vistorybench_tag": self._vistorybench_tag(
                        character.visual_type.value
                    ),
                    "prompt": character.appearance,
                    "references": references,
                }
            )
            baseline_characters.append(
                {
                    "character_id": character.id,
                    "character_key": key,
                    "character_name": character.name or character.character_key,
                    "reference_count": len(references),
                    "references": [
                        {
                            "asset_id": reference["asset_id"],
                            "role": reference["role"],
                            "version": reference["version"],
                            "sha256": reference["sha256"],
                        }
                        for reference in references
                    ],
                }
            )
        page_payloads = [
            {
                "page_id": page.id,
                "page_no": page.page_no,
                "summary": page.summary or "",
                "scene": page.scene or "",
                "composition": page.composition or "",
                "description": "\n".join(
                    value
                    for value in (page.character_action, page.dialogue, page.clothing)
                    if value
                ),
                "character_keys": [
                    character_key_by_id[character_id]
                    for character_id in page_character_ids.get(page.id, [])
                    if character_id in character_key_by_id
                ],
            }
            for page in pages
        ]
        config = self.repository.get_config()
        thresholds = {
            field: float(getattr(config, field)) for field in THRESHOLD_FIELDS
        }
        if errors:
            return None
        reference_baseline = {
            "mode": REFERENCE_BASELINE_MODE,
            "reference_count": sum(
                item["reference_count"] for item in baseline_characters
            ),
            "characters": baseline_characters,
        }
        return {
            "schema_version": 2,
            "metric_version": METRIC_VERSION,
            "project_id": script_task.project_id,
            "script_task_id": script_task.id,
            "batch_task_id": batch.id,
            "thresholds": thresholds,
            "pages": page_payloads,
            "characters": characters,
            "reference_baseline": reference_baseline,
            "tracks": tracks,
            "incomplete_tracks": incomplete_tracks,
        }

    def _comfy_client_for_batch(self, batch_task_id: int) -> ComfyUIClient:
        """优先释放该批次实际使用的 ComfyUI；测试注入始终保持最高优先级。"""

        if self._comfy_client_override is not None:
            return self._comfy_client_override
        batch = self.comic_repository.get_generation_batch(batch_task_id)
        if batch is not None and batch.tool_preset_id is not None:
            preset = self.comic_repository.get_image_generation_tool_preset(
                batch.tool_preset_id
            )
            if (
                preset is not None
                and preset.provider == ImageGenerationProvider.COMFYUI
                and (preset.comfy_base_url or "").strip()
            ):
                return ComfyUIClient(preset.comfy_base_url or "")
        return self.comfy_client

    def _wait_and_release_comfyui(
        self,
        task_id: int,
        *,
        batch_task_id: int,
    ) -> dict[str, Any]:
        timeout_seconds = float(os.getenv("CONSISTENCY_COMFYUI_WAIT_TIMEOUT", "1800"))
        started = time.monotonic()
        reachable = False
        comfy_client = self._comfy_client_for_batch(batch_task_id)
        while True:
            try:
                queue = comfy_client.get_queue()
                reachable = True
            except Exception as exc:  # noqa: BLE001 - 未运行 ComfyUI 时可依赖 CUDA readiness 继续
                return {"reachable": False, "released": False, "detail": str(exc)[:500]}
            if comfy_client.queue_is_idle(queue):
                break
            if time.monotonic() - started >= timeout_seconds:
                raise AppError(
                    code="consistency.comfyui_busy_timeout",
                    status_code=409,
                    debug_message="Timed out waiting for the ComfyUI queue to become idle.",
                )
            self.repository.update_task(
                task_id=task_id,
                progress={"phase": "waiting_comfyui", "completed": 0},
            )
            time.sleep(2)
        comfy_client.free_memory(unload_models=True)
        return {"reachable": reachable, "released": True}

    @staticmethod
    def _gate_track(
        raw: dict[str, Any],
        thresholds: dict[str, float],
    ) -> tuple[ConsistencyTrackStatus, dict[str, Any]]:
        metrics = raw.get("metrics") or {}
        applicability = raw.get("applicability") or {}
        rules = {
            "cids_cross": ("min", thresholds["cids_cross_min"]),
            "cids_self": ("min", thresholds["cids_self_min"]),
            "csd_cross": ("min", thresholds["csd_cross_min"]),
            "csd_self": ("min", thresholds["csd_self_min"]),
            "occm": ("min", thresholds["occm_min"]),
            "copy_paste": ("max", thresholds["copy_paste_max"]),
        }
        checks: dict[str, Any] = {}
        invalid = False
        passed = True
        for metric, (operator, threshold) in rules.items():
            applicable = applicability.get(metric, True) is not False
            value = metrics.get(metric)
            if not applicable:
                checks[metric] = {
                    "applicable": False,
                    "passed": True,
                    "value": None,
                    "operator": operator,
                    "threshold": threshold,
                }
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                invalid = True
                metric_passed = False
            else:
                metric_passed = (
                    float(value) >= threshold
                    if operator == "min"
                    else float(value) <= threshold
                )
            passed = passed and metric_passed
            checks[metric] = {
                "applicable": True,
                "passed": metric_passed,
                "value": value,
                "operator": operator,
                "threshold": threshold,
            }
        if invalid:
            return ConsistencyTrackStatus.ERROR, checks
        return (
            ConsistencyTrackStatus.PASSED if passed else ConsistencyTrackStatus.FAILED,
            checks,
        )

    @staticmethod
    def _primary_image(run: GenerationRun | None) -> ComicImage | None:
        if run is None:
            return None
        return next(
            (
                image
                for image in sorted(run.images, key=lambda item: item.id)
                if image.artifact_index == 1
            ),
            None,
        )

    def _validate_local_image(
        self,
        value: str | None,
        *,
        expected_sha: str | None,
        issue_prefix: str,
        identifier: int,
        errors: list[dict[str, Any]],
    ) -> Path | None:
        if not value:
            errors.append(
                self._issue(
                    f"consistency.{issue_prefix}_file_missing",
                    "A required local image path is missing.",
                    id=identifier,
                )
            )
            return None
        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if not path.is_file():
            errors.append(
                self._issue(
                    f"consistency.{issue_prefix}_file_missing",
                    "A required local image file does not exist.",
                    id=identifier,
                    path=str(path),
                )
            )
            return None
        actual_sha = self._sha256_file(path)
        if expected_sha and actual_sha.lower() != expected_sha.lower():
            errors.append(
                self._issue(
                    f"consistency.{issue_prefix}_hash_mismatch",
                    "A required image changed after it was registered.",
                    id=identifier,
                )
            )
            return None
        return path

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _vistorybench_tag(visual_type: str) -> str:
        return {
            "realistic_human": "realistic_human",
            "stylized_human": "unrealistic_human",
            "non_human": "non_human",
        }[visual_type]

    @staticmethod
    def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
        return {"code": code, "message": message, "details": details}
