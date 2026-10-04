import asyncio
from collections import defaultdict
from copy import deepcopy
from typing import Any, AsyncIterator

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
    GenerationMode,
    ImagePromptPresetKind,
    ImagePromptType,
    ImageSpecStaleReason,
    PromptLanguage,
    PageScriptReviewStatus,
    ScriptGenerationTaskStatus,
    VisualAssetRole,
    VisualEntityType,
    SystemPromptKey,
)
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_compilers import compiler_for_prompt_type
from backend.services.reference_selection_service import ReferenceSelectionService
from backend.utils.json_utils import canonical_hash, canonical_json
from backend.models.scene_conditions import SCENE_DEFINITION_VERSION, page_scene_conditions
from backend.utils.prompt_loader import PromptLoader
from backend.utils.system_prompt_catalog import default_model_system_prompt, model_prompt_overrides


CONTROL_ROLES = {
    VisualAssetRole.POSE.value: "pose",
    VisualAssetRole.DEPTH.value: "depth",
    VisualAssetRole.CANNY.value: "canny",
    VisualAssetRole.LINEART.value: "lineart",
}


class ImageSpecService:
    """按页组合只读视觉设定、ShotPlan 和三类 Prompt，不推演跨页状态。"""

    PROMPT_VERSION = "5"
    PAGE_CONTEXT_VERSION = "page-context-v3"

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
        page_ids: list[int] | None = None,
        prompt_language: PromptLanguage = PromptLanguage.ORIGINAL,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """按需编译指定页面；未变化页面复用镜头和三类规格。"""

        # 不再让历史偏好把可选参考图变成必须项；旧模式字段只保留溯源兼容。
        generation_mode = GenerationMode.PREVIEW
        context = self._prepare_context(
            task_id=task_id,
            style_profile_id=style_profile_id,
            shot_planner_preset_id=shot_planner_preset_id,
            negative_prompt_preset_id=negative_prompt_preset_id,
            page_ids=page_ids,
        )
        context["prompt_language"] = prompt_language
        pages: list[ComicPage] = context["pages"]
        yield "start", {
            "task_id": task_id,
            "total_pages": len(pages),
            "prompt_types": [item.value for item in ImagePromptType],
            "generation_mode": generation_mode.value,
            "prompt_language": prompt_language.value,
        }

        # 旧参数仅为请求兼容保留；每页设定直接构建，无事件提取或跨页归约。
        compilation = self._compile_page_context(context)
        snapshots_by_page = {item.page_id: item for item in compilation.snapshots}
        total_specs = len(pages) * len(ImagePromptType)
        for page in pages:
            snapshot = snapshots_by_page[page.id]
            yield "snapshot", self._snapshot_payload(snapshot, page)

        normalized_concurrency = max(1, min(concurrency, 20))
        semaphore = asyncio.Semaphore(normalized_concurrency)
        planner = None

        async def plan_page(
            page: ComicPage,
        ) -> tuple[ComicPage, dict[str, Any], PageShotPlan | None, dict[str, str] | None]:
            nonlocal planner
            async with semaphore:
                snapshot = snapshots_by_page[page.id]
                existing = self._reusable_shot_plan(
                    page=page,
                    snapshot=snapshot,
                    context=context,
                )
                snapshot_data = self._loads_object(snapshot.state_json)
                # 完全复用时不初始化模型，避免已准备好的页面仍要求模型凭据。
                if planner is None and (existing is None or prompt_language != PromptLanguage.ORIGINAL):
                    planner = ShotPlannerAgent(
                        system_prompt=context["planner_system_prompt"],
                        language_system_prompt=context["language_system_prompt"],
                    )
                page_data = self._page_payload(page)
                controls = self._available_controls(snapshot_data)
                plan = self._loads_object(existing.plan_json) if existing else await planner.plan(
                    page=page_data,
                    snapshot=snapshot_data,
                    available_controls=controls,
                )
                translated = None
                if prompt_language != PromptLanguage.ORIGINAL:
                    # 译文只作用于最终四个组件；同页三类表达共用一次转换。
                    base = compiler_for_prompt_type(ImagePromptType.HYBRID).compile(
                        snapshot=snapshot_data, shot_plan=plan, style_profile=None,
                        negative_prompts=self._negative_prompt_payload(context["negative_preset"]),
                        generation_mode=generation_mode, source_hash="",
                    )
                    components = {key: base.spec["prompt"][key] for key in (
                        "tag_text", "natural_language_text", "negative_tag_text", "negative_natural_language_text",
                    )}
                    try:
                        translated = await planner.translate_prompt_components(components, prompt_language)
                    except Exception as exc:
                        raise AppError("image_spec.prompt_language_failed", debug_message=str(exc)) from exc
                return page, plan, existing, translated

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
            ) -> tuple[ComicPage, dict[str, Any] | None, PageShotPlan | None, dict[str, str] | None, Exception | None]:
                try:
                    planned_page, plan_data, existing_plan, translated = await plan_page(page)
                    return planned_page, plan_data, existing_plan, translated, None
                except Exception as exc:  # 单页模型失败不取消其它页面
                    return page, None, None, None, exc

            planning_tasks = [
                asyncio.create_task(guarded_plan(page)) for page in pending_pages
            ]
            for completed_task in asyncio.as_completed(planning_tasks):
                page, plan_data, existing_plan, translated, plan_error = await completed_task
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
                            planner_system_prompt=context["planner_system_prompt"],
                            global_system_prompt_hash=context["global_system_prompt_hash"],
                        ),
                        planner_model=context["llm_model"],
                        prompt_version=self.PROMPT_VERSION,
                    )
                    shot_plan_payload = self._shot_plan_payload(shot_plan, page)
                    shot_plan_payload["reused"] = existing_plan is not None
                    yield "shot_plan", shot_plan_payload

                    reference_plan = ReferenceSelectionService.select(
                        snapshot=self._loads_object(snapshot.state_json),
                        shot_plan=plan_data,
                    )

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
                            reference_plan=reference_plan,
                            prompt_language=prompt_language,
                            prompt_components=translated,
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
            snapshot_hash=snapshot.state_hash,
        ):
            if shot_plan.planner_preset_id != context["planner_preset"].id:
                continue
            plan = self._loads_object(shot_plan.plan_json)
            current_hash = self._shot_plan_source_hash(
                plan=plan,
                planner_preset=context["planner_preset"],
                planner_model=context["llm_model"],
                planner_system_prompt=context["planner_system_prompt"],
                global_system_prompt_hash=context["global_system_prompt_hash"],
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
                shot_plan.snapshot.state_hash != snapshot.state_hash
                or shot_plan.planner_preset_id != expected_planner_id
            ):
                continue
            current_plan_hash = self._shot_plan_source_hash(
                plan=self._loads_object(shot_plan.plan_json),
                planner_preset=context["planner_preset"],
                planner_model=context["llm_model"],
                planner_system_prompt=context["planner_system_prompt"],
                global_system_prompt_hash=context["global_system_prompt_hash"],
            )
            if shot_plan.plan_hash != current_plan_hash:
                continue
            valid = True
            for spec in typed_specs:
                if (
                    spec.snapshot.state_hash != snapshot.state_hash
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
                    prompt_language=context["prompt_language"],
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
        """批量任务 Hash 用于审计本次页面输入快照、Prompt 与编译器组合。"""

        return canonical_hash(
            {
                "schema_version": 1,
                "page_context_source_hash": compilation.source_hash,
                "snapshots": [
                    {
                        "page_id": item.page_id,
                        "state_hash": item.state_hash,
                    }
                    for item in sorted(compilation.snapshots, key=lambda value: value.page_id)
                ],
                "generation_mode": generation_mode.value,
                "prompt_language": context["prompt_language"].value,
                "style": (
                    self._style_payload(context["style"], context["style_assets"])
                    if context["style"] is not None
                    else None
                ),
                "planner_preset": {
                    "id": context["planner_preset"].id,
                    "content_hash": canonical_hash(context["planner_system_prompt"]),
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
        specs = self.repository.list_latest_specs(task_id=task_id, prompt_type=prompt_type)
        if not specs:
            return []
        # 与出图前校验使用相同的实时输入和 Hash；历史完成数不代表当前可用数。
        context = self._prepare_context(
            task_id=task_id, style_profile_id=None, shot_planner_preset_id=None,
            negative_prompt_preset_id=None, require_review=False,
        )
        current = {item["page_id"]: item for item in self._build_page_contexts(context)}
        result = []
        for spec in specs:
            payload = self._spec_payload(spec, pages[spec.page_id])
            reasons = self.spec_stale_reasons(spec, current[spec.page_id])
            payload.update(spec_stale=bool(reasons), stale_reasons=reasons)
            result.append(payload)
        return result

    def spec_stale_reasons(
        self, spec: ImageSpec, current_context: dict[str, Any],
    ) -> list[ImageSpecStaleReason]:
        """只读比较来源，按用户可处理的输入分类解释过期，不修改历史快照。"""

        reasons = []
        if not self.page_context_is_current(spec.snapshot, canonical_hash(current_context)):
            previous = self._loads_object(spec.snapshot.state_json)
            for fields, reason in (
                (("page_script", "scene_conditions"), ImageSpecStaleReason.PAGE_SCRIPT_CHANGED),
                (("characters",), ImageSpecStaleReason.CHARACTER_INPUTS_CHANGED),
                (("scene",), ImageSpecStaleReason.SCENE_INPUTS_CHANGED),
                (("prop_catalog",), ImageSpecStaleReason.PROP_INPUTS_CHANGED),
            ):
                if any(previous.get(field) != current_context.get(field) for field in fields):
                    reasons.append(reason)
            if not reasons:
                reasons.append(ImageSpecStaleReason.INPUTS_CHANGED)
        if spec.source_hash != self.current_image_spec_source_hash(spec):
            reasons.append(ImageSpecStaleReason.PROMPT_RULES_CHANGED)
        return reasons

    def current_page_context_source_hash(self, task_id: int) -> str:
        """保留整批输入 Hash 用于历史审计，生成过期校验使用逐页 Hash。"""

        context = self._prepare_context(
            task_id=task_id,
            style_profile_id=None,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
        )
        return canonical_hash(self._page_context_source_payload(context))

    def current_page_context_hashes(
        self, task_id: int, page_ids: list[int] | None = None,
    ) -> dict[int, str]:
        """从实时绑定重新构建页面来源；其它页修改不使本页规格过期。"""

        context = self._prepare_context(
            task_id=task_id, style_profile_id=None,
            shot_planner_preset_id=None, negative_prompt_preset_id=None,
            page_ids=page_ids,
            require_review=False,
        )
        return {
            value["page_id"]: canonical_hash(value)
            for value in self._build_page_contexts(context)
        }

    def current_image_spec_source_hash(self, spec: ImageSpec) -> str:
        """按当前 Prompt 类型、风格和预设重算来源，用于生成前判定 stale。"""
        # 历史 spec 风格字段保留；新编译来源不再读取或施加风格。
        style = None
        style_assets: list[dict[str, Any]] = []
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
            prompt_language=PromptLanguage(self._loads_object(spec.spec_json).get("prompt_language", "original")),
        )

    def page_context_is_current(
        self, snapshot: VisualStateSnapshot, current_context_hash: str,
    ) -> bool:
        """兼容输入结构未变的 v2 标记；真实设定变化和历史事件快照仍要求重新准备。"""

        if snapshot.state_hash == current_context_hash:
            return True
        state = self._loads_object(snapshot.state_json)
        if (
            self.PAGE_CONTEXT_VERSION != "page-context-v3"
            or state.get("context_builder_version") != "page-context-v2"
            or canonical_hash(state) != snapshot.state_hash
        ):
            return False
        # 只替换已知兼容的标记，再与实时输入的完整 Hash 比较，不改历史记录。
        state["context_builder_version"] = self.PAGE_CONTEXT_VERSION
        return canonical_hash(state) == current_context_hash

    def _prepare_context(
        self,
        *,
        task_id: int,
        style_profile_id: int | None,
        shot_planner_preset_id: int | None,
        negative_prompt_preset_id: int | None,
        page_ids: list[int] | None = None,
        require_review: bool = True,
    ) -> dict[str, Any]:
        """编译要求已审查；只读来源 Hash 查询允许包含待审查页，避免阻塞其它页的有效性展示。"""
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
        if page_ids is not None:
            requested = set(page_ids)
            if not requested or requested - {page.id for page in pages}:
                raise AppError("image_generation.page_scope_invalid", status_code=400)
            pages = [page for page in pages if page.id in requested]
        if not pages:
            raise ValueError(f"Script pages not found for task: {task_id}")
        unreviewed_page_nos = [
            page.page_no
            for page in pages
            if page.script_review_status != PageScriptReviewStatus.PASSED
        ]
        if require_review and unreviewed_page_nos:
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
        # 兼容旧请求中的 style_profile_id，但画面准备不再消费该条件。
        style = None
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
        assets = [
            asset for asset in self.repository.list_project_assets(task.project_id, approved_only=True)
            if asset.entity_type != VisualEntityType.STYLE and asset.role != VisualAssetRole.LORA
        ]
        asset_payloads = [self._asset_payload(asset) for asset in assets]
        assets_by_owner: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for asset in asset_payloads:
            if asset["entity_id"] is not None:
                assets_by_owner[(asset["entity_type"], int(asset["entity_id"]))].append(asset)
        assets_by_subject: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for asset in asset_payloads:
            if asset.get("reference_subject_id") is not None:
                assets_by_subject[int(asset["reference_subject_id"])].append(asset)
        reference_subjects = self.repository.list_project_reference_subjects(task.project_id)
        subject_payloads = {
            subject.id: {
                "id": subject.id, "entity_type": subject.entity_type.value,
                "key": subject.key, "name": subject.name,
                "description": subject.description,
                "negative_constraints": subject.negative_constraints,
            }
            for subject in reference_subjects
        }
        prop_catalog = [
            {
                "id": subject.id, "key": subject.key, "name": subject.name,
                "description": subject.description,
                "negative_constraints": subject.negative_constraints,
                "assets": assets_by_subject.get(subject.id, []),
            }
            for subject in reference_subjects
            if subject.entity_type == VisualEntityType.PROP
        ]
        # 没有目录的历史物品仍可依据准确的 entity_key 关联，不模糊匹配名称。
        props_by_key = {item["key"]: item for item in prop_catalog}
        for asset in asset_payloads:
            if asset["entity_type"] != VisualEntityType.PROP.value or not asset.get("entity_key"):
                continue
            key = str(asset["entity_key"])
            prop = props_by_key.setdefault(key, {"id": None, "key": key, "name": key, "description": "", "negative_constraints": "", "assets": []})
            if not any(value["id"] == asset["id"] for value in prop["assets"]):
                prop["assets"].append(asset)
        prop_catalog = [props_by_key[key] for key in sorted(props_by_key)]
        active_llm = self.repository.get_active_llm_config()
        return {
            "task": task,
            "pages": pages,
            "style": style,
            "style_assets": [],
            "planner_preset": planner_preset,
            "planner_system_prompt": self._planner_system_prompt(planner_preset),
            "language_system_prompt": self._language_system_prompt(),
            "global_system_prompt_hash": self._global_system_prompt_hash(),
            "negative_preset": negative_preset,
            "assets": assets,
            "asset_payloads": asset_payloads,
            "assets_by_owner": assets_by_owner,
            "assets_by_reference_subject": assets_by_subject,
            "reference_subjects": subject_payloads,
            "prop_catalog": prop_catalog,
            "scenes": self.repository.list_task_scenes(task_id),
            "llm_config_id": active_llm.id if active_llm else None,
            "llm_model": active_llm.default_model if active_llm else None,
        }

    def _compile_page_context(self, context: dict[str, Any]) -> ContinuityCompilation:
        """复用历史表保存不可变输入；新记录的 events 始终为空，不需要模型调用。"""

        page_contexts = self._build_page_contexts(context)
        source_hash = canonical_hash(self._page_context_source_payload(context, page_contexts))
        reusable = self.repository.find_reusable_compilation(
            task_id=context["task"].id, source_hash=source_hash,
        )
        if reusable is not None:
            return reusable
        compilation = self.repository.create_compilation(
            task_id=context["task"].id, source_hash=source_hash,
            llm_config_id=None, llm_model=None,
            prompt_version=self.PAGE_CONTEXT_VERSION,
            reducer_version=self.PAGE_CONTEXT_VERSION,
        )
        try:
            return self.repository.complete_compilation(
                compilation=compilation,
                snapshots=[
                    {
                        "page_id": value["page_id"], "page_no": value["page_no"],
                        "scene_visual_version_id": value["scene"]["visual_version_id"],
                        "state_json": canonical_json(value),
                        "state_hash": canonical_hash(value), "warnings_json": "[]",
                    }
                    for value in page_contexts
                ],
            )
        except Exception:
            self.repository.session.rollback()
            self.repository.fail_compilation(
                compilation, error_code="image_spec.compilation_failed",
                error_message="Page context persistence failed.",
            )
            raise

    def _build_page_contexts(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """逐页读取实际绑定，不按角色 key 缓存造型，也不继承上一页临时状态。"""

        scenes = self._scene_baselines(context)
        page_contexts = []
        for page in context["pages"]:
            if page.script_scene is None or page.script_scene.scene_key not in scenes:
                raise ValueError(f"Page {page.page_no} has no bound scene.")
            characters = []
            bindings = []
            for character in sorted(page.visual_characters, key=lambda value: value.character_key):
                outline = character.outline_character
                if outline is None:
                    raise ValueError(f"ScriptCharacter has no outline baseline: {character.character_key}")
                selected_outfit = character.outfit_variant
                outfit = (selected_outfit if selected_outfit is not None
                          and selected_outfit.status == ApprovalStatus.APPROVED else None)
                if outfit is not None:
                    outfit_state = self._outfit_state_payload(
                        outfit, context["assets_by_owner"].get((VisualEntityType.OUTFIT.value, outfit.id), []),
                    )
                    accessories = ", ".join(str(value) for value in outfit_state["accessories"])
                else:
                    outfit_state = {
                        "variant_id": None, "key": "", "name": "",
                        "description": character.current_clothing.strip() or outline.default_clothing.strip(),
                        "garment_components": [], "layer_order": [], "colors": [],
                        "materials": [], "patterns": [], "accessories": [],
                        "trigger_tokens": [], "negative_constraints": "", "assets": [],
                        "garment_states": {}, "conditions": {},
                    }
                    accessories = character.current_accessories.strip() or outline.default_accessories.strip()
                characters.append({
                    "character_key": character.character_key,
                    "outline_character_id": outline.id,
                    "name": character.name or outline.name,
                    "identity": {
                        "role": outline.role, "background": outline.background,
                        "appearance": outline.appearance,
                        "negative_constraints": outline.negative_constraints,
                    },
                    "hairstyle": character.current_hairstyle.strip() or outline.default_hairstyle.strip(),
                    "outfit": outfit_state,
                    "accessories": {"description": accessories, "states": {}},
                    "negative_constraints": character.negative_constraints,
                    "identity_assets": context["assets_by_owner"].get((VisualEntityType.CHARACTER.value, outline.id), []),
                    # 保留旧 JSON 读取形状，但新流程不维护持有者或持久状态。
                    "conditions": {}, "held_props": [], "held_prop_assets": [],
                    "section_context": {
                        "current_state": character.current_state,
                        "emotion": character.emotion,
                        "temporary_changes": character.temporary_changes,
                    },
                })
                bindings.append({
                    "script_character_id": character.id,
                    "outline_character_id": outline.id,
                    "outfit_variant_id": selected_outfit.id if selected_outfit else None,
                    "outfit_status": selected_outfit.status.value if selected_outfit else None,
                    "outfit_version": selected_outfit.version if selected_outfit else None,
                })
            selected_scene = page.script_scene.selected_visual_version
            page_scene = deepcopy(scenes[page.script_scene.scene_key])
            if page.scene_conditions_json is not None and page.script_scene.task.scene_definition_version < SCENE_DEFINITION_VERSION:
                # 历史页显式保存条件后也不能同时输出旧场景的日夜/灯光默认值。
                conditions = page_scene_conditions(page)
                page_scene.update(time=conditions["time_of_day"], weather=conditions["weather"],
                                  lighting=conditions["lighting"], light_states={})
            page_contexts.append({
                "schema_version": 2,
                "context_builder_version": self.PAGE_CONTEXT_VERSION,
                "page_id": page.id, "page_no": page.page_no,
                "page_script": self._page_payload(page),
                "characters": characters,
                "scene": page_scene,
                "scene_conditions": page_scene_conditions(page),
                "prop_catalog": deepcopy(context["prop_catalog"]),
                "source_bindings": {
                    "section_id": page.section_id, "scene_id": page.scene_id,
                    "scene_visual_version_id": selected_scene.id if selected_scene else None,
                    "scene_visual_status": selected_scene.status.value if selected_scene else None,
                    "scene_visual_version": selected_scene.version if selected_scene else None,
                    "characters": bindings,
                },
            })
        return page_contexts

    def _scene_baselines(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        assets_by_owner = context["assets_by_owner"]
        result: dict[str, dict[str, Any]] = {}
        for scene in context["scenes"]:
            reference_subject = context["reference_subjects"].get(scene.reference_subject_id) or {}
            version = scene.selected_visual_version
            approved_version = (
                version if version is not None and version.status == ApprovalStatus.APPROVED else None
            )
            result[scene.scene_key] = {
                "scene_key": scene.scene_key,
                "script_scene_id": scene.id,
                "scene_definition_version": scene.task.scene_definition_version,
                "name": scene.name,
                "location_type": scene.location_type,
                "time": scene.time_of_day if scene.task.scene_definition_version < SCENE_DEFINITION_VERSION else "",
                "lighting": scene.lighting if scene.task.scene_definition_version < SCENE_DEFINITION_VERSION else "",
                "weather": scene.weather if scene.task.scene_definition_version < SCENE_DEFINITION_VERSION else "",
                "environment_details": scene.environment_details,
                "color_palette": self._loads_list(approved_version.color_palette_json)
                if approved_version
                else scene.color_palette,
                "negative_constraints": scene.negative_constraints,
                "visual_version_id": approved_version.id if approved_version else None,
                "visual_version": approved_version.version if approved_version else None,
                "reference_subject_id": scene.reference_subject_id,
                "reference_subject_key": reference_subject.get("key", ""),
                "reference_subject_name": reference_subject.get("name", ""),
                "reference_description": reference_subject.get("description", ""),
                "reference_negative_constraints": reference_subject.get("negative_constraints", ""),
                # 条目通用图与版本专用图分开，重新绑定条目后不能继续取旧条目的专用素材。
                "catalog_assets": [asset for asset in context["assets_by_reference_subject"].get(scene.reference_subject_id, []) if asset.get("entity_id") is None],
                "landmarks": self._loads_list(approved_version.landmarks_json)
                if approved_version
                else [],
                "spatial_relations": self._loads_object(approved_version.spatial_relations_json)
                if approved_version
                else {},
                "object_states": self._loads_object(approved_version.object_states_json)
                if approved_version and scene.task.scene_definition_version < SCENE_DEFINITION_VERSION
                else {},
                "light_states": self._loads_object(approved_version.lighting_state_json)
                if approved_version and scene.task.scene_definition_version < SCENE_DEFINITION_VERSION
                else {},
                "camera_presets": self._loads_list(approved_version.camera_presets_json)
                if approved_version
                else [],
                "assets": [asset for asset in assets_by_owner.get(
                    (VisualEntityType.SCENE.value, approved_version.id), []
                ) if asset.get("reference_subject_id") in (None, scene.reference_subject_id)]
                if approved_version and scene.task.scene_definition_version < SCENE_DEFINITION_VERSION
                else [],
            }
        return result

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
        reference_plan: dict[str, Any] | None = None,
        prompt_language: PromptLanguage = PromptLanguage.ORIGINAL,
        prompt_components: dict[str, str] | None = None,
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
            prompt_language=prompt_language,
        )
        compiler = compiler_for_prompt_type(prompt_type)
        compiled = compiler.compile(
            snapshot=snapshot_data,
            shot_plan=plan_data,
            style_profile=style_data,
            negative_prompts=self._negative_prompt_payload(negative_preset),
            generation_mode=generation_mode,
            source_hash=combined_source_hash,
            reference_plan=reference_plan,
            prompt_language=prompt_language,
            prompt_components=prompt_components,
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
        prompt_language: PromptLanguage = PromptLanguage.ORIGINAL,
    ) -> str:
        """来源锁定快照、镜头、选图规则和负向 Prompt；历史风格不再影响新规格。"""

        compiler = compiler_for_prompt_type(prompt_type)
        return canonical_hash(
            {
                "snapshot_hash": snapshot_hash,
                "plan_hash": plan_hash,
                "prompt_type": prompt_type.value,
                "prompt_language": prompt_language.value,
                "language_prompt_hash": canonical_hash(self._language_system_prompt())
                if prompt_language != PromptLanguage.ORIGINAL else None,
                "reference_language_prompt_hash": canonical_hash(PromptLoader.load(
                    "qwen21_reference_prompt_zh.json" if prompt_language == PromptLanguage.CHINESE
                    else "qwen21_reference_prompt.json",
                )),
                "compiler": {
                    "key": compiler.compiler_key,
                    "version": compiler.compiler_version,
                },
                "reference_selector_version": ReferenceSelectionService.VERSION,
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

    def _planner_system_prompt(self, preset: ImagePromptPreset) -> str:
        """Shot 设置覆盖同时用于实际调用与来源 Hash，避免准备复用旧镜头计划。"""
        content = ComicRepository(self.repository.session).get_system_prompt_content(
            SystemPromptKey.SHOT_PLANNER, fallback=preset.content,
        )
        return content if content is not None else PromptLoader.load("shot_planner_prompt.md")

    def _language_system_prompt(self) -> str:
        """语言转换也消费同一设置来源，修改后旧规格可检测到规则过期。"""
        content = ComicRepository(self.repository.session).get_system_prompt_content(SystemPromptKey.SHOT_LANGUAGE)
        return content if content is not None else PromptLoader.load("image_spec_language_prompt.md")

    def _global_system_prompt_hash(self) -> str:
        """全局上下文参与生成来源；API Key 从不进入来源或快照。"""
        config = self.repository.get_active_llm_config()
        content = model_prompt_overrides(config).get(config.default_model, default_model_system_prompt(config)) if config else ""
        return canonical_hash(content.strip())

    def _shot_plan_source_hash(
        self,
        *,
        plan: dict[str, Any],
        planner_preset: ImagePromptPreset | None,
        planner_model: str | None,
        planner_system_prompt: str | None = None,
        global_system_prompt_hash: str | None = None,
    ) -> str:
        """镜头计划 Hash 同时锁定计划内容和产生它的 Agent/Prompt/模型。"""

        return canonical_hash(
            {
                "plan": plan,
                "planner_preset": (
                    {
                        "id": planner_preset.id,
                        "kind": planner_preset.kind.value,
                        "content_hash": canonical_hash(planner_system_prompt if planner_system_prompt is not None else self._planner_system_prompt(planner_preset)),
                    }
                    if planner_preset is not None
                    else None
                ),
                "agent": {
                    "key": "shot_planner_agent",
                    "version": ShotPlannerAgent.VERSION,
                    "prompt_version": self.PROMPT_VERSION,
                    "llm_model": planner_model,
                    "global_system_prompt_hash": global_system_prompt_hash if global_system_prompt_hash is not None else self._global_system_prompt_hash(),
                },
            }
        )

    def _page_context_source_payload(
        self, context: dict[str, Any], page_contexts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """来源包含真实页设定和参考资产；独立版本让旧事件规格要求重新准备。"""

        return {
            "schema_version": 2,
            "context_builder_version": self.PAGE_CONTEXT_VERSION,
            "task_id": context["task"].id,
            "pages": page_contexts if page_contexts is not None else self._build_page_contexts(context),
        }

    @staticmethod
    def _page_payload(page: ComicPage) -> dict[str, Any]:
        return {
            "scene_conditions": page_scene_conditions(page),
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
        """把获批服装版本展开为本页只读造型，不携带其它页面的临时状态。"""

        payload = self._outfit_payload(item, assets)
        return {
            "variant_id": item.id,
            "version": item.version,
            "key": item.key,
            "garment_states": {},
            "conditions": {},
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
            "reference_subject_id": asset.reference_subject_id,
            "outfit_variant_id": asset.outfit_variant_id,
            "storage_kind": asset.storage_kind.value,
            "local_path": asset.local_path,
            "renderer_locator": asset.renderer_locator,
            "sha256": asset.sha256,
            "version": asset.version,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "crop_metadata_json": asset.crop_metadata_json,
            "mask_asset_id": asset.mask_asset_id,
            "derived_from_asset_id": asset.derived_from_asset_id,
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
