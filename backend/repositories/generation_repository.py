from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models.comic import (
    ComicImage,
    GenerationRun,
    GenerationTask,
    ImageGenerationToolPreset,
    ImageSpec,
    VisualStateSnapshot,
)
from backend.models.enums import (
    GenerationMode,
    GenerationRunStatus,
    SeedStrategy,
)
from backend.models.time import utc_now


class GenerationRepository:
    """结构化出图与单候选 GenerationRun 的数据访问层。"""

    def __init__(self, session: Session):
        self.session = session

    def get_tool_preset(self, preset_id: int) -> ImageGenerationToolPreset | None:
        return self.session.scalar(
            select(ImageGenerationToolPreset)
            .where(ImageGenerationToolPreset.id == preset_id)
            .options(selectinload(ImageGenerationToolPreset.model_profile))
        )

    def latest_spec_for_page(
        self,
        *,
        page_id: int,
        model_profile_id: int | None,
        generation_mode: GenerationMode,
    ) -> ImageSpec | None:
        statement = select(ImageSpec).where(
            ImageSpec.page_id == page_id,
            ImageSpec.generation_mode == generation_mode,
        )
        if model_profile_id is not None:
            statement = statement.where(ImageSpec.model_profile_id == model_profile_id)
        return self.session.scalar(
            statement
            .options(
                selectinload(ImageSpec.model_profile),
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
        page_id: int,
        image_spec_id: int,
        tool_preset_id: int,
        model_profile_id: int,
        candidate_index: int,
        seed: int,
        seed_strategy: SeedStrategy,
        generation_mode: GenerationMode,
        bindings_json: str,
        model_manifest_json: str,
        resolved_assets_json: str,
        render_params_json: str,
        degradation_json: str,
        applied_spec_json: str,
    ) -> GenerationRun:
        run = GenerationRun(
            generation_task_id=generation_task_id,
            page_id=page_id,
            image_spec_id=image_spec_id,
            tool_preset_id=tool_preset_id,
            model_profile_id=model_profile_id,
            candidate_index=candidate_index,
            seed=seed,
            seed_strategy=seed_strategy,
            generation_mode=generation_mode,
            status=GenerationRunStatus.PENDING,
            bindings_json=bindings_json,
            model_manifest_json=model_manifest_json,
            resolved_assets_json=resolved_assets_json,
            render_params_json=render_params_json,
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
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> GenerationRun:
        run = self.session.get(GenerationRun, run_id)
        if run is None:
            raise ValueError(f"GenerationRun not found: {run_id}")
        for field_name, value in {
            "status": status,
            "external_request_id": external_request_id,
            "seed_applied": seed_applied,
            "workflow_json": workflow_json,
            "workflow_hash": workflow_hash,
            "degradation_json": degradation_json,
            "applied_spec_json": applied_spec_json,
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
    ) -> ComicImage:
        image = ComicImage(
            generation_run_id=run_id,
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
                selectinload(GenerationRun.model_profile),
                selectinload(GenerationRun.tool_preset),
            )
        )

    def list_successful_runs(
        self,
        *,
        page_id: int,
        model_profile_id: int,
        generation_mode: GenerationMode,
        image_spec_id: int,
    ) -> list[GenerationRun]:
        return list(
            self.session.scalars(
                select(GenerationRun)
                .where(
                    GenerationRun.page_id == page_id,
                    GenerationRun.model_profile_id == model_profile_id,
                    GenerationRun.generation_mode == generation_mode,
                    GenerationRun.image_spec_id == image_spec_id,
                    GenerationRun.status == GenerationRunStatus.SUCCEEDED,
                )
                .order_by(GenerationRun.created_at, GenerationRun.id)
            )
        )
