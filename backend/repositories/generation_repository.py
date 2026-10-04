from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from backend.models.comic import (
    ComicImage,
    GenerationRun,
    ImageGenerationToolPreset,
    ImageSpec,
    VisualStateSnapshot,
)
from backend.models.enums import (
    GenerationMode,
    GenerationRunStatus,
    ImageGenerationProvider,
    ImagePromptType,
    SeedStrategy,
)
from backend.models.time import utc_now


class GenerationRepository:
    """结构化出图与单候选 GenerationRun 的数据访问层。"""

    def __init__(self, session: Session):
        self.session = session

    def get_tool_preset(self, preset_id: int) -> ImageGenerationToolPreset | None:
        return self.session.get(ImageGenerationToolPreset, preset_id)

    def latest_spec_for_page(
        self,
        *,
        page_id: int,
        prompt_type: ImagePromptType,
        generation_mode: GenerationMode,
    ) -> ImageSpec | None:
        statement = select(ImageSpec).where(
            ImageSpec.page_id == page_id,
            ImageSpec.generation_mode == generation_mode,
        )
        statement = statement.where(ImageSpec.prompt_type == prompt_type)
        return self.session.scalar(
            statement
            .options(
                selectinload(ImageSpec.snapshot).selectinload(
                    VisualStateSnapshot.compilation
                ),
                selectinload(ImageSpec.shot_plan),
            )
            .order_by(ImageSpec.id.desc())
            .limit(1)
        )

    def create_run(
        self,
        *,
        generation_task_id: int,
        batch_task_id: int | None,
        page_id: int,
        image_spec_id: int,
        tool_preset_id: int,
        provider: ImageGenerationProvider,
        prompt_type: ImagePromptType,
        candidate_index: int,
        seed: int,
        seed_strategy: SeedStrategy,
        generation_mode: GenerationMode,
        bindings_json: str,
        resolved_assets_json: str,
        degradation_json: str,
        applied_spec_json: str,
    ) -> GenerationRun:
        run = GenerationRun(
            generation_task_id=generation_task_id,
            batch_task_id=batch_task_id,
            page_id=page_id,
            image_spec_id=image_spec_id,
            tool_preset_id=tool_preset_id,
            provider=provider,
            prompt_type=prompt_type,
            candidate_index=candidate_index,
            seed=seed,
            seed_strategy=seed_strategy,
            generation_mode=generation_mode,
            status=GenerationRunStatus.PENDING,
            bindings_json=bindings_json,
            resolved_assets_json=resolved_assets_json,
            degradation_json=degradation_json,
            applied_spec_json=applied_spec_json,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def update_run(
        self,
        *,
        run_id: int,
        status: GenerationRunStatus | None = None,
        external_request_id: str | None = None,
        seed_applied: bool | None = None,
        workflow_json: str | None = None,
        workflow_hash: str | None = None,
        degradation_json: str | None = None,
        applied_spec_json: str | None = None,
        resolved_assets_json: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> GenerationRun:
        run = self.session.get(GenerationRun, run_id)
        if run is None:
            raise ValueError(f"GenerationRun not found: {run_id}")
        if status in {GenerationRunStatus.QUEUED, GenerationRunStatus.RUNNING, GenerationRunStatus.SUCCEEDED}:
            # 原请求超时后可能通过 Provider 历史恢复成功，不能继续展示旧失败状态。
            run.error_code = None
            run.error_message = None
            if status != GenerationRunStatus.SUCCEEDED:
                run.finished_at = None
        for field_name, value in {
            "status": status,
            "external_request_id": external_request_id,
            "seed_applied": seed_applied,
            "workflow_json": workflow_json,
            "workflow_hash": workflow_hash,
            "degradation_json": degradation_json,
            "applied_spec_json": applied_spec_json,
            "resolved_assets_json": resolved_assets_json,
            "error_code": error_code,
            "error_message": error_message,
        }.items():
            if value is not None:
                setattr(run, field_name, value)
        if status in {GenerationRunStatus.SUCCEEDED, GenerationRunStatus.FAILED}:
            run.finished_at = utc_now()
        self.session.commit()
        self.session.refresh(run)
        return run

    def add_image(
        self,
        *,
        run_id: int,
        page_id: int,
        local_path: str,
        seed: int,
        workflow_name: str,
        prompt: str,
        negative_prompt: str,
        sha256: str,
        width: int | None,
        height: int | None,
        artifact_index: int = 1,
    ) -> ComicImage:
        image = ComicImage(
            generation_run_id=run_id,
            artifact_index=artifact_index,
            page_id=page_id,
            local_path=local_path,
            seed=seed,
            workflow_name=workflow_name,
            prompt=prompt,
            negative_prompt=negative_prompt,
            sha256=sha256,
            width=width,
            height=height,
        )
        self.session.add(image)
        self.session.commit()
        self.session.refresh(image)
        return image

    def get_run(self, run_id: int) -> GenerationRun | None:
        return self.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == run_id)
            .options(
                selectinload(GenerationRun.images),
                selectinload(GenerationRun.image_spec),
                selectinload(GenerationRun.tool_preset),
            )
        )

    def list_successful_runs(
        self,
        *,
        page_id: int,
        prompt_type: ImagePromptType,
        generation_mode: GenerationMode,
        image_spec_id: int,
        batch_task_id: int | None = None,
    ) -> list[GenerationRun]:
        statement = select(GenerationRun).where(
            GenerationRun.page_id == page_id,
            GenerationRun.prompt_type == prompt_type,
            GenerationRun.generation_mode == generation_mode,
            GenerationRun.image_spec_id == image_spec_id,
            GenerationRun.status == GenerationRunStatus.SUCCEEDED,
        )
        if batch_task_id is not None:
            statement = statement.where(GenerationRun.batch_task_id == batch_task_id)
        return list(
            self.session.scalars(
                statement.order_by(GenerationRun.created_at, GenerationRun.id)
            )
        )

    def list_batch_runs(self, batch_task_id: int) -> list[GenerationRun]:
        """读取一个明确批次中的全部候选运行，不混入其它生成历史。"""

        return list(
            self.session.scalars(
                select(GenerationRun)
                .where(GenerationRun.batch_task_id == batch_task_id)
                .options(selectinload(GenerationRun.images))
                .order_by(
                    GenerationRun.candidate_index,
                    GenerationRun.page_id,
                    GenerationRun.id,
                )
            )
        )

    def batch_progress(self, batch_task_ids: list[int]) -> dict[int, dict[str, int | None]]:
        """两次分组查询读取进度；恢复包装子任务不会被算成额外候选。"""

        result = {
            batch_id: {"completed_candidates": 0, "images_count": 0, "latest_image_id": None, "active_runs": 0}
            for batch_id in batch_task_ids
        }
        if not result:
            return result
        # 同一候选可有失败重试、多个成功历史或多个输出，完成数按页/候选去重，
        # 实际图片数仍保留所有已落库产物；无图片的 succeeded run 不算已完成。
        candidates = (
            select(
                GenerationRun.batch_task_id.label("batch_id"),
                GenerationRun.page_id,
                GenerationRun.candidate_index,
                func.count(ComicImage.id).label("images_count"),
                func.max(ComicImage.id).label("latest_image_id"),
                func.max(case((GenerationRun.status == GenerationRunStatus.SUCCEEDED, 1), else_=0)).label("completed"),
            )
            .join(ComicImage, ComicImage.generation_run_id == GenerationRun.id)
            .where(GenerationRun.batch_task_id.in_(batch_task_ids))
            .group_by(GenerationRun.batch_task_id, GenerationRun.page_id, GenerationRun.candidate_index)
            .subquery()
        )
        for batch_id, completed, images_count, latest_image_id in self.session.execute(
            select(
                candidates.c.batch_id, func.sum(candidates.c.completed),
                func.sum(candidates.c.images_count), func.max(candidates.c.latest_image_id),
            ).group_by(candidates.c.batch_id)
        ):
            result[batch_id].update(completed_candidates=int(completed), images_count=int(images_count), latest_image_id=latest_image_id)
        for batch_id, active in self.session.execute(
            select(GenerationRun.batch_task_id, func.count(GenerationRun.id))
            .where(
                GenerationRun.batch_task_id.in_(batch_task_ids),
                GenerationRun.status.in_([GenerationRunStatus.PENDING, GenerationRunStatus.QUEUED, GenerationRunStatus.RUNNING]),
            )
            .group_by(GenerationRun.batch_task_id)
        ):
            # 批次暂停不代表当前外部请求终止，不能用 parent/child 心跳过滤掉它。
            result[batch_id]["active_runs"] = int(active)
        return result
