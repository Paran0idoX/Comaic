import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator

from backend.agents.continuity_event_agent import ContinuityEventAgent
from backend.agents.shot_planner_agent import ShotPlannerAgent
from backend.i18n.errors import AppError, app_error_from_exception
from backend.models.comic import (
    ComicPage,
    ContinuityCompilation,
    ImagePromptPreset,
    ImageSpec,
    ImageSpecCompilation,
    OutfitVariant,
    PageShotPlan,
    ScriptScene,
    StyleProfile,
    VisualAsset,
    VisualStateSnapshot,
)
from backend.models.enums import (
    ApprovalStatus,
    ContinuityEventSource,
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
    ImagePromptPresetKind,
    ImagePromptType,
    PageScriptReviewStatus,
    ScriptGenerationTaskStatus,
    VisualAssetRole,
    VisualEntityType,
)
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_compilers import compiler_for_prompt_type
from backend.services.visual_state_reducer import VisualStateReducer
from backend.utils.json_utils import canonical_hash, canonical_json
from backend.utils.prompt_loader import PromptLoader


CONTROL_ROLES = {
    VisualAssetRole.POSE.value: "pose",
    VisualAssetRole.DEPTH.value: "depth",
    VisualAssetRole.CANNY.value: "canny",
    VisualAssetRole.LINEART.value: "lineart",
}


