from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models.comic import (
    ComicPage,
    ContinuityCompilation,
    ContinuityEvent,
    ImagePromptPreset,
    ImageSpec,
    ImageSpecCompilation,
    LLMConfig,
    OutfitVariant,
    PageShotPlan,
    ScriptCharacter,
    ScriptGenerationTask,
    ScriptScene,
    ScriptSection,
    StyleProfile,
    VisualAsset,
    VisualStateSnapshot,
)
from backend.models.enums import (
    ApprovalStatus,
    CompilationStatus,
    ContinuityEventSource,
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
    ImagePromptPresetKind,
    ImagePromptType,
)


class ImageSpecRepository:
    """视觉状态与 ImageSpec 数据访问层；编译历史采用只追加方式保存。"""

    def __init__(self, session: Session):
        self.session = session

    def get_script_task(self, task_id: int) -> ScriptGenerationTask | None:
        return self.session.scalar(
            select(ScriptGenerationTask)
            .where(ScriptGenerationTask.id == task_id)
            .options(
                selectinload(ScriptGenerationTask.outline_version),
                selectinload(ScriptGenerationTask.sections),
                selectinload(ScriptGenerationTask.scenes).selectinload(
                    ScriptScene.selected_visual_version
                ),
            )
        )

    def list_task_pages(self, task_id: int) -> list[ComicPage]:
        statement = (
            select(ComicPage)
            .join(ScriptSection, ComicPage.section_id == ScriptSection.id)
            .where(ScriptSection.task_id == task_id)
            .options(
                selectinload(ComicPage.section),
                selectinload(ComicPage.script_scene).selectinload(
                    ScriptScene.selected_visual_version
                ),
                selectinload(ComicPage.visual_characters).selectinload(
                    ScriptCharacter.outline_character
                ),
                selectinload(ComicPage.visual_characters).selectinload(
                    ScriptCharacter.outfit_variant
                ),
            )
            .order_by(ComicPage.page_no)
        )
        return list(self.session.scalars(statement).unique())

    def list_task_scenes(self, task_id: int) -> list[ScriptScene]:
        return list(
            self.session.scalars(
                select(ScriptScene)
                .where(ScriptScene.task_id == task_id)
                .options(selectinload(ScriptScene.selected_visual_version))
                .order_by(ScriptScene.scene_key)
            )
        )

    def list_project_assets(
        self,
        project_id: int,
        *,
        approved_only: bool = True,
    ) -> list[VisualAsset]:
        statement = select(VisualAsset).where(VisualAsset.project_id == project_id)
        if approved_only:
            statement = statement.where(VisualAsset.status == ApprovalStatus.APPROVED)
        return list(self.session.scalars(statement.order_by(VisualAsset.id)))

    def list_project_outfits(
        self,
        project_id: int,
        *,
        approved_only: bool = False,
    ) -> list[OutfitVariant]:
        statement = select(OutfitVariant).where(OutfitVariant.project_id == project_id)
        if approved_only:
            statement = statement.where(OutfitVariant.status == ApprovalStatus.APPROVED)
        return list(self.session.scalars(statement.order_by(OutfitVariant.id)))

    def get_style_profile(self, style_profile_id: int | None) -> StyleProfile | None:
        if style_profile_id is None:
            return None
        return self.session.get(StyleProfile, style_profile_id)

    def get_prompt_preset(
        self,
        preset_id: int | None,
        expected_kind: ImagePromptPresetKind,
    ) -> ImagePromptPreset | None:
        if preset_id is None:
            return None
        preset = self.session.get(ImagePromptPreset, preset_id)
        if preset is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        if preset.kind != expected_kind:
            raise ValueError(
                f"ImagePromptPreset {preset_id} kind must be {expected_kind.value}."
            )
        return preset

    def list_prompt_presets(
        self,
        kind: ImagePromptPresetKind | None = None,
    ) -> list[ImagePromptPreset]:
        statement = select(ImagePromptPreset)
        if kind is not None:
            statement = statement.where(ImagePromptPreset.kind == kind)
        return list(
            self.session.scalars(
                statement.order_by(
                    ImagePromptPreset.kind,
                    ImagePromptPreset.is_default.desc(),
                    ImagePromptPreset.updated_at.desc(),
                )
            )
        )

    def create_prompt_preset(self, **values: Any) -> ImagePromptPreset:
        item = ImagePromptPreset(**values)
        if item.is_default:
            self._clear_default_prompt_presets(item.kind)
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def update_prompt_preset(
        self,
        preset_id: int,
        **values: Any,
    ) -> ImagePromptPreset:
        item = self.session.get(ImagePromptPreset, preset_id)
        if item is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        if bool(values.get("is_default")):
            self._clear_default_prompt_presets(
                ImagePromptPresetKind(values.get("kind", item.kind)),
                except_preset_id=item.id,
            )
        for field_name, value in values.items():
            setattr(item, field_name, value)
        self.session.commit()
        self.session.refresh(item)
        return item

    def delete_prompt_preset(self, preset_id: int) -> None:
        item = self.session.get(ImagePromptPreset, preset_id)
        if item is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        self.session.delete(item)
        self.session.commit()

    def _clear_default_prompt_presets(
        self,
        kind: ImagePromptPresetKind,
        *,
        except_preset_id: int | None = None,
    ) -> None:
        for item in self.session.scalars(
            select(ImagePromptPreset).where(
                ImagePromptPreset.kind == kind,
                ImagePromptPreset.is_default.is_(True),
            )
        ):
            if item.id != except_preset_id:
                item.is_default = False

    def get_default_prompt_preset(
        self,
        kind: ImagePromptPresetKind,
    ) -> ImagePromptPreset | None:
        return self.session.scalar(
            select(ImagePromptPreset)
            .where(ImagePromptPreset.kind == kind, ImagePromptPreset.is_default.is_(True))
            .order_by(ImagePromptPreset.updated_at.desc())
            .limit(1)
        )

    def get_active_llm_config(self) -> LLMConfig | None:
        return self.session.scalar(
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True))
            .order_by(LLMConfig.updated_at.desc())
            .limit(1)
        )

    # Continuity compilation ------------------------------------------
    def find_reusable_compilation(
        self,
        *,
        task_id: int,
        source_hash: str,
    ) -> ContinuityCompilation | None:
        return self.session.scalar(
            select(ContinuityCompilation)
            .where(
                ContinuityCompilation.script_task_id == task_id,
                ContinuityCompilation.source_hash == source_hash,
                ContinuityCompilation.status == CompilationStatus.SUCCEEDED,
            )
            .options(
                selectinload(ContinuityCompilation.events),
                selectinload(ContinuityCompilation.snapshots),
            )
            .order_by(ContinuityCompilation.id.desc())
            .limit(1)
        )

    def create_compilation(
        self,
        *,
        task_id: int,
        source_hash: str,
        llm_config_id: int | None,
        llm_model: str | None,
        prompt_version: str,
        reducer_version: str,
    ) -> ContinuityCompilation:
        item = ContinuityCompilation(
            script_task_id=task_id,
            source_hash=source_hash,
            status=CompilationStatus.RUNNING,
            llm_config_id=llm_config_id,
            llm_model=llm_model,
            prompt_version=prompt_version,
            reducer_version=reducer_version,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def complete_compilation(
        self,
        *,
        compilation: ContinuityCompilation,
        events: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> ContinuityCompilation:
        page_id_by_no = {int(item["page_no"]): int(item["page_id"]) for item in snapshots}
        for event in events:
            page_no = int(event["page_no"])
            self.session.add(
                ContinuityEvent(
                    compilation_id=compilation.id,
                    page_id=page_id_by_no[page_no],
                    sequence_no=int(event["sequence_no"]),
                    event_type=ContinuityEventType(event["event_type"]),
                    target_type=ContinuityTargetType(event["target_type"]),
                    target_key=str(event["target_key"]),
                    timing=ContinuityEventTiming(event.get("timing", "after_page")),
                    payload_json=event["payload_json"],
                    source=ContinuityEventSource(event.get("source", "llm")),
                )
            )
        for snapshot in snapshots:
            self.session.add(
                VisualStateSnapshot(
                    compilation_id=compilation.id,
                    page_id=int(snapshot["page_id"]),
                    scene_visual_version_id=snapshot.get("scene_visual_version_id"),
                    state_json=snapshot["state_json"],
                    state_hash=snapshot["state_hash"],
                    warnings_json=snapshot.get("warnings_json", "[]"),
                )
            )
        compilation.status = CompilationStatus.SUCCEEDED
        compilation.error_code = None
        compilation.error_message = None
        self.session.commit()
        self.session.refresh(compilation)
        return compilation

    def fail_compilation(
        self,
        compilation: ContinuityCompilation,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        compilation.status = CompilationStatus.FAILED
        compilation.error_code = error_code
        compilation.error_message = error_message
        self.session.commit()

    def get_compilation(self, compilation_id: int) -> ContinuityCompilation | None:
        return self.session.scalar(
            select(ContinuityCompilation)
            .where(ContinuityCompilation.id == compilation_id)
            .options(
                selectinload(ContinuityCompilation.events),
                selectinload(ContinuityCompilation.snapshots),
            )
        )

    def list_compilations(self, task_id: int) -> list[ContinuityCompilation]:
        return list(
            self.session.scalars(
                select(ContinuityCompilation)
                .where(ContinuityCompilation.script_task_id == task_id)
                .options(
                    selectinload(ContinuityCompilation.events),
                    selectinload(ContinuityCompilation.snapshots),
                )
                .order_by(ContinuityCompilation.id.desc())
            )
        )

    # Shot plans and specs ---------------------------------------------
    def add_shot_plan(
        self,
        *,
        page_id: int,
        snapshot_id: int,
        planner_preset_id: int | None,
        plan_json: str,
        plan_hash: str,
        planner_model: str | None,
        prompt_version: str,
    ) -> PageShotPlan:
        item = PageShotPlan(
            page_id=page_id,
            snapshot_id=snapshot_id,
            planner_preset_id=planner_preset_id,
            plan_json=plan_json,
            plan_hash=plan_hash,
            planner_model=planner_model,
            prompt_version=prompt_version,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def add_image_spec(
        self,
        *,
        page_id: int,
        snapshot_id: int,
        shot_plan_id: int,
        prompt_type: ImagePromptType,
        style_profile_id: int | None,
        negative_prompt_preset_id: int | None,
        generation_mode: GenerationMode,
        spec_json: str,
        positive_prompt: str,
        negative_prompt: str,
        required_capabilities_json: str,
        warnings_json: str,
        source_hash: str,
        spec_hash: str,
        compiler_key: str,
        compiler_version: str,
    ) -> ImageSpec:
        item = ImageSpec(
            page_id=page_id,
            snapshot_id=snapshot_id,
            shot_plan_id=shot_plan_id,
            prompt_type=prompt_type,
            style_profile_id=style_profile_id,
            negative_prompt_preset_id=negative_prompt_preset_id,
            generation_mode=generation_mode,
            spec_json=spec_json,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            required_capabilities_json=required_capabilities_json,
            warnings_json=warnings_json,
            source_hash=source_hash,
            spec_hash=spec_hash,
            compiler_key=compiler_key,
            compiler_version=compiler_version,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def mark_pages_spec_ready(self, page_ids: list[int]) -> None:
        """三种规格全部落库后再推进页面状态，避免半成品被生成链路读取。"""

        from backend.models.enums import ComicPageStatus

        for page_id in page_ids:
            page = self.session.get(ComicPage, page_id)
            if page is None:
                raise ValueError(f"ComicPage not found: {page_id}")
            page.status = ComicPageStatus.SPEC_READY
        self.session.commit()

    def list_latest_specs(
        self,
        *,
        task_id: int,
        prompt_type: ImagePromptType | None = None,
    ) -> list[ImageSpec]:
        statement = (
            select(ImageSpec)
            .join(ComicPage, ImageSpec.page_id == ComicPage.id)
            .join(ScriptSection, ComicPage.section_id == ScriptSection.id)
            .where(ScriptSection.task_id == task_id)
            .options(
                selectinload(ImageSpec.snapshot),
                selectinload(ImageSpec.shot_plan),
            )
            .order_by(ImageSpec.page_id, ImageSpec.prompt_type, ImageSpec.id.desc())
        )
        if prompt_type is not None:
            statement = statement.where(ImageSpec.prompt_type == prompt_type)
        rows = list(self.session.scalars(statement))
        latest: dict[tuple[int, ImagePromptType, GenerationMode], ImageSpec] = {}
        for item in rows:
            key = (item.page_id, item.prompt_type, item.generation_mode)
            latest.setdefault(key, item)
        return list(latest.values())

    # ImageSpec batch compilation ------------------------------------
    def create_image_spec_compilation(
        self,
        *,
        task_id: int,
        continuity_compilation_id: int,
        source_hash: str,
        generation_mode: GenerationMode,
        total_pages: int,
        total_specs: int,
    ) -> ImageSpecCompilation:
        item = ImageSpecCompilation(
            script_task_id=task_id,
            continuity_compilation_id=continuity_compilation_id,
            source_hash=source_hash,
            status=CompilationStatus.RUNNING,
            generation_mode=generation_mode,
            total_pages=total_pages,
            completed_pages=0,
            total_specs=total_specs,
            completed_specs=0,
            failed_pages_json="[]",
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_shot_plans(
        self,
        *,
        page_id: int,
        snapshot_id: int,
    ) -> list[PageShotPlan]:
        """返回当前页面快照的历史计划，Service 再按 Prompt/模型 hash 判定复用。"""

        return list(
            self.session.scalars(
                select(PageShotPlan)
                .where(
                    PageShotPlan.page_id == page_id,
                    PageShotPlan.snapshot_id == snapshot_id,
                )
                .order_by(PageShotPlan.id.desc())
            )
        )

    def update_image_spec_compilation_progress(
        self,
        item: ImageSpecCompilation,
        *,
        completed_pages: int,
        completed_specs: int,
        failed_pages_json: str = "[]",
    ) -> None:
        item.completed_pages = completed_pages
        item.completed_specs = completed_specs
        item.failed_pages_json = failed_pages_json
        self.session.commit()

    def complete_image_spec_compilation(self, item: ImageSpecCompilation) -> None:
        item.status = CompilationStatus.SUCCEEDED
        item.completed_pages = item.total_pages
        item.completed_specs = item.total_specs
        item.failed_pages_json = "[]"
        item.error_code = None
        item.error_message = None
        self.session.commit()

    def fail_image_spec_compilation(
        self,
        item: ImageSpecCompilation,
        *,
        completed_pages: int,
        completed_specs: int,
        failed_pages_json: str,
        error_code: str,
        error_message: str,
    ) -> None:
        item.status = CompilationStatus.FAILED
        item.completed_pages = completed_pages
        item.completed_specs = completed_specs
        item.failed_pages_json = failed_pages_json
        item.error_code = error_code
        item.error_message = error_message
        self.session.commit()

    def list_image_spec_compilations(self, task_id: int) -> list[ImageSpecCompilation]:
        return list(
            self.session.scalars(
                select(ImageSpecCompilation)
                .where(ImageSpecCompilation.script_task_id == task_id)
                .order_by(ImageSpecCompilation.id.desc())
            )
        )

    def get_image_spec(self, spec_id: int) -> ImageSpec | None:
        return self.session.scalar(
            select(ImageSpec)
            .where(ImageSpec.id == spec_id)
            .options(
                selectinload(ImageSpec.snapshot),
                selectinload(ImageSpec.shot_plan),
            )
        )
