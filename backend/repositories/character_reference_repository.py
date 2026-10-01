"""人物参考图任务的数据访问层；不调用 Renderer 或业务 Service。"""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from backend.models.comic import (
    CharacterReferenceGenerationRun,
    CharacterReferenceGenerationTask,
    CharacterReferenceImage,
    ComicProject,
    ImageGenerationToolPreset,
    OutlineCharacter,
    OutlineVersion,
    StyleProfile,
)
from backend.models.enums import (
    ApprovalStatus,
    GenerationRunStatus,
    GenerationTaskStatus,
    OutlineVersionStatus,
    VisualAssetRole,
    VisualEntityType,
)
from backend.models.time import utc_now
from backend.utils.json_utils import canonical_json


REFERENCE_ROLES = (
    VisualAssetRole.IDENTITY_FACE,
    VisualAssetRole.IDENTITY_HALF_BODY,
    VisualAssetRole.IDENTITY_FULL_BODY,
)


class CharacterReferenceRepository:
    """保存参考图任务、逐角色运行记录及本地产物。"""

    def __init__(self, session: Session):
        self.session = session

    def get_character(self, character_id: int) -> OutlineCharacter | None:
        return self.session.scalar(
            select(OutlineCharacter)
            .where(OutlineCharacter.id == character_id)
            .options(selectinload(OutlineCharacter.outline_version))
        )

    def get_outline_version(self, outline_version_id: int) -> OutlineVersion | None:
        return self.session.get(OutlineVersion, outline_version_id)

    def get_project(self, project_id: int) -> ComicProject | None:
        return self.session.get(ComicProject, project_id)

    def get_active_confirmed_outline_version(
        self, project_id: int
    ) -> OutlineVersion | None:
        return self.session.scalar(
            select(OutlineVersion)
            .where(
                OutlineVersion.project_id == project_id,
                OutlineVersion.status == OutlineVersionStatus.ACTIVE,
                OutlineVersion.confirmed_at.is_not(None),
            )
            .order_by(OutlineVersion.created_at.desc(), OutlineVersion.id.desc())
            .limit(1)
        )

    def list_outline_characters(
        self, outline_version_id: int
    ) -> list[OutlineCharacter]:
        return list(
            self.session.scalars(
                select(OutlineCharacter)
                .where(OutlineCharacter.outline_version_id == outline_version_id)
                .order_by(OutlineCharacter.character_key, OutlineCharacter.id)
            )
        )

    def get_style(self, style_id: int) -> StyleProfile | None:
        return self.session.get(StyleProfile, style_id)

    def get_tool(self, tool_id: int) -> ImageGenerationToolPreset | None:
        return self.session.get(ImageGenerationToolPreset, tool_id)

    def create_task(
        self,
        *,
        project_id: int,
        character_id: int | None,
        tool: ImageGenerationToolPreset,
        style_profile_id: int | None,
        candidate_count: int,
        prompts: dict[str, dict[str, str]],
        seeds: list[int],
        entity_type: VisualEntityType = VisualEntityType.CHARACTER,
        entity_id: int | None = None,
        entity_key: str | None = None,
        reference_subject_id: int | None = None,
        outfit_variant_id: int | None = None,
        roles: tuple[VisualAssetRole, ...] | None = None,
        source_asset_ids: list[int] | None = None,
        subject_snapshot: dict | None = None,
        specs: dict[str, dict] | None = None,
    ) -> CharacterReferenceGenerationTask:
        task = CharacterReferenceGenerationTask(
            project_id=project_id,
            outline_character_id=character_id,
            entity_type=entity_type,
            entity_id=entity_id if entity_id is not None else character_id,
            entity_key=entity_key,
            reference_subject_id=reference_subject_id,
            outfit_variant_id=outfit_variant_id,
            selected_roles_json=canonical_json([role.value for role in roles or REFERENCE_ROLES]),
            source_asset_ids_json=canonical_json(source_asset_ids or []),
            subject_snapshot_json=canonical_json(subject_snapshot or {}),
            tool_preset_id=tool.id,
            style_profile_id=style_profile_id,
            status=GenerationTaskStatus.PENDING,
            candidate_count=candidate_count,
            prompt_type=tool.prompt_type,
            prompt_snapshot_json=canonical_json(prompts),
            progress_json=canonical_json(
                {"completed": 0, "failed": 0, "total": candidate_count * len(roles or REFERENCE_ROLES)}
            ),
        )
        self.session.add(task)
        self.session.flush()
        for candidate_index, seed in enumerate(seeds, start=1):
            for role in roles or REFERENCE_ROLES:
                prompt = prompts[role.value]
                spec = {
                    "prompt": {
                        "positive": prompt["positive"],
                        "negative": prompt["negative"],
                    },
                    "render": {},
                    "subjects": [],
                    "scene": {},
                    "style": {},
                    "required_capabilities": ["txt2img"],
                }
                if specs is not None:
                    spec = deepcopy(specs[role.value])
                spec["render"]["seed"] = seed
                self.session.add(
                    CharacterReferenceGenerationRun(
                        task_id=task.id,
                        candidate_index=candidate_index,
                        role=role,
                        seed=seed,
                        provider=tool.provider,
                        prompt_type=tool.prompt_type,
                        positive_prompt=prompt["positive"],
                        negative_prompt=prompt["negative"],
                        status=GenerationRunStatus.PENDING,
                        review_status=ApprovalStatus.DRAFT,
                        bindings_json=tool.bindings_json,
                        degradation_json="[]",
                        applied_spec_json=canonical_json(spec),
                    )
                )
        self.session.commit()
        return self.get_task(task.id)  # type: ignore[return-value]

    def get_task(self, task_id: int) -> CharacterReferenceGenerationTask | None:
        return self.session.scalar(
            select(CharacterReferenceGenerationTask)
            .where(CharacterReferenceGenerationTask.id == task_id)
            .options(
                selectinload(CharacterReferenceGenerationTask.outline_character),
                selectinload(CharacterReferenceGenerationTask.tool_preset),
                selectinload(CharacterReferenceGenerationTask.style_profile),
                selectinload(CharacterReferenceGenerationTask.runs).selectinload(
                    CharacterReferenceGenerationRun.images
                ),
            )
        )

    def list_character_tasks(
        self, character_id: int
    ) -> list[CharacterReferenceGenerationTask]:
        statement = (
            select(CharacterReferenceGenerationTask)
            .where(
                CharacterReferenceGenerationTask.outline_character_id == character_id
            )
            .options(
                selectinload(CharacterReferenceGenerationTask.outline_character),
                selectinload(CharacterReferenceGenerationTask.tool_preset),
                selectinload(CharacterReferenceGenerationTask.style_profile),
                selectinload(CharacterReferenceGenerationTask.runs).selectinload(
                    CharacterReferenceGenerationRun.images
                ),
            )
            .order_by(
                CharacterReferenceGenerationTask.created_at.desc(),
                CharacterReferenceGenerationTask.id.desc(),
            )
        )
        return list(self.session.scalars(statement).unique())

    def list_pending_task_ids(self) -> list[int]:
        """进程重启后重新排队尚未开始的任务；失败和暂停任务仍需人工继续。"""

        return list(
            self.session.scalars(
                select(CharacterReferenceGenerationTask.id)
                .where(
                    CharacterReferenceGenerationTask.status
                    == GenerationTaskStatus.PENDING
                )
                .order_by(
                    CharacterReferenceGenerationTask.created_at,
                    CharacterReferenceGenerationTask.id,
                )
            )
        )

    def update_task(
        self,
        task_id: int,
        **values: Any,
    ) -> CharacterReferenceGenerationTask:
        task = self.session.get(CharacterReferenceGenerationTask, task_id)
        if task is None:
            raise ValueError(f"CharacterReferenceGenerationTask not found: {task_id}")
        for key, value in values.items():
            setattr(task, key, value)
        self.session.commit()
        return self.get_task(task_id)  # type: ignore[return-value]

    def update_run(
        self,
        run_id: int,
        **values: Any,
    ) -> CharacterReferenceGenerationRun:
        run = self.session.get(CharacterReferenceGenerationRun, run_id)
        if run is None:
            raise ValueError(f"CharacterReferenceGenerationRun not found: {run_id}")
        for key, value in values.items():
            setattr(run, key, value)
        self.session.commit()
        self.session.refresh(run)
        return run

    def add_image(
        self,
        *,
        run_id: int,
        artifact_index: int,
        local_path: str,
        mime_type: str | None,
        sha256: str,
        width: int | None,
        height: int | None,
    ) -> CharacterReferenceImage:
        image = CharacterReferenceImage(
            run_id=run_id,
            artifact_index=artifact_index,
            local_path=local_path,
            mime_type=mime_type,
            sha256=sha256,
            width=width,
            height=height,
        )
        self.session.add(image)
        self.session.commit()
        self.session.refresh(image)
        return image

    def get_image(self, image_id: int) -> CharacterReferenceImage | None:
        return self.session.scalar(
            select(CharacterReferenceImage)
            .where(CharacterReferenceImage.id == image_id)
            .options(
                selectinload(CharacterReferenceImage.run).selectinload(
                    CharacterReferenceGenerationRun.task
                )
            )
        )

    def update_running_heartbeats(
        self,
        *,
        task_ids: set[int],
        heartbeat_at: datetime,
    ) -> int:
        if not task_ids:
            return 0
        result = self.session.execute(
            update(CharacterReferenceGenerationTask)
            .where(
                CharacterReferenceGenerationTask.id.in_(task_ids),
                CharacterReferenceGenerationTask.status == GenerationTaskStatus.RUNNING,
            )
            .values(heartbeat_at=heartbeat_at)
        )
        self.session.commit()
        return int(result.rowcount or 0)

    def suspend_stale_tasks(
        self,
        *,
        stale_before: datetime,
        error_message: str,
    ) -> int:
        result = self.session.execute(
            update(CharacterReferenceGenerationTask)
            .where(
                CharacterReferenceGenerationTask.status == GenerationTaskStatus.RUNNING,
                CharacterReferenceGenerationTask.heartbeat_at.is_not(None),
                CharacterReferenceGenerationTask.heartbeat_at < stale_before,
            )
            .values(
                status=GenerationTaskStatus.SUSPENDED,
                error_code="character_reference.runtime_interrupted",
                error_message=error_message,
                finished_at=utc_now(),
            )
        )
        self.session.commit()
        return int(result.rowcount or 0)
