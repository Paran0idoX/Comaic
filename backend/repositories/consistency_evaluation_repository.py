"""一致性评估配置、任务、轨道结果和一键采用的数据访问层。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.models.comic import (
    ComicImage,
    ComicPage,
    ConsistencyEvaluationConfig,
    ConsistencyEvaluationTask,
    ConsistencyEvaluationTrack,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
    ComicPageStatus,
    ConsistencyEvaluationStatus,
    ConsistencyTrackStatus,
    VisualAssetRole,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.models.time import utc_now
from backend.utils.json_utils import canonical_json


# 人脸身份编码只能使用有机会显示脸部的视角；背面图仍供生图选图使用。
FACE_VISIBLE_IDENTITY_ASSET_ROLES = (
    VisualAssetRole.IDENTITY_FACE,
    VisualAssetRole.IDENTITY_HALF_BODY,
    VisualAssetRole.IDENTITY_FULL_BODY,
    VisualAssetRole.IDENTITY_SIDE,
)
IDENTITY_ASSET_ROLES = FACE_VISIBLE_IDENTITY_ASSET_ROLES


class ConsistencyEvaluationRepository:
    """只负责一致性评估相关数据库读写，不调用模型或 ComfyUI。"""

    def __init__(self, session: Session):
        self.session = session

    def get_config(self) -> ConsistencyEvaluationConfig:
        config = self.session.get(ConsistencyEvaluationConfig, 1)
        if config is None:
            config = ConsistencyEvaluationConfig(id=1)
            self.session.add(config)
            self.session.commit()
            self.session.refresh(config)
        return config

    def update_config(self, **values: float) -> ConsistencyEvaluationConfig:
        config = self.get_config()
        for field_name, value in values.items():
            setattr(config, field_name, float(value))
        self.session.commit()
        self.session.refresh(config)
        return config

    def list_approved_identity_assets(
        self,
        *,
        project_id: int,
        outline_character_ids: set[int],
    ) -> list[VisualAsset]:
        if not outline_character_ids:
            return []
        statement = (
            select(VisualAsset)
            .where(
                VisualAsset.project_id == project_id,
                VisualAsset.entity_type == VisualEntityType.CHARACTER,
                VisualAsset.entity_id.in_(outline_character_ids),
                VisualAsset.role.in_(IDENTITY_ASSET_ROLES),
                VisualAsset.status == ApprovalStatus.APPROVED,
                VisualAsset.storage_kind == VisualAssetStorageKind.LOCAL_FILE,
            )
            .order_by(VisualAsset.entity_id, VisualAsset.version, VisualAsset.id)
        )
        return list(self.session.scalars(statement))

    def find_same_evaluation(
        self,
        *,
        batch_task_id: int,
        source_hash: str,
        metric_version: str,
    ) -> ConsistencyEvaluationTask | None:
        statement = (
            select(ConsistencyEvaluationTask)
            .where(
                ConsistencyEvaluationTask.batch_task_id == batch_task_id,
                ConsistencyEvaluationTask.source_hash == source_hash,
                ConsistencyEvaluationTask.metric_version == metric_version,
            )
            .options(selectinload(ConsistencyEvaluationTask.tracks))
            .order_by(ConsistencyEvaluationTask.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_task(
        self,
        *,
        batch_task_id: int,
        script_task_id: int,
        source_hash: str,
        thresholds: dict[str, float],
        manifest: dict[str, Any],
        metric_version: str,
    ) -> ConsistencyEvaluationTask:
        task = ConsistencyEvaluationTask(
            batch_task_id=batch_task_id,
            script_task_id=script_task_id,
            status=ConsistencyEvaluationStatus.PENDING,
            source_hash=source_hash,
            thresholds_json=canonical_json(thresholds),
            manifest_json=canonical_json(manifest),
            metric_version=metric_version,
            progress_json=canonical_json({"phase": "pending", "completed": 0}),
        )
        try:
            self.session.add(task)
            self.session.flush()
            for track in manifest["tracks"]:
                self.session.add(
                    ConsistencyEvaluationTrack(
                        evaluation_task_id=task.id,
                        candidate_index=int(track["candidate_index"]),
                        status=ConsistencyTrackStatus.PENDING,
                        image_ids_json=canonical_json(
                            {
                                str(image["page_id"]): image["image_id"]
                                for image in track["images"]
                            }
                        ),
                    )
                )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.find_same_evaluation(
                batch_task_id=batch_task_id,
                source_hash=source_hash,
                metric_version=metric_version,
            )
            if existing is not None:
                return existing
            raise
        return self.get_task(task.id)  # type: ignore[return-value]

    def get_task(self, task_id: int) -> ConsistencyEvaluationTask | None:
        statement = (
            select(ConsistencyEvaluationTask)
            .where(ConsistencyEvaluationTask.id == task_id)
            .options(selectinload(ConsistencyEvaluationTask.tracks))
        )
        return self.session.scalar(statement)

    def reset_failed_task(self, task_id: int) -> ConsistencyEvaluationTask:
        """同一输入快照失败后复用任务记录重试，保持并发幂等唯一约束。"""

        task = self.session.get(ConsistencyEvaluationTask, task_id)
        if task is None:
            raise ValueError(f"ConsistencyEvaluationTask not found: {task_id}")
        if task.status != ConsistencyEvaluationStatus.FAILED:
            return self.get_task(task_id)  # type: ignore[return-value]
        task.status = ConsistencyEvaluationStatus.PENDING
        task.progress_json = canonical_json({"phase": "pending", "completed": 0})
        task.error_code = None
        task.error_message = None
        task.heartbeat_at = None
        task.finished_at = None
        for track in task.tracks:
            track.status = ConsistencyTrackStatus.PENDING
            track.passed = False
            track.metrics_json = "{}"
            track.details_json = "{}"
            track.error_code = None
            track.error_message = None
            track.adopted_at = None
        self.session.commit()
        return self.get_task(task_id)  # type: ignore[return-value]

    def list_batch_tasks(self, batch_task_id: int) -> list[ConsistencyEvaluationTask]:
        statement = (
            select(ConsistencyEvaluationTask)
            .where(ConsistencyEvaluationTask.batch_task_id == batch_task_id)
            .options(selectinload(ConsistencyEvaluationTask.tracks))
            .order_by(ConsistencyEvaluationTask.id.desc())
        )
        return list(self.session.scalars(statement))

    def get_track(self, track_id: int) -> ConsistencyEvaluationTrack | None:
        statement = (
            select(ConsistencyEvaluationTrack)
            .where(ConsistencyEvaluationTrack.id == track_id)
            .options(selectinload(ConsistencyEvaluationTrack.task))
        )
        return self.session.scalar(statement)

    def update_task(
        self,
        *,
        task_id: int,
        status: ConsistencyEvaluationStatus | None = None,
        progress: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        heartbeat_at: datetime | None = None,
    ) -> ConsistencyEvaluationTask:
        task = self.session.get(ConsistencyEvaluationTask, task_id)
        if task is None:
            raise ValueError(f"ConsistencyEvaluationTask not found: {task_id}")
        if status is not None:
            task.status = status
            if status in {
                ConsistencyEvaluationStatus.WAITING_RESOURCE,
                ConsistencyEvaluationStatus.RUNNING,
            }:
                task.heartbeat_at = heartbeat_at or utc_now()
                task.finished_at = None
                task.error_code = None
                task.error_message = None
            if status in {
                ConsistencyEvaluationStatus.SUCCEEDED,
                ConsistencyEvaluationStatus.FAILED,
                ConsistencyEvaluationStatus.SUSPENDED,
            }:
                task.finished_at = utc_now()
        if progress is not None:
            task.progress_json = canonical_json(progress)
        if error_code is not None:
            task.error_code = error_code
        if error_message is not None:
            task.error_message = error_message
        if heartbeat_at is not None:
            task.heartbeat_at = heartbeat_at
        self.session.commit()
        return self.get_task(task_id)  # type: ignore[return-value]

    def update_track(
        self,
        *,
        track_id: int,
        status: ConsistencyTrackStatus,
        metrics: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ConsistencyEvaluationTrack:
        track = self.session.get(ConsistencyEvaluationTrack, track_id)
        if track is None:
            raise ValueError(f"ConsistencyEvaluationTrack not found: {track_id}")
        track.status = status
        track.passed = status == ConsistencyTrackStatus.PASSED
        if metrics is not None:
            track.metrics_json = canonical_json(metrics)
        if details is not None:
            track.details_json = canonical_json(details)
        track.error_code = error_code
        track.error_message = error_message
        self.session.commit()
        self.session.refresh(track)
        return track

    def adopt_track(self, track_id: int) -> ConsistencyEvaluationTrack:
        """事务性采用整条轨道；任一图片不匹配时整次操作回滚。"""

        track = self.get_track(track_id)
        if track is None:
            raise ValueError(f"ConsistencyEvaluationTrack not found: {track_id}")
        if not track.passed or track.status != ConsistencyTrackStatus.PASSED:
            raise ValueError(f"Consistency track has not passed: {track_id}")
        image_ids = json.loads(track.image_ids_json)
        try:
            for raw_page_id, image_id in image_ids.items():
                page_id = int(raw_page_id)
                page = self.session.get(ComicPage, page_id)
                image = self.session.get(ComicImage, int(image_id))
                if page is None or image is None or image.page_id != page_id:
                    raise ValueError(
                        f"Consistency track image does not belong to page {page_id}: {image_id}"
                    )
                for candidate in page.images:
                    candidate.is_selected = candidate.id == image.id
                page.selected_image_id = image.id
                page.status = ComicPageStatus.IMAGE_SELECTED
            track.adopted_at = utc_now()
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(track)
        return track

    def update_running_heartbeats(
        self,
        *,
        task_ids: set[int],
        heartbeat_at: datetime,
    ) -> int:
        if not task_ids:
            return 0
        result = self.session.execute(
            update(ConsistencyEvaluationTask)
            .where(
                ConsistencyEvaluationTask.id.in_(task_ids),
                ConsistencyEvaluationTask.status.in_(
                    (
                        ConsistencyEvaluationStatus.WAITING_RESOURCE,
                        ConsistencyEvaluationStatus.RUNNING,
                    )
                ),
            )
            .values(heartbeat_at=heartbeat_at)
        )
        self.session.commit()
        return int(result.rowcount or 0)

    def suspend_stale_tasks(self, *, stale_before: datetime, error_message: str) -> int:
        result = self.session.execute(
            update(ConsistencyEvaluationTask)
            .where(
                ConsistencyEvaluationTask.status.in_(
                    (
                        ConsistencyEvaluationStatus.WAITING_RESOURCE,
                        ConsistencyEvaluationStatus.RUNNING,
                    )
                ),
                ConsistencyEvaluationTask.heartbeat_at.is_not(None),
                ConsistencyEvaluationTask.heartbeat_at < stale_before,
            )
            .values(
                status=ConsistencyEvaluationStatus.SUSPENDED,
                error_code="consistency.runtime_interrupted",
                error_message=error_message,
                finished_at=utc_now(),
            )
        )
        self.session.commit()
        return int(result.rowcount or 0)