class ImageSpecService:
    """编排连续性事件、确定性状态、ShotPlan 和三类 Prompt ImageSpec。"""

    PROMPT_VERSION = "2"
    CONTINUITY_REDUCER_ATTEMPTS = 3

    def __init__(self, repository: ImageSpecRepository):
        self.repository = repository

    def ensure_default_presets(self) -> None:
        """为新结构初始化 ShotPlanner Prompt，同时复用现有 Negative Prompt。"""

        if self.repository.get_default_prompt_preset(
            ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT
        ) is None:
            self.repository.session.add(
                ImagePromptPreset(
                    name="Default shot planner",
                    description="Plan camera, subject regions and controls without rewriting visual identity.",
                    kind=ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT,
                    content=PromptLoader.load("shot_planner_prompt.md"),
                    is_default=True,
                )
            )
            self.repository.session.commit()
        if self.repository.get_default_prompt_preset(
            ImagePromptPresetKind.NEGATIVE_PROMPT
        ) is None:
            self.repository.session.add(
                ImagePromptPreset(
                    name="Default negative prompt",
                    description="Generic negative prompt for structured comic image generation.",
                    kind=ImagePromptPresetKind.NEGATIVE_PROMPT,
                    content="low quality, blurry, bad anatomy, extra fingers, text, watermark",
                    tag_content="low quality, blurry, bad anatomy, extra fingers, text, watermark",
                    natural_language_content=(
                        "Avoid low quality, blur, incorrect anatomy, extra fingers, text, and watermarks."
                    ),
                    is_default=True,
                )
            )
            self.repository.session.commit()

    def list_presets(
        self,
        kind: ImagePromptPresetKind | None = None,
    ) -> list[ImagePromptPreset]:
        self.ensure_default_presets()
        return self.repository.list_prompt_presets(kind)

    def create_preset(
        self,
        *,
        name: str,
        kind: ImagePromptPresetKind,
        content: str = "",
        tag_content: str = "",
        natural_language_content: str = "",
        description: str | None = None,
        is_default: bool = False,
    ) -> ImagePromptPreset:
        values = self._normalize_preset_values(
            name=name,
            kind=kind,
            content=content,
            tag_content=tag_content,
            natural_language_content=natural_language_content,
            description=description,
            is_default=is_default,
        )
        return self.repository.create_prompt_preset(**values)

    def update_preset(self, *, preset_id: int, **values: Any) -> ImagePromptPreset:
        current = self.repository.session.get(ImagePromptPreset, preset_id)
        if current is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        normalized = self._normalize_preset_values(
            name=str(values.get("name", current.name)),
            kind=ImagePromptPresetKind(values.get("kind", current.kind)),
            content=str(values.get("content", current.content)),
            tag_content=str(values.get("tag_content", current.tag_content)),
            natural_language_content=str(
                values.get("natural_language_content", current.natural_language_content)
            ),
            description=values.get("description", current.description),
            is_default=bool(values.get("is_default", current.is_default)),
        )
        return self.repository.update_prompt_preset(preset_id, **normalized)

    def delete_preset(self, preset_id: int) -> None:
        self.repository.delete_prompt_preset(preset_id)

    @staticmethod
    def _normalize_preset_values(
        *,
        name: str,
        kind: ImagePromptPresetKind,
        content: str,
        tag_content: str,
        natural_language_content: str,
        description: str | None,
        is_default: bool,
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Prompt preset name is required.")
        if kind == ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT:
            normalized_content = content.strip()
            if not normalized_content:
                raise ValueError("ShotPlanner prompt content is required.")
            tag_content = ""
            natural_language_content = ""
        else:
            normalized_content = content.strip() or tag_content.strip()
            if not tag_content.strip() or not natural_language_content.strip():
                raise ValueError(
                    "Negative prompt preset requires tag and natural language content."
                )
        return {
            "name": normalized_name,
            "kind": kind,
            "content": normalized_content,
            "tag_content": tag_content.strip(),
            "natural_language_content": natural_language_content.strip(),
            "description": description.strip() if description else None,
            "is_default": is_default,
        }
    async def stream_compile_task(
        self,
        *,
        task_id: int,
        style_profile_id: int | None,
        shot_planner_preset_id: int | None,
        negative_prompt_preset_id: int | None,
        generation_mode: GenerationMode,
        concurrency: int = 8,
        regenerate_continuity: bool = False,
        resume_existing: bool = True,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """流式编译完整任务；视觉真值和镜头计划只计算一次，再生成三类规格。"""

        context = self._prepare_context(
            task_id=task_id,
            style_profile_id=style_profile_id,
            shot_planner_preset_id=shot_planner_preset_id,
            negative_prompt_preset_id=negative_prompt_preset_id,
        )
        pages: list[ComicPage] = context["pages"]
        yield "start", {
            "task_id": task_id,
            "total_pages": len(pages),
            "prompt_types": [item.value for item in ImagePromptType],
            "generation_mode": generation_mode.value,
        }

        compilation, reused = await self._compile_continuity(
            context=context,
            regenerate=regenerate_continuity,
        )
        yield "continuity", {
            "compilation_id": compilation.id,
            "source_hash": compilation.source_hash,
            "reused": reused,
            "event_count": len(compilation.events),
            "snapshot_count": len(compilation.snapshots),
        }
        snapshots_by_page = {item.page_id: item for item in compilation.snapshots}
        total_specs = len(pages) * len(ImagePromptType)
        for page in pages:
            snapshot = snapshots_by_page[page.id]
            yield "snapshot", self._snapshot_payload(snapshot, page)

        normalized_concurrency = max(1, min(concurrency, 20))
        semaphore = asyncio.Semaphore(normalized_concurrency)
        planner = ShotPlannerAgent(system_prompt=context["planner_preset"].content)

        async def plan_page(
            page: ComicPage,
        ) -> tuple[ComicPage, dict[str, Any], PageShotPlan | None]:
            async with semaphore:
                snapshot = snapshots_by_page[page.id]
                existing = self._reusable_shot_plan(
                    page=page,
                    snapshot=snapshot,
                    context=context,
                )
                if existing is not None:
                    return page, self._loads_object(existing.plan_json), existing
                snapshot_data = self._loads_object(snapshot.state_json)
                page_data = self._page_payload(page)
                controls = self._available_controls(snapshot_data)
                plan = await planner.plan(
                    page=page_data,
                    snapshot=snapshot_data,
                    available_controls=controls,
                )
                return page, plan, None

        reusable = (
            self._reusable_specs_by_page(
                context=context,
                snapshots_by_page=snapshots_by_page,
                generation_mode=generation_mode,
            )
            if resume_existing
            else {}
        )
        completed_pages = len(reusable)
        completed_specs = completed_pages * len(ImagePromptType)
        failed_pages: list[dict[str, Any]] = []
        terminal = False
        batch = self.repository.create_image_spec_compilation(
            task_id=task_id,
            continuity_compilation_id=compilation.id,
            source_hash=self._image_spec_compilation_source_hash(
                context=context,
                compilation=compilation,
                generation_mode=generation_mode,
            ),
            generation_mode=generation_mode,
            total_pages=len(pages),
            total_specs=total_specs,
        )
        self.repository.update_image_spec_compilation_progress(
            batch,
            completed_pages=completed_pages,
            completed_specs=completed_specs,
        )

        pending_pages = [page for page in pages if page.id not in reusable]
        planning_tasks: list[asyncio.Task] = []
        try:
            yield "compilation", self._image_spec_compilation_payload(batch)
            if reusable:
                yield "resume", {
                    "compilation_id": batch.id,
                    "page_nos": sorted(
                        page.page_no for page in pages if page.id in reusable
                    ),
                    "completed_pages": completed_pages,
                    "completed_specs": completed_specs,
                }
            # 按完成顺序逐页落库；单页失败不取消其它页面，断开 SSE 时 finally
            # 会显式取消并等待所有未完成 Task，避免留下无人接收的模型调用。
            async def guarded_plan(
                page: ComicPage,
            ) -> tuple[ComicPage, dict[str, Any] | None, PageShotPlan | None, Exception | None]:
                try:
                    planned_page, plan_data, existing_plan = await plan_page(page)
                    return planned_page, plan_data, existing_plan, None
                except Exception as exc:  # 单页模型失败不取消其它页面
                    return page, None, None, exc

            planning_tasks = [
                asyncio.create_task(guarded_plan(page)) for page in pending_pages
            ]
            for completed_task in asyncio.as_completed(planning_tasks):
                page, plan_data, existing_plan, plan_error = await completed_task
                if plan_error is not None or plan_data is None:
                    failure = self._page_compilation_failure(
                        page,
                        plan_error or RuntimeError("ShotPlanner returned no plan."),
                        default_code="image_spec.shot_plan_invalid",
                    )
                    failed_pages.append(failure)
                    self.repository.update_image_spec_compilation_progress(
                        batch,
                        completed_pages=completed_pages,
                        completed_specs=completed_specs,
                        failed_pages_json=canonical_json(failed_pages),
                    )
                    yield "page_error", self._public_page_failure_payload(failure)
                    continue

                try:
                    snapshot = snapshots_by_page[page.id]
                    shot_plan = existing_plan or self.repository.add_shot_plan(
                        page_id=page.id,
                        snapshot_id=snapshot.id,
                        planner_preset_id=context["planner_preset"].id,
                        plan_json=canonical_json(plan_data),
                        plan_hash=self._shot_plan_source_hash(
                            plan=plan_data,
                            planner_preset=context["planner_preset"],
                            planner_model=context["llm_model"],
                        ),
                        planner_model=context["llm_model"],
                        prompt_version=self.PROMPT_VERSION,
                    )
                    shot_plan_payload = self._shot_plan_payload(shot_plan, page)
                    shot_plan_payload["reused"] = existing_plan is not None
                    yield "shot_plan", shot_plan_payload

                    for prompt_type in ImagePromptType:
                        spec = self._compile_prompt_spec(
                            page=page,
                            snapshot=snapshot,
                            shot_plan=shot_plan,
                            prompt_type=prompt_type,
                            style_profile=context["style"],
                            style_assets=context["style_assets"],
                            negative_preset=context["negative_preset"],
                            generation_mode=generation_mode,
                        )
                        completed_specs += 1
                        yield "image_spec", self._spec_payload(spec, page)
                        yield "progress", {
                            "task_id": task_id,
                            "compilation_id": batch.id,
                            "completed": completed_specs,
                            "total": total_specs,
                        }
                    self.repository.mark_pages_spec_ready([page.id])
                    completed_pages += 1
                    self.repository.update_image_spec_compilation_progress(
                        batch,
                        completed_pages=completed_pages,
                        completed_specs=completed_specs,
                        failed_pages_json=canonical_json(failed_pages),
                    )
                except Exception as exc:
                    failure = self._page_compilation_failure(page, exc)
                    failed_pages.append(failure)
                    self.repository.update_image_spec_compilation_progress(
                        batch,
                        completed_pages=completed_pages,
                        completed_specs=completed_specs,
                        failed_pages_json=canonical_json(failed_pages),
                    )
                    yield "page_error", self._public_page_failure_payload(failure)

            if failed_pages:
                details = canonical_json(failed_pages)
                failure_codes = {str(item["code"]) for item in failed_pages}
                if len(failure_codes) == 1:
                    batch_error_code = next(iter(failure_codes))
                elif "image_spec.shot_plan_invalid" in failure_codes:
                    batch_error_code = "image_spec.shot_plan_invalid"
                else:
                    batch_error_code = "image_spec.compilation_failed"
                self.repository.fail_image_spec_compilation(
                    batch,
                    completed_pages=completed_pages,
                    completed_specs=completed_specs,
                    failed_pages_json=details,
                    error_code=batch_error_code,
                    error_message=details,
                )
                terminal = True
                yield "failed", self._image_spec_compilation_payload(batch)
                raise AppError(
                    batch_error_code,
                    status_code=(
                        400
                        if batch_error_code == "image_spec.final_conditions_missing"
                        else 422
                    ),
                    params={"count": len(failed_pages)},
                    debug_message=(
                        f"ImageSpec compilation {batch.id} failed on pages "
                        f"{[item['page_no'] for item in failed_pages]}"
                    ),
                )

            self.repository.complete_image_spec_compilation(batch)
            terminal = True
            yield "done", {
                "task_id": task_id,
                "continuity_compilation_id": compilation.id,
                "image_spec_compilation_id": batch.id,
                "total_pages": len(pages),
                "total_specs": total_specs,
            }
        except asyncio.CancelledError:
            self.repository.fail_image_spec_compilation(
                batch,
                completed_pages=completed_pages,
                completed_specs=completed_specs,
                failed_pages_json=canonical_json(failed_pages),
                error_code="image_spec.compilation_interrupted",
                error_message="ImageSpec compilation stream was cancelled.",
            )
            terminal = True
            raise
        except AppError:
            raise
        except Exception as exc:
            self.repository.fail_image_spec_compilation(
                batch,
                completed_pages=completed_pages,
                completed_specs=completed_specs,
                failed_pages_json=canonical_json(failed_pages),
                error_code="image_spec.compilation_failed",
                error_message=str(exc),
            )
            terminal = True
            raise AppError(
                "image_spec.compilation_failed",
                status_code=500,
                debug_message=str(exc),
            ) from exc
        finally:
            for task in planning_tasks:
                if not task.done():
                    task.cancel()
            if planning_tasks:
                await asyncio.gather(*planning_tasks, return_exceptions=True)
            if not terminal:
                self.repository.fail_image_spec_compilation(
                    batch,
                    completed_pages=completed_pages,
                    completed_specs=completed_specs,
                    failed_pages_json=canonical_json(failed_pages),
                    error_code="image_spec.compilation_interrupted",
                    error_message="ImageSpec compilation stream ended before completion.",
                )

    def _reusable_shot_plan(
        self,
        *,
        page: ComicPage,
        snapshot: VisualStateSnapshot,
        context: dict[str, Any],
    ) -> PageShotPlan | None:
        """Prompt 表达类型或 Preview/Final 改变时复用仍有效的模型无关镜头计划。"""

        for shot_plan in self.repository.list_shot_plans(
            page_id=page.id,
            snapshot_id=snapshot.id,
        ):
            if shot_plan.planner_preset_id != context["planner_preset"].id:
                continue
            plan = self._loads_object(shot_plan.plan_json)
            current_hash = self._shot_plan_source_hash(
                plan=plan,
                planner_preset=context["planner_preset"],
                planner_model=context["llm_model"],
            )
            if shot_plan.plan_hash == current_hash:
                return shot_plan
        return None

    def _reusable_specs_by_page(
        self,
        *,
        context: dict[str, Any],
        snapshots_by_page: dict[int, VisualStateSnapshot],
        generation_mode: GenerationMode,
    ) -> dict[int, list[ImageSpec]]:
        """只复用来源仍完全一致、且三种 Prompt 共用同一 ShotPlan 的页面。"""

        latest = self.repository.list_latest_specs(task_id=context["task"].id)
        by_key = {
            (item.page_id, item.prompt_type, item.generation_mode): item
            for item in latest
        }
        reusable: dict[int, list[ImageSpec]] = {}
        expected_style_id = context["style"].id if context["style"] else None
        expected_negative_id = (
            context["negative_preset"].id if context["negative_preset"] else None
        )
        expected_planner_id = context["planner_preset"].id
        for page in context["pages"]:
            snapshot = snapshots_by_page[page.id]
            specs = [
                by_key.get((page.id, prompt_type, generation_mode))
                for prompt_type in ImagePromptType
            ]
            if any(item is None for item in specs):
                continue
            typed_specs = [item for item in specs if item is not None]
            if len({item.shot_plan_id for item in typed_specs}) != 1:
                continue
            shot_plan = typed_specs[0].shot_plan
            if (
                shot_plan.snapshot_id != snapshot.id
                or shot_plan.planner_preset_id != expected_planner_id
            ):
                continue
            current_plan_hash = self._shot_plan_source_hash(
                plan=self._loads_object(shot_plan.plan_json),
                planner_preset=context["planner_preset"],
                planner_model=context["llm_model"],
            )
            if shot_plan.plan_hash != current_plan_hash:
                continue
            valid = True
            for spec in typed_specs:
                if (
                    spec.snapshot_id != snapshot.id
                    or spec.style_profile_id != expected_style_id
                    or spec.negative_prompt_preset_id != expected_negative_id
                ):
                    valid = False
                    break
                expected_source_hash = self._image_spec_source_hash(
                    snapshot_hash=snapshot.state_hash,
                    plan_hash=current_plan_hash,
                    prompt_type=spec.prompt_type,
                    style_profile=context["style"],
                    style_assets=context["style_assets"],
                    negative_preset=context["negative_preset"],
                )
                if spec.source_hash != expected_source_hash:
                    valid = False
                    break
            if valid:
                reusable[page.id] = typed_specs
        return reusable

    def _image_spec_compilation_source_hash(
        self,
        *,
        context: dict[str, Any],
        compilation: ContinuityCompilation,
        generation_mode: GenerationMode,
    ) -> str:
        """批量任务 Hash 用于审计本次连续性快照、Prompt 与编译器组合。"""

        return canonical_hash(
            {
                "schema_version": 1,
                "continuity_source_hash": compilation.source_hash,
                "snapshots": [
                    {
                        "page_id": item.page_id,
                        "state_hash": item.state_hash,
                    }
                    for item in sorted(compilation.snapshots, key=lambda value: value.page_id)
                ],
                "generation_mode": generation_mode.value,
                "style": (
                    self._style_payload(context["style"], context["style_assets"])
                    if context["style"] is not None
                    else None
                ),
                "planner_preset": {
                    "id": context["planner_preset"].id,
                    "content_hash": canonical_hash(context["planner_preset"].content),
                },
                "negative_prompt": self._negative_prompt_payload(
                    context["negative_preset"]
                ),
                "agent": {
                    "version": ShotPlannerAgent.VERSION,
                    "llm_model": context["llm_model"],
                },
                "compilers": [
                    {
                        "prompt_type": prompt_type.value,
                        "key": compiler_for_prompt_type(prompt_type).compiler_key,
                        "version": compiler_for_prompt_type(prompt_type).compiler_version,
                    }
                    for prompt_type in ImagePromptType
                ],
            }
        )

    @staticmethod
    def _page_compilation_failure(
        page: ComicPage,
        exc: BaseException,
        *,
        default_code: str | None = None,
    ) -> dict[str, Any]:
        mapped = app_error_from_exception(
            exc if isinstance(exc, Exception) else RuntimeError(str(exc))
        )
        code = mapped.code
        if default_code and code.startswith("common."):
            code = default_code
        return {
            "page_id": page.id,
            "page_no": page.page_no,
            "code": code,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    @staticmethod
    def _public_page_failure_payload(failure: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": failure["code"],
            "page_id": failure["page_id"],
            "page_no": failure["page_no"],
            "message": f"Page {failure['page_no']} could not be compiled.",
        }

    @staticmethod
    def _image_spec_compilation_payload(item: ImageSpecCompilation) -> dict[str, Any]:
        return {
            "id": item.id,
            "task_id": item.script_task_id,
            "continuity_compilation_id": item.continuity_compilation_id,
            "source_hash": item.source_hash,
            "status": item.status.value,
            "generation_mode": item.generation_mode.value,
            "total_pages": item.total_pages,
            "completed_pages": item.completed_pages,
            "total_specs": item.total_specs,
            "completed_specs": item.completed_specs,
            "failed_pages": ImageSpecService._loads_list(item.failed_pages_json),
            "error_code": item.error_code,
            "error_message": item.error_message,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    def list_image_spec_compilations(self, task_id: int) -> list[dict[str, Any]]:
        if self.repository.get_script_task(task_id) is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return [
            self._image_spec_compilation_payload(item)
            for item in self.repository.list_image_spec_compilations(task_id)
        ]

    def list_task_specs(
        self,
        *,
        task_id: int,
        prompt_type: ImagePromptType | None = None,
    ) -> list[dict[str, Any]]:
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        pages = {page.id: page for page in self.repository.list_task_pages(task_id)}
        return [
            self._spec_payload(spec, pages[spec.page_id])
            for spec in self.repository.list_latest_specs(
                task_id=task_id,
                prompt_type=prompt_type,
            )
        ]

    def current_continuity_source_hash(self, task_id: int) -> str:
        """计算当前脚本与获批视觉资产的 hash，生成前用它拒绝过期规格。"""

        context = self._prepare_context(
            task_id=task_id,
            style_profile_id=None,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
        )
        return canonical_hash(self._continuity_source_payload(context))

    def current_image_spec_source_hash(self, spec: ImageSpec) -> str:
        """按当前 Prompt 类型、风格和预设重算来源，用于生成前判定 stale。"""
        style = self.repository.get_style_profile(spec.style_profile_id)
        style_assets: list[dict[str, Any]] = []
        if style is not None:
            style_assets = [
                self._asset_payload(asset)
                for asset in self.repository.list_project_assets(style.project_id, approved_only=True)
                if asset.entity_type == VisualEntityType.STYLE and asset.entity_id == style.id
            ]
        negative_preset = (
            self.repository.session.get(ImagePromptPreset, spec.negative_prompt_preset_id)
            if spec.negative_prompt_preset_id is not None
            else None
        )
        planner_preset = (
            self.repository.session.get(ImagePromptPreset, spec.shot_plan.planner_preset_id)
            if spec.shot_plan.planner_preset_id is not None
            else None
        )
        current_plan_hash = self._shot_plan_source_hash(
            plan=self._loads_object(spec.shot_plan.plan_json),
            planner_preset=planner_preset,
            planner_model=spec.shot_plan.planner_model,
        )
        return self._image_spec_source_hash(
            snapshot_hash=spec.snapshot.state_hash,
            plan_hash=current_plan_hash,
            prompt_type=spec.prompt_type,
            style_profile=style,
            style_assets=style_assets,
            negative_preset=negative_preset,
        )

    async def replace_events(
        self,
        *,
        compilation_id: int,
        events: list[dict[str, Any]],
    ) -> ContinuityCompilation:
        """人工校正创建新编译版本；保留系统事件并替换非系统事件。"""

        original = self.repository.get_compilation(compilation_id)
        if original is None:
            raise ValueError(f"ContinuityCompilation not found: {compilation_id}")
        context = self._prepare_context(
            task_id=original.script_task_id,
            style_profile_id=None,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
        )
        # 系统事件来自当前脚本分段和当前获批版本，不能沿用旧 compilation 的快照。
        system_events = self._section_boundary_events(context)
        manual_events = [
            {**event, "source": ContinuityEventSource.MANUAL.value}
            for event in events
        ]
        combined = self._normalize_events(
            system_events + manual_events,
            context=context,
        )
        return self._persist_reduced_compilation(
            context=context,
            source_hash=canonical_hash(self._continuity_source_payload(context)),
            events=combined,
        )

    # Context and continuity -------------------------------------------
    def _prepare_context(
        self,
        *,
        task_id: int,
        style_profile_id: int | None,
        shot_planner_preset_id: int | None,
        negative_prompt_preset_id: int | None,
    ) -> dict[str, Any]:
        self.ensure_default_presets()
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if task.status != ScriptGenerationTaskStatus.SUCCEEDED:
            raise AppError(
                "script.task_not_succeeded",
                status_code=409,
                debug_message=(
                    f"ScriptGenerationTask {task_id} has status {task.status.value}."
                ),
            )
        pages = [page for page in self.repository.list_task_pages(task_id) if page.summary]
        if not pages:
            raise ValueError(f"Script pages not found for task: {task_id}")
        unreviewed_page_nos = [
            page.page_no
            for page in pages
            if page.script_review_status != PageScriptReviewStatus.PASSED
        ]
        if unreviewed_page_nos:
            page_list = ", ".join(str(page_no) for page_no in unreviewed_page_nos)
            raise AppError(
                "script.pages_not_reviewed",
                status_code=409,
                params={"pages": page_list},
                debug_message=(
                    f"Script task {task_id} contains pages without passed supervisor "
                    f"review: {page_list}."
                ),
            )
        style = self.repository.get_style_profile(style_profile_id)
        if style_profile_id is not None and (
            style is None or style.project_id != task.project_id
        ):
            raise ValueError(f"StyleProfile not found for project: {style_profile_id}")
        planner_preset = (
            self.repository.get_prompt_preset(
                shot_planner_preset_id,
                ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT,
            )
            if shot_planner_preset_id is not None
            else self.repository.get_default_prompt_preset(
                ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT
            )
        )
        negative_preset = (
            self.repository.get_prompt_preset(
                negative_prompt_preset_id,
                ImagePromptPresetKind.NEGATIVE_PROMPT,
            )
            if negative_prompt_preset_id is not None
            else self.repository.get_default_prompt_preset(
                ImagePromptPresetKind.NEGATIVE_PROMPT
            )
        )
        if planner_preset is None:
            raise ValueError("ShotPlanner prompt preset is required.")
        assets = self.repository.list_project_assets(task.project_id, approved_only=True)
        asset_payloads = [self._asset_payload(asset) for asset in assets]
        assets_by_owner: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for asset in asset_payloads:
            if asset["entity_id"] is not None:
                assets_by_owner[(asset["entity_type"], int(asset["entity_id"]))].append(asset)
        style_assets = (
            assets_by_owner.get((VisualEntityType.STYLE.value, style.id), [])
            if style is not None
            else []
        )
        active_llm = self.repository.get_active_llm_config()
        return {
            "task": task,
            "pages": pages,
            "style": style,
            "style_assets": style_assets,
            "planner_preset": planner_preset,
            "negative_preset": negative_preset,
            "assets": assets,
            "asset_payloads": asset_payloads,
            "assets_by_owner": assets_by_owner,
            "outfits": self.repository.list_project_outfits(
                task.project_id, approved_only=True
            ),
            "scenes": self.repository.list_task_scenes(task_id),
            "llm_config_id": active_llm.id if active_llm else None,
            "llm_model": active_llm.default_model if active_llm else None,
        }

    async def _compile_continuity(
        self,
        *,
        context: dict[str, Any],
        regenerate: bool,
    ) -> tuple[ContinuityCompilation, bool]:
        source_payload = self._continuity_source_payload(context)
        source_hash = canonical_hash(source_payload)
        if not regenerate:
            reusable = self.repository.find_reusable_compilation(
                task_id=context["task"].id,
                source_hash=source_hash,
            )
            if reusable is not None:
                return reusable, True
        validation_feedback: str | None = None
        last_error: Exception | None = None
        for attempt in range(1, self.CONTINUITY_REDUCER_ATTEMPTS + 1):
            compilation = self.repository.create_compilation(
                task_id=context["task"].id,
                source_hash=source_hash,
                llm_config_id=context["llm_config_id"],
                llm_model=context["llm_model"],
                prompt_version=self.PROMPT_VERSION,
                reducer_version=VisualStateReducer.VERSION,
            )
            try:
                llm_events = await ContinuityEventAgent().extract(
                    pages=[self._page_payload(page) for page in context["pages"]],
                    characters=self._character_agent_payloads(context["pages"]),
                    scenes=[self._scene_text_payload(scene) for scene in context["scenes"]],
                    outfits=[self._outfit_payload(item, []) for item in context["outfits"]],
                    validation_feedback=validation_feedback,
                )
                system_events = self._section_boundary_events(context)
                events = self._normalize_events(system_events + llm_events, context=context)
                completed = self._persist_reduced_compilation(
                    context=context,
                    source_hash=source_hash,
                    events=events,
                    existing_compilation=compilation,
                )
                return completed, False
            except Exception as exc:
                last_error = exc
                validation_feedback = str(exc)
                self.repository.fail_compilation(
                    compilation,
                    error_code="image_spec.continuity_failed",
                    error_message=(
                        f"attempt {attempt}/{self.CONTINUITY_REDUCER_ATTEMPTS}: {exc}"
                    ),
                )

        raise AppError(
            "image_spec.continuity_invalid",
            status_code=400,
            debug_message=(
                "Continuity reducer validation failed after "
                f"{self.CONTINUITY_REDUCER_ATTEMPTS} attempts: {last_error}"
            ),
        )

    def _persist_reduced_compilation(
        self,
        *,
        context: dict[str, Any],
        source_hash: str,
        events: list[dict[str, Any]],
        existing_compilation: ContinuityCompilation | None = None,
    ) -> ContinuityCompilation:
        compilation = existing_compilation or self.repository.create_compilation(
            task_id=context["task"].id,
            source_hash=source_hash,
            llm_config_id=context["llm_config_id"],
            llm_model=context["llm_model"],
            prompt_version=self.PROMPT_VERSION,
            reducer_version=VisualStateReducer.VERSION,
        )
        character_baselines = self._character_baselines(context)
        scene_baselines = self._scene_baselines(context)
        reduced = VisualStateReducer(
            character_baselines=character_baselines,
            scene_baselines=scene_baselines,
        ).reduce(
            pages=[self._reducer_page_payload(page) for page in context["pages"]],
            events=events,
        )
        prop_assets_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for asset in context["asset_payloads"]:
            if (
                asset["entity_type"] == VisualEntityType.PROP.value
                and asset.get("entity_key")
            ):
                prop_assets_by_key[str(asset["entity_key"])].append(asset)
        for page_state in reduced:
            for character_state in page_state["characters"]:
                character_state["held_prop_assets"] = [
                    {
                        "prop_key": prop_key,
                        "assets": prop_assets_by_key.get(prop_key, []),
                    }
                    for prop_key in character_state.get("held_props", [])
                ]
        scene_version_by_key = {
            scene.scene_key: (
                scene.selected_visual_version.id
                if scene.selected_visual_version is not None
                and scene.selected_visual_version.status == ApprovalStatus.APPROVED
                else None
            )
            for scene in context["scenes"]
        }
        snapshots = []
        for value in reduced:
            state_json = canonical_json(value)
            snapshots.append(
                {
                    "page_id": value["page_id"],
                    "page_no": value["page_no"],
                    "scene_visual_version_id": scene_version_by_key.get(
                        value["scene"]["scene_key"]
                    ),
                    "state_json": state_json,
                    "state_hash": canonical_hash(value),
                    "warnings_json": "[]",
                }
            )
        stored_events = [
            {
                **event,
                "payload_json": canonical_json(event.get("payload") or {}),
            }
            for event in events
        ]
        self.repository.complete_compilation(
            compilation=compilation,
            events=stored_events,
            snapshots=snapshots,
        )
        result = self.repository.get_compilation(compilation.id)
        if result is None:
            raise RuntimeError("Continuity compilation disappeared after commit.")
        return result

    # Baselines and events ---------------------------------------------
    def _character_baselines(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        assets_by_owner = context["assets_by_owner"]
        baselines: dict[str, dict[str, Any]] = {}
        for page in context["pages"]:
            for character in page.visual_characters:
                key = character.character_key
                if key in baselines:
                    continue
                outline = character.outline_character
                if outline is None:
                    raise ValueError(f"ScriptCharacter has no outline baseline: {key}")
                baselines[key] = {
                    "character_key": key,
                    "outline_character_id": outline.id,
                    "name": character.name or outline.name,
                    "identity": {
                        "role": outline.role,
                        "background": outline.background,
                        "appearance": outline.appearance,
                        "visual_anchors": outline.visual_anchors,
                        "negative_constraints": outline.negative_constraints,
                    },
                    "hairstyle": outline.default_hairstyle,
                    "outfit": {
                        "variant_id": None,
                        "key": "",
                        "name": "",
                        "description": outline.default_clothing,
                        "garment_components": [],
                        "layer_order": [],
                        "colors": [],
                        "materials": [],
                        "patterns": [],
                        "accessories": [],
                        "trigger_tokens": [],
                        "negative_constraints": "",
                        "garment_states": {},
                        "conditions": {},
                        "assets": [],
                    },
                    "accessories": {
                        "description": outline.default_accessories,
                        "states": {},
                    },
                    "conditions": {},
                    "held_props": [],
                    "visual_anchors": character.visual_anchors,
                    "negative_constraints": character.negative_constraints,
                    "identity_assets": assets_by_owner.get(
                        (VisualEntityType.CHARACTER.value, outline.id), []
                    ),
                }
        return baselines

    def _scene_baselines(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        assets_by_owner = context["assets_by_owner"]
        result: dict[str, dict[str, Any]] = {}
        for scene in context["scenes"]:
            version = scene.selected_visual_version
            approved_version = (
                version if version is not None and version.status == ApprovalStatus.APPROVED else None
            )
            result[scene.scene_key] = {
                "scene_key": scene.scene_key,
                "script_scene_id": scene.id,
                "name": scene.name,
                "location_type": scene.location_type,
                "time": scene.time_of_day,
                "lighting": scene.lighting,
                "weather": scene.weather,
                "environment_details": scene.environment_details,
                "color_palette": self._loads_list(approved_version.color_palette_json)
                if approved_version
                else scene.color_palette,
                "visual_anchors": scene.visual_anchors,
                "negative_constraints": scene.negative_constraints,
                "visual_version_id": approved_version.id if approved_version else None,
                "landmarks": self._loads_list(approved_version.landmarks_json)
                if approved_version
                else [],
                "spatial_relations": self._loads_object(approved_version.spatial_relations_json)
                if approved_version
                else {},
                "object_states": self._loads_object(approved_version.object_states_json)
                if approved_version
                else {},
                "light_states": self._loads_object(approved_version.lighting_state_json)
                if approved_version
                else {},
                "camera_presets": self._loads_list(approved_version.camera_presets_json)
                if approved_version
                else [],
                "assets": assets_by_owner.get(
                    (VisualEntityType.SCENE.value, approved_version.id), []
                )
                if approved_version
                else [],
            }
        return result

    def _section_boundary_events(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        last_signature: dict[str, tuple[Any, ...]] = {}
        outfit_assets = context["assets_by_owner"]
        for page in context["pages"]:
            for character in sorted(page.visual_characters, key=lambda item: item.character_key):
                outfit = (
                    character.outfit_variant
                    if character.outfit_variant is not None
                    and character.outfit_variant.status == ApprovalStatus.APPROVED
                    else None
                )
                outline = character.outline_character
                effective_hairstyle = self._stable_section_feature(
                    character.current_hairstyle,
                    outline.default_hairstyle if outline else "",
                )
                if outfit is not None:
                    effective_clothing = ", ".join(
                        str(value) for value in self._loads_list(outfit.garment_components_json)
                    ) or outfit.name
                    effective_accessories = ", ".join(
                        str(value) for value in self._loads_list(outfit.accessories_json)
                    )
                else:
                    effective_clothing = self._stable_section_feature(
                        character.current_clothing,
                        outline.default_clothing if outline else "",
                    )
                    effective_accessories = self._stable_section_feature(
                        character.current_accessories,
                        outline.default_accessories if outline else "",
                    )
                signature = (
                    effective_hairstyle,
                    outfit.id if outfit else None,
                    effective_clothing,
                    effective_accessories,
                    character.current_state,
                    character.visual_anchors,
                    character.negative_constraints,
                )
                if last_signature.get(character.character_key) == signature:
                    continue
                last_signature[character.character_key] = signature
                if effective_hairstyle:
                    events.append(
                        self._system_event(
                            page.page_no,
                            ContinuityEventType.SET_HAIRSTYLE,
                            character.character_key,
                            {"value": effective_hairstyle},
                        )
                    )
                outfit_payload = (
                    self._outfit_state_payload(
                        outfit,
                        outfit_assets.get(
                            (VisualEntityType.OUTFIT.value, outfit.id), []
                        ),
                    )
                    if outfit
                    else {
                        "outfit_variant_id": None,
                        "outfit_key": "",
                        "name": "",
                        "description": effective_clothing,
                        "garment_components": [],
                        "layer_order": [],
                        "colors": [],
                        "materials": [],
                        "patterns": [],
                        "accessories": [],
                        "trigger_tokens": [],
                        "negative_constraints": "",
                        "assets": [],
                    }
                )
                outfit_payload["character_negative_constraints"] = (
                    character.negative_constraints
                )
                outfit_payload["character_visual_anchors"] = character.visual_anchors
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_OUTFIT,
                        character.character_key,
                        outfit_payload,
                    )
                )
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_ACCESSORY,
                        character.character_key,
                        {
                            "accessory_key": "__description__",
                            "value": effective_accessories,
                        },
                    )
                )
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_CHARACTER_CONDITION,
                        character.character_key,
                        {
                            "condition_key": "section_state",
                            "value": character.current_state,
                        },
                    )
                )
        return events

    @staticmethod
    def _stable_section_feature(current: Any, default: Any) -> str:
        """把湿污、凌乱和持有位置等后缀从基础造型版本中分离。"""

        current_text = str(current or "").strip()
        default_text = str(default or "").strip()
        if not current_text:
            return default_text
        if not default_text:
            return current_text

        def head(value: str) -> str:
            for separator in ("，", ",", "。", "；", ";", "（", "("):
                value = value.split(separator, 1)[0]
            return "".join(value.casefold().split())

        current_head = head(current_text)
        default_head = head(default_text)
        shorter = min(len(current_head), len(default_head))
        longer = max(len(current_head), len(default_head), 1)
        if current_head == default_head or (
            shorter / longer >= 0.8
            and (current_head in default_head or default_head in current_head)
        ):
            return default_text
        return current_text

    @staticmethod
    def _system_event(
        page_no: int,
        event_type: ContinuityEventType,
        target_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "page_no": page_no,
            "sequence_no": 0,
            "event_type": event_type.value,
            "target_type": ContinuityTargetType.CHARACTER.value,
            "target_key": target_key,
            "timing": ContinuityEventTiming.BEFORE_PAGE.value,
            "payload": payload,
            "source": ContinuityEventSource.SYSTEM.value,
        }

    def _normalize_events(
        self,
        events: list[dict[str, Any]],
        *,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        pages_by_no = {page.page_no: page for page in context["pages"]}
        character_keys = {
            character.character_key
            for page in context["pages"]
            for character in page.visual_characters
        }
        scene_keys = {scene.scene_key for scene in context["scenes"]}
        outfits_by_id = {item.id: item for item in context["outfits"]}
        assets_by_owner = context["assets_by_owner"]
        locked_accessory_targets = {
            str(raw.get("target_key", "")).strip()
            for raw in events
            if raw.get("event_type") == ContinuityEventType.SET_ACCESSORY.value
            and raw.get("source") == ContinuityEventSource.SYSTEM.value
            and str((raw.get("payload") or {}).get("accessory_key", "")).strip()
            == "__description__"
            and str((raw.get("payload") or {}).get("value", "")).strip()
        }
        normalized: list[dict[str, Any]] = []
        for raw in events:
            page_no = int(raw.get("page_no", 0))
            if page_no not in pages_by_no:
                raise ValueError(f"Continuity event page_no not found: {page_no}")
            event_type = ContinuityEventType(raw["event_type"])
            target_type = ContinuityTargetType(raw["target_type"])
            target_key = str(raw.get("target_key", "")).strip()
            if target_type == ContinuityTargetType.CHARACTER and target_key not in character_keys:
                raise ValueError(f"Continuity character target not found: {target_key}")
            if target_type == ContinuityTargetType.SCENE and target_key not in scene_keys:
                raise ValueError(f"Continuity scene target not found: {target_key}")
            source = ContinuityEventSource(
                raw.get("source", ContinuityEventSource.LLM.value)
            )
            if (
                event_type == ContinuityEventType.SET_ACCESSORY
                and source == ContinuityEventSource.LLM
                and target_key in locked_accessory_targets
            ):
                # 已批准视觉设定中的固定配件由 system event 管理。LLM 只从脚本抽取
                # 持久变化，不能用自然语言动作覆盖“唯一且不可取下”等硬锚点。
                continue
            payload = dict(raw.get("payload") or {})
            if event_type == ContinuityEventType.SET_OUTFIT and payload.get("outfit_variant_id"):
                variant_id = int(payload["outfit_variant_id"])
                variant = outfits_by_id.get(variant_id)
                if variant is None:
                    raise ValueError(f"Continuity outfit variant not found: {variant_id}")
                payload.update(
                    self._outfit_state_payload(
                        variant,
                        assets_by_owner.get(
                            (VisualEntityType.OUTFIT.value, variant.id), []
                        ),
                    )
                )
            elif (
                event_type == ContinuityEventType.SET_OUTFIT
                and source != ContinuityEventSource.SYSTEM
            ):
                # LLM/人工事件不能注入资产或角色锚点；无获批 variant 时只保留文字变化。
                payload = {
                    "outfit_variant_id": None,
                    "outfit_key": str(payload.get("outfit_key", "")).strip(),
                    "description": str(payload.get("description", "")).strip(),
                    "assets": [],
                }
            if source != ContinuityEventSource.SYSTEM:
                payload.pop("character_visual_anchors", None)
                payload.pop("character_negative_constraints", None)
            normalized.append(
                {
                    "page_no": page_no,
                    "sequence_no": int(raw.get("sequence_no", 0)),
                    "event_type": event_type.value,
                    "target_type": target_type.value,
                    "target_key": target_key,
                    "timing": ContinuityEventTiming(
                        raw.get("timing", ContinuityEventTiming.AFTER_PAGE.value)
                    ).value,
                    "payload": payload,
                    "source": source.value,
                }
            )
        source_order = {"system": 0, "manual": 1, "llm": 2}
        timing_order = {"before_page": 0, "after_page": 1}
        normalized.sort(
            key=lambda item: (
                item["page_no"],
                timing_order[item["timing"]],
                source_order[item["source"]],
                item["sequence_no"],
                item["event_type"],
            )
        )
        # 分段锁定值由 system event 表达，同一语义槽位内它优先于人工/LLM；
        # 其它带不同 condition/object/prop key 的事件仍会完整保留。
        discriminator_keys = {
            ContinuityEventType.SET_ACCESSORY.value: "accessory_key",
            ContinuityEventType.SET_GARMENT_STATE.value: "garment_key",
            ContinuityEventType.SET_CLOTHING_CONDITION.value: "condition_key",
            ContinuityEventType.SET_CHARACTER_CONDITION.value: "condition_key",
            ContinuityEventType.PICK_UP_PROP.value: "prop_key",
            ContinuityEventType.DROP_PROP.value: "prop_key",
            ContinuityEventType.TRANSFER_PROP.value: "prop_key",
            ContinuityEventType.SET_DOOR_STATE.value: "door_key",
            ContinuityEventType.SET_OBJECT_STATE.value: "object_key",
            ContinuityEventType.BREAK_OBJECT.value: "object_key",
        }
        deduplicated: list[dict[str, Any]] = []
        seen_slots: set[tuple[Any, ...]] = set()
        for item in normalized:
            discriminator_key = discriminator_keys.get(item["event_type"])
            discriminator = (
                str(item["payload"].get(discriminator_key, "")).strip()
                if discriminator_key
                else ""
            )
            slot = (
                item["page_no"],
                item["timing"],
                item["event_type"],
                item["target_type"],
                item["target_key"],
                discriminator,
            )
            if slot in seen_slots:
                continue
            seen_slots.add(slot)
            deduplicated.append(item)
        counters: dict[int, int] = defaultdict(int)
        for item in deduplicated:
            counters[item["page_no"]] += 1
            item["sequence_no"] = counters[item["page_no"]]
        return deduplicated

    # Prompt specs ------------------------------------------------------
    def _compile_prompt_spec(
        self,
        *,
        page: ComicPage,
        snapshot: VisualStateSnapshot,
        shot_plan: PageShotPlan,
        prompt_type: ImagePromptType,
        style_profile: StyleProfile | None,
        style_assets: list[dict[str, Any]],
        negative_preset: ImagePromptPreset | None,
        generation_mode: GenerationMode,
    ) -> ImageSpec:
        snapshot_data = self._loads_object(snapshot.state_json)
        plan_data = self._loads_object(shot_plan.plan_json)
        style_data = (
            self._style_payload(style_profile, style_assets)
            if style_profile is not None
            else None
        )
        combined_source_hash = self._image_spec_source_hash(
            snapshot_hash=snapshot.state_hash,
            plan_hash=shot_plan.plan_hash,
            prompt_type=prompt_type,
            style_profile=style_profile,
            style_assets=style_assets,
            negative_preset=negative_preset,
        )
        compiler = compiler_for_prompt_type(prompt_type)
        compiled = compiler.compile(
            snapshot=snapshot_data,
            shot_plan=plan_data,
            style_profile=style_data,
            negative_prompts=self._negative_prompt_payload(negative_preset),
            generation_mode=generation_mode,
            source_hash=combined_source_hash,
        )
        return self.repository.add_image_spec(
            page_id=page.id,
            snapshot_id=snapshot.id,
            shot_plan_id=shot_plan.id,
            prompt_type=prompt_type,
            style_profile_id=style_profile.id if style_profile else None,
            negative_prompt_preset_id=negative_preset.id if negative_preset else None,
            generation_mode=generation_mode,
            spec_json=canonical_json(compiled.spec),
            positive_prompt=compiled.positive_prompt,
            negative_prompt=compiled.negative_prompt,
            required_capabilities_json=canonical_json(compiled.required_capabilities),
            warnings_json=canonical_json(compiled.warnings),
            source_hash=combined_source_hash,
            spec_hash=compiled.spec_hash,
            compiler_key=compiler.compiler_key,
            compiler_version=compiler.compiler_version,
        )

    # Payload helpers ---------------------------------------------------
    def _image_spec_source_hash(
        self,
        *,
        snapshot_hash: str,
        plan_hash: str,
        prompt_type: ImagePromptType,
        style_profile: StyleProfile | None,
        style_assets: list[dict[str, Any]],
        negative_preset: ImagePromptPreset | None,
    ) -> str:
        """完整来源 Hash 包含 Prompt 类型、编译器、风格资产和负向 Prompt 版本。"""

        compiler = compiler_for_prompt_type(prompt_type)
        return canonical_hash(
            {
                "snapshot_hash": snapshot_hash,
                "plan_hash": plan_hash,
                "prompt_type": prompt_type.value,
                "compiler": {
                    "key": compiler.compiler_key,
                    "version": compiler.compiler_version,
                },
                "style": (
                    self._style_payload(style_profile, style_assets)
                    if style_profile is not None
                    else None
                ),
                "negative_prompt_preset": (
                    {
                        "id": negative_preset.id,
                        "kind": negative_preset.kind.value,
                        "tag_content_hash": canonical_hash(negative_preset.tag_content),
                        "natural_language_content_hash": canonical_hash(
                            negative_preset.natural_language_content
                        ),
                    }
                    if negative_preset is not None
                    else None
                ),
            }
        )

    def _shot_plan_source_hash(
        self,
        *,
        plan: dict[str, Any],
        planner_preset: ImagePromptPreset | None,
        planner_model: str | None,
    ) -> str:
        """镜头计划 Hash 同时锁定计划内容和产生它的 Agent/Prompt/模型。"""

        return canonical_hash(
            {
                "plan": plan,
                "planner_preset": (
                    {
                        "id": planner_preset.id,
                        "kind": planner_preset.kind.value,
                        "content_hash": canonical_hash(planner_preset.content),
                    }
                    if planner_preset is not None
                    else None
                ),
                "agent": {
                    "key": "shot_planner_agent",
                    "version": ShotPlannerAgent.VERSION,
                    "prompt_version": self.PROMPT_VERSION,
                    "llm_model": planner_model,
                },
            }
        )

    def _continuity_source_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "task_id": context["task"].id,
            "pages": [self._page_payload(page) for page in context["pages"]],
            "characters": self._character_agent_payloads(context["pages"]),
            "scenes": [self._scene_source_payload(scene) for scene in context["scenes"]],
            "outfits": [
                self._outfit_payload(
                    item,
                    context["assets_by_owner"].get(
                        (VisualEntityType.OUTFIT.value, item.id), []
                    ),
                )
                for item in context["outfits"]
            ],
            "assets": context["asset_payloads"],
            "agent": {
                "key": "continuity_event_agent",
                "version": ContinuityEventAgent.VERSION,
                "prompt_hash": canonical_hash(
                    PromptLoader.load("continuity_event_prompt.md")
                ),
                "llm_config_id": context["llm_config_id"],
                "llm_model": context["llm_model"],
            },
            "prompt_version": self.PROMPT_VERSION,
            "reducer_version": VisualStateReducer.VERSION,
        }

    @staticmethod
    def _page_payload(page: ComicPage) -> dict[str, Any]:
        return {
            "page_id": page.id,
            "page_no": page.page_no,
            "section_no": page.section.section_no if page.section else None,
            "scene_key": page.script_scene.scene_key if page.script_scene else "",
            "character_keys": sorted(
                character.character_key for character in page.visual_characters
            ),
            "summary": page.summary or "",
            "characters": page.characters or "",
            "clothing": page.clothing or "",
            "scene": page.scene or "",
            "composition": page.composition or "",
            "character_action": page.character_action or "",
            # dialogue 仅作为 ShotPlanner 理解剧情的上下文，编译器不会写进 Prompt。
            "dialogue": page.dialogue or "无",
        }

    @staticmethod
    def _reducer_page_payload(page: ComicPage) -> dict[str, Any]:
        return {
            "page_id": page.id,
            "page_no": page.page_no,
            "scene_key": page.script_scene.scene_key if page.script_scene else "",
            "character_keys": sorted(
                character.character_key for character in page.visual_characters
            ),
        }

    @staticmethod
    def _character_agent_payloads(pages: list[ComicPage]) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        for page in pages:
            for character in page.visual_characters:
                if character.id in seen:
                    continue
                seen[character.id] = {
                    "character_key": character.character_key,
                    "name": character.name,
                    "section_no": character.section.section_no,
                    "current_hairstyle": character.current_hairstyle,
                    "current_clothing": character.current_clothing,
                    "current_accessories": character.current_accessories,
                    "current_state": character.current_state,
                    "temporary_changes": character.temporary_changes,
                    "outfit_variant_id": character.outfit_variant_id,
                }
        return list(seen.values())

    @staticmethod
    def _scene_text_payload(scene: ScriptScene) -> dict[str, Any]:
        return {
            "scene_key": scene.scene_key,
            "name": scene.name,
            "time": scene.time_of_day,
            "weather": scene.weather,
            "visual_anchors": scene.visual_anchors,
        }

    def _scene_source_payload(self, scene: ScriptScene) -> dict[str, Any]:
        payload = self._scene_text_payload(scene)
        payload.update(
            {
                "lighting": scene.lighting,
                "environment_details": scene.environment_details,
                "color_palette": scene.color_palette,
                "negative_constraints": scene.negative_constraints,
                "selected_visual_version": (
                    {
                        "id": scene.selected_visual_version.id,
                        "version": scene.selected_visual_version.version,
                        "status": scene.selected_visual_version.status.value,
                        "landmarks": self._loads_list(
                            scene.selected_visual_version.landmarks_json
                        ),
                        "spatial_relations": self._loads_object(
                            scene.selected_visual_version.spatial_relations_json
                        ),
                        "camera_presets": self._loads_list(
                            scene.selected_visual_version.camera_presets_json
                        ),
                        "object_states": self._loads_object(
                            scene.selected_visual_version.object_states_json
                        ),
                        "color_palette": self._loads_list(
                            scene.selected_visual_version.color_palette_json
                        ),
                        "lighting_state": self._loads_object(
                            scene.selected_visual_version.lighting_state_json
                        ),
                    }
                    if scene.selected_visual_version
                    else None
                ),
            }
        )
        return payload

    def _outfit_payload(
        self,
        item: OutfitVariant,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "outline_character_id": item.outline_character_id,
            "key": item.key,
            "version": item.version,
            "name": item.name,
            "status": item.status.value,
            "garment_components": self._loads_list(item.garment_components_json),
            "layer_order": self._loads_list(item.layer_order_json),
            "colors": self._loads_list(item.colors_json),
            "materials": self._loads_list(item.materials_json),
            "patterns": self._loads_list(item.patterns_json),
            "accessories": self._loads_list(item.accessories_json),
            "trigger_tokens": self._loads_list(item.trigger_tokens_json),
            "negative_constraints": item.negative_constraints,
            "assets": assets,
        }

    def _outfit_description(self, item: OutfitVariant) -> str:
        values = (
            self._loads_list(item.garment_components_json)
            + self._loads_list(item.colors_json)
            + self._loads_list(item.materials_json)
            + self._loads_list(item.patterns_json)
        )
        return ", ".join(str(value) for value in values if str(value).strip()) or item.name

    def _outfit_state_payload(
        self,
        item: OutfitVariant,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把获批服装版本展开为 reducer 可锁定的完整结构。"""

        payload = self._outfit_payload(item, assets)
        return {
            "outfit_variant_id": item.id,
            "outfit_key": item.key,
            "name": item.name,
            "description": self._outfit_description(item),
            "garment_components": payload["garment_components"],
            "layer_order": payload["layer_order"],
            "colors": payload["colors"],
            "materials": payload["materials"],
            "patterns": payload["patterns"],
            "accessories": payload["accessories"],
            "trigger_tokens": payload["trigger_tokens"],
            "negative_constraints": item.negative_constraints,
            "assets": assets,
        }

    @staticmethod
    def _asset_payload(asset: VisualAsset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "entity_type": asset.entity_type.value,
            "entity_id": asset.entity_id,
            "entity_key": asset.entity_key,
            "role": asset.role.value,
            "storage_kind": asset.storage_kind.value,
            "local_path": asset.local_path,
            "renderer_locator": asset.renderer_locator,
            "sha256": asset.sha256,
            "version": asset.version,
        }

    def _style_payload(
        self,
        item: StyleProfile,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "key": item.key,
            "version": item.version,
            "name": item.name,
            "positive_tag": item.positive_tag,
            "negative_tag": item.negative_tag,
            "positive_natural_language": item.positive_natural_language,
            "negative_natural_language": item.negative_natural_language,
            "color_palette": self._loads_list(item.color_palette_json),
            "lighting": item.lighting,
            "status": item.status.value,
            "assets": assets,
        }

    @staticmethod
    def _negative_prompt_payload(item: ImagePromptPreset | None) -> dict[str, str]:
        """负向预设按两种基础表达返回；混合型由编译器按固定顺序合并。"""

        if item is None:
            return {"tag": "", "natural_language": ""}
        return {
            "tag": item.tag_content,
            "natural_language": item.natural_language_content,
        }

    @staticmethod
    def _available_controls(snapshot: dict[str, Any]) -> list[str]:
        roles = {
            asset.get("role")
            for asset in (snapshot.get("scene") or {}).get("assets", [])
        }
        for character in snapshot.get("characters", []):
            roles.update(asset.get("role") for asset in character.get("identity_assets", []))
            roles.update(
                asset.get("role") for asset in (character.get("outfit") or {}).get("assets", [])
            )
        controls = {CONTROL_ROLES[role] for role in roles if role in CONTROL_ROLES}
        if len(snapshot.get("characters", [])) > 1:
            controls.add("regional_condition")
        return sorted(controls)

    @staticmethod
    def _snapshot_payload(snapshot: VisualStateSnapshot, page: ComicPage) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "state": ImageSpecService._loads_object(snapshot.state_json),
            "state_hash": snapshot.state_hash,
            "warnings": ImageSpecService._loads_list(snapshot.warnings_json),
            "created_at": snapshot.created_at.isoformat(),
        }

    @staticmethod
    def _shot_plan_payload(plan: PageShotPlan, page: ComicPage) -> dict[str, Any]:
        return {
            "id": plan.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "plan": ImageSpecService._loads_object(plan.plan_json),
            "plan_hash": plan.plan_hash,
            "created_at": plan.created_at.isoformat(),
        }

    @staticmethod
    def _spec_payload(spec: ImageSpec, page: ComicPage) -> dict[str, Any]:
        return {
            "id": spec.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "snapshot_id": spec.snapshot_id,
            "shot_plan_id": spec.shot_plan_id,
            "prompt_type": spec.prompt_type.value,
            "generation_mode": spec.generation_mode.value,
            "spec": ImageSpecService._loads_object(spec.spec_json),
            "positive_prompt": spec.positive_prompt,
            "negative_prompt": spec.negative_prompt,
            "required_capabilities": ImageSpecService._loads_list(
                spec.required_capabilities_json
            ),
            "warnings": ImageSpecService._loads_list(spec.warnings_json),
            "source_hash": spec.source_hash,
            "spec_hash": spec.spec_hash,
            "compiler_key": spec.compiler_key,
            "compiler_version": spec.compiler_version,
            "created_at": spec.created_at.isoformat(),
        }

    @staticmethod
    def _event_from_orm(item) -> dict[str, Any]:
        return {
            "page_no": item.page.page_no,
            "sequence_no": item.sequence_no,
            "event_type": item.event_type.value,
            "target_type": item.target_type.value,
            "target_key": item.target_key,
            "timing": item.timing.value,
            "payload": ImageSpecService._loads_object(item.payload_json),
            "source": item.source.value,
        }

    @staticmethod
    def _loads_object(value: str) -> dict[str, Any]:
        import json

        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Stored visual JSON must be an object.")
        return parsed

    @staticmethod
    def _loads_list(value: str) -> list[Any]:
        import json

        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("Stored visual JSON must be an array.")
        return parsed
