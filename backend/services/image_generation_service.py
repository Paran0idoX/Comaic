import asyncio
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import random
from typing import Any, AsyncIterator
from uuid import uuid4

import requests
from PIL import Image

from backend.models.comic import ComicImage, ComicPage, GenerationTask, ImageGenerationToolPreset, ImageSpec, ModelProfile, ScriptGenerationTask
from backend.models.enums import (
    ComicPageStatus,
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationToolKind,
    SeedStrategy,
    WorkflowCapability,
)
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.generation_repository import GenerationRepository
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.services.renderer_backends import backend_for_preset
from backend.services.task_runtime import RuntimeTaskType, running_task_registry
from backend.tools.comfyui_client import ComfyUIClient
from backend.i18n.errors import app_error_from_exception
from backend.services.workflow_compiler import (
    WorkflowBindings,
    WorkflowCapabilities,
    WorkflowCompiler,
)
from backend.utils.json_utils import canonical_json


CandidateSeedPair = tuple[int, int]


class ImageGenerationService:
    """图片生成业务服务：编排 workflow 配置、ComfyUI 调用、图片落库和暂停检查。"""

    def __init__(
        self,
        repository: ComicRepository,
        *,
        comfy_client: ComfyUIClient | None = None,
        output_dir: str | Path = "outputs",
    ):
        """注入 Repository 和 ComfyUI Tool；Service 负责业务状态流转。"""

        self.repository = repository
        self.comfy_client = comfy_client or ComfyUIClient(
            os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
        )
        self.output_dir = Path(output_dir)

    def list_tool_presets(self) -> list[ImageGenerationToolPreset]:
        """读取页面维护的生图工具配置。"""

        return self.repository.list_image_generation_tool_presets()

    def list_workflow_presets(self) -> list[ImageGenerationToolPreset]:
        """旧接口别名：读取 ComfyUI 类型生图工具配置。"""

        return self.repository.list_comfy_workflow_presets()

    def create_tool_preset(
        self,
        *,
        name: str,
        kind: ImageGenerationToolKind,
        description: str | None = None,
        is_default: bool = False,
        model_profile_id: int | None = None,
        capabilities: dict[str, Any] | None = None,
        bindings: dict[str, Any] | None = None,
        runtime_manifest: dict[str, Any] | None = None,
        comfy_base_url: str | None = None,
        workflow_json: str | None = None,
        positive_node_id: str | None = None,
        positive_input_name: str | None = "text",
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
        api_base_url: str | None = None,
        endpoint_path: str | None = "/images/generations",
        api_key: str | None = None,
        model: str | None = None,
        size: str | None = "1024x1024",
        response_format: str | None = "b64_json",
        seed_field_name: str | None = None,
        negative_prompt_field_name: str | None = None,
        extra_body_json: str | None = None,
    ) -> ImageGenerationToolPreset:
        """创建生图工具配置，并按工具类型校验关键字段。"""

        payload = self._normalize_tool_payload(
            kind=kind,
            model_profile_id=model_profile_id,
            capabilities=capabilities,
            bindings=bindings,
            runtime_manifest=runtime_manifest,
            comfy_base_url=comfy_base_url,
            workflow_json=workflow_json,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=negative_node_id,
            negative_input_name=negative_input_name,
            seed_node_id=seed_node_id,
            seed_input_name=seed_input_name,
            api_base_url=api_base_url,
            endpoint_path=endpoint_path,
            api_key=api_key,
            model=model,
            size=size,
            response_format=response_format,
            seed_field_name=seed_field_name,
            negative_prompt_field_name=negative_prompt_field_name,
            extra_body_json=extra_body_json,
        )
        return self.repository.create_image_generation_tool_preset(
            name=self._required_text(name, "Workflow name"),
            description=self._optional_text(description),
            kind=kind,
            is_default=is_default,
            **payload,
        )

    def update_tool_preset(
        self,
        *,
        preset_id: int,
        name: str,
        kind: ImageGenerationToolKind,
        description: str | None = None,
        is_default: bool = False,
        model_profile_id: int | None = None,
        capabilities: dict[str, Any] | None = None,
        bindings: dict[str, Any] | None = None,
        runtime_manifest: dict[str, Any] | None = None,
        comfy_base_url: str | None = None,
        workflow_json: str | None = None,
        positive_node_id: str | None = None,
        positive_input_name: str | None = "text",
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
        api_base_url: str | None = None,
        endpoint_path: str | None = "/images/generations",
        api_key: str | None = None,
        model: str | None = None,
        size: str | None = "1024x1024",
        response_format: str | None = "b64_json",
        seed_field_name: str | None = None,
        negative_prompt_field_name: str | None = None,
        extra_body_json: str | None = None,
    ) -> ImageGenerationToolPreset:
        """更新生图工具配置；校验逻辑与创建保持一致。"""

        payload = self._normalize_tool_payload(
            kind=kind,
            model_profile_id=model_profile_id,
            capabilities=capabilities,
            bindings=bindings,
            runtime_manifest=runtime_manifest,
            comfy_base_url=comfy_base_url,
            workflow_json=workflow_json,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=negative_node_id,
            negative_input_name=negative_input_name,
            seed_node_id=seed_node_id,
            seed_input_name=seed_input_name,
            api_base_url=api_base_url,
            endpoint_path=endpoint_path,
            api_key=api_key,
            model=model,
            size=size,
            response_format=response_format,
            seed_field_name=seed_field_name,
            negative_prompt_field_name=negative_prompt_field_name,
            extra_body_json=extra_body_json,
        )
        return self.repository.update_image_generation_tool_preset(
            preset_id=preset_id,
            name=self._required_text(name, "Workflow name"),
            description=self._optional_text(description),
            kind=kind,
            is_default=is_default,
            **payload,
        )

    def delete_tool_preset(self, preset_id: int) -> None:
        """删除生图工具配置，不影响已生成图片。"""

        self.repository.delete_image_generation_tool_preset(preset_id)

    def create_workflow_preset(self, **kwargs) -> ImageGenerationToolPreset:
        """旧接口别名：创建 ComfyUI 类型工具配置。"""

        kwargs.pop("kind", None)
        return self.create_tool_preset(kind=ImageGenerationToolKind.COMFYUI, **kwargs)

    def update_workflow_preset(self, *, preset_id: int, **kwargs) -> ImageGenerationToolPreset:
        """旧接口别名：更新 ComfyUI 类型工具配置。"""

        kwargs.pop("kind", None)
        return self.update_tool_preset(preset_id=preset_id, kind=ImageGenerationToolKind.COMFYUI, **kwargs)

    def delete_workflow_preset(self, preset_id: int) -> None:
        """旧接口别名：删除 ComfyUI 类型工具配置。"""

        self.repository.delete_comfy_workflow_preset(preset_id)

    def list_script_task_pages(self, task_id: int) -> list[ComicPage]:
        """读取脚本任务下所有页面，用于图片生成页面回显图片与 Prompt。"""

        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return self.repository.list_script_task_pages(task_id)

    def suspend_generation_task(self, task_id: int) -> GenerationTask:
        """暂停图片生成任务；暂停只阻止后续页面继续提交。"""

        task = self.repository.suspend_generation_task(task_id)
        if task.status != GenerationTaskStatus.SUSPENDED:
            return task
        return task

    async def stream_generate_for_script_task(
        self,
        *,
        task_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        candidates_per_page: int = 1,
        negative_prompt: str | None = None,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """按脚本任务批量生成图片；当前实现按页顺序提交，便于稳定暂停。"""

        script_task = self.repository.get_script_task(task_id)
        if script_task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        preset = self._get_tool_preset(tool_preset_id)
        if preset.model_profile_id is not None:
            pages = self.repository.list_script_task_pages(task_id)
            async for event, payload in self._stream_generate_structured_pages(
                script_task=script_task,
                pages=pages,
                preset=preset,
                candidates_per_page=candidates_per_page,
                poll_interval_seconds=poll_interval_seconds,
                generation_mode=generation_mode,
                seed_strategy=seed_strategy,
                continue_existing=False,
            ):
                yield event, payload
            return
        self._ensure_generation_tool_ready(preset)
        pages = [
            page for page in self.repository.list_script_task_pages(task_id)
            if page.image_prompt
        ]
        if not pages:
            raise ValueError(f"Image prompts not found for script task: {task_id}")
        candidate_seed_pairs = self._candidate_seed_pairs(candidates_per_page)
        page_seed_pairs = {page.id: candidate_seed_pairs for page in pages}
        async for event, payload in self._stream_generate_pages(
            script_task=script_task,
            pages=pages,
            page_seed_pairs=page_seed_pairs,
            preset=preset,
            poll_interval_seconds=poll_interval_seconds,
            negative_prompt=negative_prompt,
        ):
            yield event, payload

    async def stream_continue_for_script_task(
        self,
        *,
        task_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        candidates_per_page: int = 1,
        negative_prompt: str | None = None,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """继续批量图片生成，只为候选图数量不足的页面追加缺失候选。"""

        script_task = self.repository.get_script_task(task_id)
        if script_task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        preset = self._get_tool_preset(tool_preset_id)
        if preset.model_profile_id is not None:
            pages = self.repository.list_script_task_pages(task_id)
            async for event, payload in self._stream_generate_structured_pages(
                script_task=script_task,
                pages=pages,
                preset=preset,
                candidates_per_page=candidates_per_page,
                poll_interval_seconds=poll_interval_seconds,
                generation_mode=generation_mode,
                seed_strategy=seed_strategy,
                continue_existing=True,
            ):
                yield event, payload
            return
        self._ensure_generation_tool_ready(preset)
        pages = [
            page for page in self.repository.list_script_task_pages(task_id)
            if page.image_prompt
        ]
        if not pages:
            raise ValueError(f"Image prompts not found for script task: {task_id}")
        page_seed_pairs = self._missing_candidate_seed_pairs_by_page(
            pages=pages,
            candidates_per_page=candidates_per_page,
        )
        pages_to_generate = [page for page in pages if page_seed_pairs.get(page.id)]
        async for event, payload in self._stream_generate_pages(
            script_task=script_task,
            pages=pages_to_generate,
            page_seed_pairs=page_seed_pairs,
            preset=preset,
            poll_interval_seconds=poll_interval_seconds,
            negative_prompt=negative_prompt,
        ):
            yield event, payload

    async def stream_generate_for_page(
        self,
        *,
        page_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        candidates_per_page: int = 1,
        negative_prompt: str | None = None,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """单页生成图片，供失败页面补跑或追加候选图。"""

        page = self._get_page(page_id)
        preset = self._get_tool_preset(tool_preset_id)
        if preset.model_profile_id is not None:
            if page.section is None:
                raise ValueError(f"ComicPage has no script task: {page_id}")
            script_task = self.repository.get_script_task(page.section.task_id)
            if script_task is None:
                raise ValueError(f"ScriptGenerationTask not found: {page.section.task_id}")
            async for event, payload in self._stream_generate_structured_pages(
                script_task=script_task,
                pages=[page],
                preset=preset,
                candidates_per_page=candidates_per_page,
                poll_interval_seconds=poll_interval_seconds,
                generation_mode=generation_mode,
                seed_strategy=seed_strategy,
                continue_existing=False,
            ):
                yield event, payload
            return
        if not page.image_prompt:
            raise ValueError(f"Image prompt not found for page: {page_id}")
        self._ensure_generation_tool_ready(preset)
        candidate_seed_pairs = self._candidate_seed_pairs(candidates_per_page)
        task = self.repository.create_generation_task(
            project_id=page.project_id,
            page_id=page.id,
            batch_size=candidates_per_page,
        )
        task = self.repository.update_generation_task(
            task_id=task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        running_task_registry.register(RuntimeTaskType.GENERATION_TASK, task.id)
        try:
            yield "start", {"task_id": task.id, "total": 1, "status": task.status.value}
            image_count = 0
            async for event, payload in self._stream_page_images(
                page=page,
                page_task_id=task.id,
                preset=preset,
                candidate_seed_pairs=candidate_seed_pairs,
                poll_interval_seconds=poll_interval_seconds,
                negative_prompt=negative_prompt,
                batch_task_id=task.id,
            ):
                if event == "image":
                    image_count += 1
                yield event, payload
            if image_count == 0:
                raise ValueError(f"ComfyUI generated no images for page: {page.page_no}")
            task = self.repository.update_generation_task(
                task_id=task.id,
                status=GenerationTaskStatus.SUCCEEDED,
            )
            self.repository.mark_page_image_ready(page.id)
            yield "done", {"task_id": task.id, "status": task.status.value, "total": 1, "succeeded": 1, "failed": 0}
        except Exception as exc:
            self.repository.update_generation_task(
                task_id=task.id,
                status=GenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            raise
        finally:
            running_task_registry.unregister(RuntimeTaskType.GENERATION_TASK, task.id)

    def select_image(self, *, page_id: int, image_id: int) -> ComicPage:
        """人工选择某页最终图片。"""

        return self.repository.select_image(page_id=page_id, image_id=image_id)

    def _get_tool_preset(self, preset_id: int) -> ImageGenerationToolPreset:
        """读取生图工具 preset，不存在时给出明确错误。"""

        preset = self.repository.get_image_generation_tool_preset(preset_id)
        if preset is None:
            raise ValueError(f"ImageGenerationToolPreset not found: {preset_id}")
        return preset

    def _get_page(self, page_id: int) -> ComicPage:
        """按 id 读取页面。"""

        page = self.repository.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        return page

    async def _stream_generate_structured_pages(
        self,
        *,
        script_task: ScriptGenerationTask,
        pages: list[ComicPage],
        preset: ImageGenerationToolPreset,
        candidates_per_page: int,
        poll_interval_seconds: float,
        generation_mode: GenerationMode,
        seed_strategy: SeedStrategy,
        continue_existing: bool,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """新 P0 出图主链路：只读取匹配的 ImageSpec，并为每个候选保存 GenerationRun。"""

        if preset.model_profile_id is None or preset.model_profile is None:
            raise ValueError("Structured generation tool requires model_profile_id.")
        if not preset.model_profile.is_enabled:
            raise ValueError(f"ModelProfile must be enabled: {preset.model_profile_id}")
        declared_family = json.loads(preset.runtime_manifest_json).get("model_family")
        if declared_family not in {None, "", preset.model_profile.family.value}:
            raise ValueError(
                f"Workflow model family {declared_family} does not match "
                f"ModelProfile family {preset.model_profile.family.value}."
            )
        generation_repository = GenerationRepository(self.repository.session)
        spec_repository = ImageSpecRepository(self.repository.session)
        spec_service = ImageSpecService(spec_repository)
        current_source_hash = spec_service.current_continuity_source_hash(script_task.id)
        page_specs: dict[int, ImageSpec] = {}
        for page in pages:
            spec = generation_repository.latest_spec_for_page(
                page_id=page.id,
                model_profile_id=preset.model_profile_id,
                generation_mode=generation_mode,
            )
            if spec is None:
                raise ValueError(
                    f"ImageSpec not found for page {page.page_no}, model {preset.model_profile_id}, "
                    f"mode {generation_mode.value}."
                )
            if spec.snapshot.compilation.source_hash != current_source_hash:
                raise ValueError(f"ImageSpec is stale for page: {page.page_no}")
            if spec.source_hash != spec_service.current_image_spec_source_hash(spec):
                raise ValueError(f"ImageSpec is stale for page: {page.page_no}")
            page_specs[page.id] = spec

        page_seed_pairs = self._structured_seed_pairs(
            pages=pages,
            generation_repository=generation_repository,
            model_profile_id=preset.model_profile_id,
            generation_mode=generation_mode,
            image_spec_ids_by_page={
                page_id: spec.id for page_id, spec in page_specs.items()
            },
            candidates_per_page=candidates_per_page,
            seed_strategy=seed_strategy,
            continue_existing=continue_existing,
        )
        pages_to_generate = [page for page in pages if page_seed_pairs.get(page.id)]
        batch_size = sum(len(page_seed_pairs.get(page.id, [])) for page in pages_to_generate)
        batch_task = self.repository.create_generation_task(
            project_id=script_task.project_id,
            page_id=None if len(pages_to_generate) != 1 else pages_to_generate[0].id,
            batch_size=batch_size,
        )
        batch_task = self.repository.update_generation_task(
            task_id=batch_task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        running_task_registry.register(RuntimeTaskType.GENERATION_TASK, batch_task.id)
        backend = backend_for_preset(preset, default_comfy_client=self.comfy_client)
        completed = 0
        succeeded = 0
        failed = 0
        try:
            yield "start", {
                "task_id": batch_task.id,
                "script_task_id": script_task.id,
                "total": len(pages_to_generate),
                "batch_size": batch_size,
                "generation_mode": generation_mode.value,
                "seed_strategy": seed_strategy.value,
                "model_profile_id": preset.model_profile_id,
                "status": batch_task.status.value,
            }
            if not pages_to_generate:
                batch_task = self.repository.update_generation_task(
                    task_id=batch_task.id,
                    status=GenerationTaskStatus.SUCCEEDED,
                )
                yield "done", {
                    "task_id": batch_task.id,
                    "status": batch_task.status.value,
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                }
                return

            for page in pages_to_generate:
                if self._is_suspended(batch_task.id):
                    yield "suspended", {
                        "task_id": batch_task.id,
                        "status": GenerationTaskStatus.SUSPENDED.value,
                    }
                    return
                spec = page_specs[page.id]
                page_task = self.repository.create_generation_task(
                    project_id=script_task.project_id,
                    page_id=page.id,
                    batch_size=len(page_seed_pairs[page.id]),
                )
                page_task = self.repository.update_generation_task(
                    task_id=page_task.id,
                    status=GenerationTaskStatus.RUNNING,
                )
                running_task_registry.register(RuntimeTaskType.GENERATION_TASK, page_task.id)
                page_failed = False
                try:
                    yield "page_task", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "image_spec_id": spec.id,
                        "candidate_count": len(page_seed_pairs[page.id]),
                        "status": page_task.status.value,
                    }
                    for candidate_index, seed in page_seed_pairs[page.id]:
                        spec_payload = json.loads(spec.spec_json)
                        spec_degradations = list(spec_payload.get("warnings") or [])
                        resolved_assets = self._resolved_assets(spec_payload)
                        run = generation_repository.create_run(
                            generation_task_id=page_task.id,
                            page_id=page.id,
                            image_spec_id=spec.id,
                            tool_preset_id=preset.id,
                            model_profile_id=preset.model_profile_id,
                            candidate_index=candidate_index,
                            seed=seed,
                            seed_strategy=seed_strategy,
                            generation_mode=generation_mode,
                            bindings_json=preset.bindings_json,
                            model_manifest_json=canonical_json(
                                self._model_manifest(preset)
                            ),
                            resolved_assets_json=canonical_json(resolved_assets),
                            render_params_json=canonical_json(
                                spec_payload.get("render", {})
                            ),
                            degradation_json=canonical_json(spec_degradations),
                            applied_spec_json=canonical_json(spec_payload),
                        )
                        try:
                            submission = await backend.submit(
                                spec=spec_payload,
                                seed=seed,
                                mode=generation_mode,
                            )
                            all_degradations = spec_degradations + submission.degradations
                            generation_repository.update_run(
                                run_id=run.id,
                                status=GenerationRunStatus.QUEUED,
                                external_request_id=submission.external_id,
                                seed_applied=submission.seed_applied,
                                workflow_json=(
                                    canonical_json(submission.workflow)
                                    if submission.workflow is not None
                                    else None
                                ),
                                workflow_hash=submission.workflow_hash,
                                degradation_json=canonical_json(
                                    all_degradations
                                ),
                                applied_spec_json=canonical_json(
                                    submission.applied_spec
                                ),
                            )
                            self.repository.update_generation_task(
                                task_id=page_task.id,
                                comfy_prompt_id=submission.external_id,
                            )
                            yield "queued", {
                                "task_id": batch_task.id,
                                "page_task_id": page_task.id,
                                "generation_run_id": run.id,
                                "page_id": page.id,
                                "page_no": page.page_no,
                                "external_request_id": submission.external_id,
                                "candidate_index": candidate_index,
                                "seed": seed,
                                "seed_applied": submission.seed_applied,
                                "degradations": all_degradations,
                            }
                            generation_repository.update_run(
                                run_id=run.id,
                                status=GenerationRunStatus.RUNNING,
                            )
                            artifacts = await backend.wait(
                                submission,
                                poll_interval_seconds=poll_interval_seconds,
                            )
                            if not artifacts:
                                raise ValueError(
                                    f"Renderer generated no images for page: {page.page_no}"
                                )
                            for index, artifact in enumerate(artifacts, start=1):
                                local_path = self._save_image_file(
                                    project_id=page.project_id,
                                    page_no=page.page_no,
                                    prompt_id=submission.external_id,
                                    index=index,
                                    filename=artifact.filename,
                                    content=artifact.content,
                                )
                                sha256, width, height = self._image_metadata(
                                    artifact.content
                                )
                                image = generation_repository.add_image(
                                    run_id=run.id,
                                    page_id=page.id,
                                    local_path=str(local_path),
                                    seed=seed,
                                    workflow_name=preset.name,
                                    prompt=spec.positive_prompt,
                                    negative_prompt=spec.negative_prompt,
                                    sha256=sha256,
                                    width=width,
                                    height=height,
                                )
                                yield "image", self._image_payload(image, page)
                            generation_repository.update_run(
                                run_id=run.id,
                                status=GenerationRunStatus.SUCCEEDED,
                            )
                        except Exception as exc:
                            generation_repository.update_run(
                                run_id=run.id,
                                status=GenerationRunStatus.FAILED,
                                error_code=app_error_from_exception(exc).code,
                                error_message=str(exc),
                            )
                            raise
                    self.repository.update_generation_task(
                        task_id=page_task.id,
                        status=GenerationTaskStatus.SUCCEEDED,
                    )
                    self.repository.mark_page_image_ready(page.id)
                    succeeded += 1
                    yield "page_done", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "status": GenerationTaskStatus.SUCCEEDED.value,
                    }
                except Exception as exc:  # noqa: BLE001 - 单页失败后继续下一页
                    page_failed = True
                    error = app_error_from_exception(exc)
                    self.repository.update_generation_task(
                        task_id=page_task.id,
                        status=GenerationTaskStatus.FAILED,
                        error_message=str(exc),
                    )
                    failed += 1
                    yield "error", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "code": error.code,
                    }
                finally:
                    running_task_registry.unregister(
                        RuntimeTaskType.GENERATION_TASK,
                        page_task.id,
                    )
                completed += 1
                yield "progress", {
                    "task_id": batch_task.id,
                    "completed": completed,
                    "succeeded": succeeded,
                    "failed": failed,
                    "total": len(pages_to_generate),
                }
                if page_failed and len(pages_to_generate) == 1:
                    # 单页请求仍通过 SSE error 表达，不把批任务误标成功。
                    self.repository.update_generation_task(
                        task_id=batch_task.id,
                        status=GenerationTaskStatus.FAILED,
                    )

            final_status = (
                GenerationTaskStatus.FAILED
                if succeeded == 0 and failed > 0
                else GenerationTaskStatus.SUCCEEDED
            )
            batch_task = self.repository.update_generation_task(
                task_id=batch_task.id,
                status=final_status,
            )
            yield "done", {
                "task_id": batch_task.id,
                "status": batch_task.status.value,
                "total": len(pages_to_generate),
                "succeeded": succeeded,
                "failed": failed,
            }
        except Exception as exc:
            self.repository.update_generation_task(
                task_id=batch_task.id,
                status=GenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            raise
        finally:
            running_task_registry.unregister(
                RuntimeTaskType.GENERATION_TASK,
                batch_task.id,
            )

    def _structured_seed_pairs(
        self,
        *,
        pages: list[ComicPage],
        generation_repository: GenerationRepository,
        model_profile_id: int,
        generation_mode: GenerationMode,
        image_spec_ids_by_page: dict[int, int],
        candidates_per_page: int,
        seed_strategy: SeedStrategy,
        continue_existing: bool,
    ) -> dict[int, list[CandidateSeedPair]]:
        """按 GenerationRun 而非图片顺序计算待生成候选及 seed。"""

        existing_by_page: dict[int, dict[int, int]] = {}
        used_seeds: set[int] = set()
        shared_seeds: dict[int, int] = {}
        for page in pages:
            runs = generation_repository.list_successful_runs(
                page_id=page.id,
                model_profile_id=model_profile_id,
                generation_mode=generation_mode,
                image_spec_id=image_spec_ids_by_page[page.id],
            )
            existing_by_page[page.id] = (
                {
                    run.candidate_index: int(run.seed)
                    for run in runs
                    if run.seed is not None
                }
                if continue_existing
                else {}
            )
            for run in runs:
                if run.seed is not None:
                    used_seeds.add(int(run.seed))
                    if continue_existing:
                        shared_seeds.setdefault(run.candidate_index, int(run.seed))
        if seed_strategy == SeedStrategy.SHARED_CANDIDATE:
            for index in range(1, candidates_per_page + 1):
                if index not in shared_seeds:
                    shared_seeds[index] = self._unique_random_seed(used_seeds)
                    used_seeds.add(shared_seeds[index])

        result: dict[int, list[CandidateSeedPair]] = {}
        for page in pages:
            pairs: list[CandidateSeedPair] = []
            existing = existing_by_page[page.id]
            for index in range(1, candidates_per_page + 1):
                if continue_existing and index in existing:
                    continue
                seed = (
                    shared_seeds[index]
                    if seed_strategy == SeedStrategy.SHARED_CANDIDATE
                    else self._unique_random_seed(used_seeds)
                )
                used_seeds.add(seed)
                pairs.append((index, seed))
            result[page.id] = pairs
        return result

    @staticmethod
    def _resolved_assets(value: Any) -> list[dict[str, Any]]:
        assets: dict[int, dict[str, Any]] = {}

        def visit(item: Any) -> None:
            if isinstance(item, list):
                for child in item:
                    visit(child)
                return
            if not isinstance(item, dict):
                return
            if isinstance(item.get("id"), int) and item.get("role") and item.get(
                "storage_kind"
            ):
                assets[item["id"]] = {
                    key: item.get(key)
                    for key in (
                        "id",
                        "role",
                        "model_family",
                        "storage_kind",
                        "sha256",
                        "version",
                        "renderer_locator",
                    )
                }
            for child in item.values():
                visit(child)

        visit(value)
        return [assets[key] for key in sorted(assets)]

    @staticmethod
    def _model_manifest(preset: ImageGenerationToolPreset) -> dict[str, Any]:
        profile = preset.model_profile
        return {
            "profile_id": profile.id if profile else None,
            "family": profile.family.value if profile else None,
            "variant": profile.variant if profile else None,
            "checkpoint_name": profile.checkpoint_name if profile else None,
            "checkpoint_hash": profile.checkpoint_hash if profile else None,
            "components": json.loads(profile.component_manifest_json)
            if profile
            else {},
            "runtime": json.loads(preset.runtime_manifest_json),
        }

    @staticmethod
    def _image_metadata(content: bytes) -> tuple[str, int | None, int | None]:
        digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
        except Exception:  # noqa: BLE001 - 结果仍可保存，尺寸作为可选溯源
            return digest, None, None
        return digest, width, height

    async def _generate_page_images(
        self,
        *,
        page: ComicPage,
        page_task_id: int,
        preset: ImageGenerationToolPreset,
        candidate_seed_pairs: list[CandidateSeedPair],
        poll_interval_seconds: float,
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> list[ComicImage]:
        """提交单页 workflow，等待 ComfyUI 完成后下载并落库图片。"""

        saved_images: list[ComicImage] = []
        for _candidate_index, seed in candidate_seed_pairs:
            workflow, seed = self._build_workflow(
                preset=preset,
                positive_prompt=page.image_prompt or "",
                negative_prompt=negative_prompt,
                seed=seed,
            )
            prompt_id = await asyncio.to_thread(self.comfy_client.queue_prompt, workflow)
            self.repository.update_generation_task(
                task_id=page_task_id,
                comfy_prompt_id=prompt_id,
            )
            history = await self._wait_for_history(
                prompt_id=prompt_id,
                poll_interval_seconds=poll_interval_seconds,
                batch_task_id=batch_task_id,
            )
            output_images = self.comfy_client.extract_output_images(history, prompt_id)
            if not output_images:
                raise ValueError(f"ComfyUI history contains no images for prompt_id: {prompt_id}")
            for index, image_info in enumerate(output_images, start=1):
                content = await asyncio.to_thread(
                    self.comfy_client.download_view_image,
                    filename=image_info["filename"],
                    subfolder=image_info["subfolder"],
                    image_type=image_info["type"],
                )
                local_path = self._save_image_file(
                    project_id=page.project_id,
                    page_no=page.page_no,
                    prompt_id=prompt_id,
                    index=index,
                    filename=image_info["filename"],
                    content=content,
                )
                saved_images.append(
                    self.repository.add_image(
                        page_id=page.id,
                        prompt=page.image_prompt or "",
                        negative_prompt=negative_prompt,
                        local_path=str(local_path),
                        seed=seed,
                        workflow_name=preset.name,
                    )
                )
        return saved_images

    async def _stream_page_images(
        self,
        *,
        page: ComicPage,
        page_task_id: int,
        preset: ImageGenerationToolPreset,
        candidate_seed_pairs: list[CandidateSeedPair],
        poll_interval_seconds: float,
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """提交并保存单页图片，同时实时产出 queued/polling/image 事件。"""

        if preset.kind == ImageGenerationToolKind.OPENAI_IMAGES_COMPATIBLE:
            async for event, payload in self._stream_openai_images_compatible_page_images(
                page=page,
                page_task_id=page_task_id,
                preset=preset,
                candidate_seed_pairs=candidate_seed_pairs,
                negative_prompt=negative_prompt,
                batch_task_id=batch_task_id,
            ):
                yield event, payload
            return

        async for event, payload in self._stream_comfy_page_images(
            page=page,
            page_task_id=page_task_id,
            preset=preset,
            candidate_seed_pairs=candidate_seed_pairs,
            poll_interval_seconds=poll_interval_seconds,
            negative_prompt=negative_prompt,
            batch_task_id=batch_task_id,
        ):
            yield event, payload

    async def _stream_comfy_page_images(
        self,
        *,
        page: ComicPage,
        page_task_id: int,
        preset: ImageGenerationToolPreset,
        candidate_seed_pairs: list[CandidateSeedPair],
        poll_interval_seconds: float,
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """使用 ComfyUI workflow 生成并保存单页图片。"""

        for candidate_index, seed in candidate_seed_pairs:
            workflow, seed = self._build_workflow(
                preset=preset,
                positive_prompt=page.image_prompt or "",
                negative_prompt=negative_prompt,
                seed=seed,
            )
            comfy_client = self._comfy_client_for_preset(preset)
            prompt_id = await asyncio.to_thread(comfy_client.queue_prompt, workflow)
            self.repository.update_generation_task(
                task_id=page_task_id,
                comfy_prompt_id=prompt_id,
            )
            yield "queued", {
                "task_id": batch_task_id,
                "page_task_id": page_task_id,
                "page_id": page.id,
                "page_no": page.page_no,
                "comfy_prompt_id": prompt_id,
                "candidate_index": candidate_index,
                "seed": seed,
            }

            poll_count = 0
            while True:
                poll_count += 1
                history = await asyncio.to_thread(comfy_client.get_history, prompt_id)
                output_images = comfy_client.extract_output_images(history, prompt_id)
                if output_images:
                    break
                yield "polling", {
                    "task_id": batch_task_id,
                    "page_task_id": page_task_id,
                    "page_id": page.id,
                    "page_no": page.page_no,
                    "comfy_prompt_id": prompt_id,
                    "poll_count": poll_count,
                    "candidate_index": candidate_index,
                    "seed": seed,
                }
                await asyncio.sleep(poll_interval_seconds)

            for index, image_info in enumerate(output_images, start=1):
                content = await asyncio.to_thread(
                    comfy_client.download_view_image,
                    filename=image_info["filename"],
                    subfolder=image_info["subfolder"],
                    image_type=image_info["type"],
                )
                local_path = self._save_image_file(
                    project_id=page.project_id,
                    page_no=page.page_no,
                    prompt_id=prompt_id,
                    index=index,
                    filename=image_info["filename"],
                    content=content,
                )
                image = self.repository.add_image(
                    page_id=page.id,
                    prompt=page.image_prompt or "",
                    negative_prompt=negative_prompt,
                    local_path=str(local_path),
                    seed=seed,
                    workflow_name=preset.name,
                )
                yield "image", self._image_payload(image, page)

    async def _stream_openai_images_compatible_page_images(
        self,
        *,
        page: ComicPage,
        page_task_id: int,
        preset: ImageGenerationToolPreset,
        candidate_seed_pairs: list[CandidateSeedPair],
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """使用 OpenAI Images 兼容 API 生成并保存单页图片。"""

        for candidate_index, seed in candidate_seed_pairs:
            request_id = f"image-api-{uuid4().hex}"
            yield "queued", {
                "task_id": batch_task_id,
                "page_task_id": page_task_id,
                "page_id": page.id,
                "page_no": page.page_no,
                "comfy_prompt_id": request_id,
                "candidate_index": candidate_index,
                "seed": seed,
            }
            response_payload = await asyncio.to_thread(
                self._request_openai_images_compatible,
                preset=preset,
                prompt=page.image_prompt or "",
                negative_prompt=negative_prompt,
                seed=seed,
            )
            external_id = str(response_payload.get("id") or request_id)
            self.repository.update_generation_task(
                task_id=page_task_id,
                comfy_prompt_id=external_id,
            )
            image_items = response_payload.get("data")
            if not isinstance(image_items, list) or not image_items:
                raise ValueError("Image generation API returned no images.")
            for index, item in enumerate(image_items, start=1):
                content = await asyncio.to_thread(self._image_content_from_api_item, item)
                local_path = self._save_image_file(
                    project_id=page.project_id,
                    page_no=page.page_no,
                    prompt_id=external_id,
                    index=index,
                    filename=f"{external_id}_{index}.png",
                    content=content,
                )
                image = self.repository.add_image(
                    page_id=page.id,
                    prompt=page.image_prompt or "",
                    negative_prompt=negative_prompt,
                    local_path=str(local_path),
                    seed=seed,
                    workflow_name=preset.name,
                )
                yield "image", self._image_payload(image, page)

    async def _stream_generate_pages(
        self,
        *,
        script_task: ScriptGenerationTask,
        pages: list[ComicPage],
        page_seed_pairs: dict[int, list[CandidateSeedPair]],
        preset: ImageGenerationToolPreset,
        poll_interval_seconds: float,
        negative_prompt: str | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """批量图片生成公共执行器；主流程统一落库任务状态并产出 SSE。"""

        batch_size = sum(len(page_seed_pairs.get(page.id, [])) for page in pages)
        batch_task = self.repository.create_generation_task(
            project_id=script_task.project_id,
            page_id=None,
            batch_size=batch_size,
        )
        batch_task = self.repository.update_generation_task(
            task_id=batch_task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        running_task_registry.register(RuntimeTaskType.GENERATION_TASK, batch_task.id)
        try:
            yield "start", {
                "task_id": batch_task.id,
                "script_task_id": script_task.id,
                "total": len(pages),
                "batch_size": batch_size,
                "status": batch_task.status.value,
            }

            if not pages:
                batch_task = self.repository.update_generation_task(
                    task_id=batch_task.id,
                    status=GenerationTaskStatus.SUCCEEDED,
                )
                yield "done", {
                    "task_id": batch_task.id,
                    "status": batch_task.status.value,
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                }
                return

            completed = 0
            succeeded = 0
            failed = 0
            for page in pages:
                if self._is_suspended(batch_task.id):
                    yield "suspended", {"task_id": batch_task.id, "status": GenerationTaskStatus.SUSPENDED.value}
                    return

                candidate_seed_pairs = page_seed_pairs.get(page.id, [])
                if not candidate_seed_pairs:
                    continue
                page_task = self.repository.create_generation_task(
                    project_id=script_task.project_id,
                    page_id=page.id,
                    batch_size=len(candidate_seed_pairs),
                )
                page_task = self.repository.update_generation_task(
                    task_id=page_task.id,
                    status=GenerationTaskStatus.RUNNING,
                )
                running_task_registry.register(RuntimeTaskType.GENERATION_TASK, page_task.id)
                try:
                    yield "page_task", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "candidate_count": len(candidate_seed_pairs),
                        "status": page_task.status.value,
                    }
                    image_count = 0
                    async for event, payload in self._stream_page_images(
                        page=page,
                        page_task_id=page_task.id,
                        preset=preset,
                        candidate_seed_pairs=candidate_seed_pairs,
                        poll_interval_seconds=poll_interval_seconds,
                        negative_prompt=negative_prompt,
                        batch_task_id=batch_task.id,
                    ):
                        if event == "image":
                            image_count += 1
                        yield event, payload
                    if image_count == 0:
                        raise ValueError(f"ComfyUI generated no images for page: {page.page_no}")
                    self.repository.update_generation_task(
                        task_id=page_task.id,
                        status=GenerationTaskStatus.SUCCEEDED,
                    )
                    self.repository.mark_page_image_ready(page.id)
                    completed += 1
                    succeeded += 1
                    yield "page_done", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "status": GenerationTaskStatus.SUCCEEDED.value,
                    }
                except Exception as exc:  # noqa: BLE001 - 单页失败不阻断后续页面
                    error = app_error_from_exception(exc)
                    self.repository.update_generation_task(
                        task_id=page_task.id,
                        status=GenerationTaskStatus.FAILED,
                        error_message=str(exc),
                    )
                    completed += 1
                    failed += 1
                    yield "error", {
                        "task_id": batch_task.id,
                        "page_task_id": page_task.id,
                        "page_id": page.id,
                        "page_no": page.page_no,
                        "code": error.code,
                    }
                finally:
                    running_task_registry.unregister(RuntimeTaskType.GENERATION_TASK, page_task.id)

                yield "progress", {
                    "task_id": batch_task.id,
                    "completed": completed,
                    "succeeded": succeeded,
                    "failed": failed,
                    "total": len(pages),
                }

                if self._is_suspended(batch_task.id):
                    yield "suspended", {"task_id": batch_task.id, "status": GenerationTaskStatus.SUSPENDED.value}
                    return

            batch_task = self.repository.update_generation_task(
                task_id=batch_task.id,
                status=GenerationTaskStatus.SUCCEEDED,
            )
            yield "done", {
                "task_id": batch_task.id,
                "status": batch_task.status.value,
                "total": len(pages),
                "succeeded": succeeded,
                "failed": failed,
            }
        except Exception as exc:
            self.repository.update_generation_task(
                task_id=batch_task.id,
                status=GenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            raise
        finally:
            running_task_registry.unregister(RuntimeTaskType.GENERATION_TASK, batch_task.id)

    async def _wait_for_history(
        self,
        *,
        prompt_id: str,
        poll_interval_seconds: float,
        batch_task_id: int,
    ) -> dict[str, Any]:
        """轮询 ComfyUI history；暂停不会中断当前 prompt，只在当前页完成后生效。"""

        while True:
            history = await asyncio.to_thread(self.comfy_client.get_history, prompt_id)
            if self.comfy_client.extract_output_images(history, prompt_id):
                return history
            await asyncio.sleep(poll_interval_seconds)
            if self._is_suspended(batch_task_id):
                # 不 interrupt ComfyUI；这里继续等待当前页完成，让已提交任务能正常保存结果。
                continue

    def _build_workflow(
        self,
        *,
        preset: ImageGenerationToolPreset,
        positive_prompt: str,
        negative_prompt: str | None,
        seed: int,
    ) -> tuple[dict[str, Any], int]:
        """复制 workflow preset，并注入正向 Prompt、可选负向 Prompt 和后端指定 seed。"""

        workflow = json.loads(preset.workflow_json)
        workflow = deepcopy(workflow)
        self._set_workflow_input(
            workflow,
            node_id=preset.positive_node_id,
            input_name=preset.positive_input_name,
            value=positive_prompt,
        )
        if negative_prompt and preset.negative_node_id and preset.negative_input_name:
            self._set_workflow_input(
                workflow,
                node_id=preset.negative_node_id,
                input_name=preset.negative_input_name,
                value=negative_prompt,
            )
        self._ensure_seed_configured(preset)
        self._set_workflow_input(
            workflow,
            node_id=preset.seed_node_id or "",
            input_name=preset.seed_input_name or "",
            value=seed,
        )
        return workflow, seed

    def _request_openai_images_compatible(
        self,
        *,
        preset: ImageGenerationToolPreset,
        prompt: str,
        negative_prompt: str | None,
        seed: int,
    ) -> dict[str, Any]:
        """调用 OpenAI Images 兼容 API，并返回 JSON 响应。"""

        api_base_url = self._required_text(preset.api_base_url, "Image API base URL").rstrip("/")
        endpoint_path = (preset.endpoint_path or "/images/generations").strip() or "/images/generations"
        body: dict[str, Any] = {
            "model": self._required_text(preset.model, "Image API model"),
            "prompt": prompt,
            "n": 1,
        }
        if preset.size:
            body["size"] = preset.size
        if preset.response_format:
            body["response_format"] = preset.response_format
        if preset.extra_body_json:
            body.update(self._normalize_extra_body_json(preset.extra_body_json))
        if preset.seed_field_name:
            body[preset.seed_field_name] = seed
        if negative_prompt and preset.negative_prompt_field_name:
            body[preset.negative_prompt_field_name] = negative_prompt

        headers = {"Content-Type": "application/json"}
        if preset.api_key:
            headers["Authorization"] = f"Bearer {preset.api_key}"
        response = requests.post(
            f"{api_base_url}/{endpoint_path.lstrip('/')}",
            json=body,
            headers=headers,
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Image generation API response must be a JSON object.")
        return payload

    def _image_content_from_api_item(self, item: Any) -> bytes:
        """从 OpenAI Images 兼容响应项提取图片二进制，支持 b64_json 和 url。"""

        if not isinstance(item, dict):
            raise ValueError("Image generation API image item must be an object.")
        b64_json = item.get("b64_json")
        if isinstance(b64_json, str) and b64_json.strip():
            return base64.b64decode(b64_json)
        image_url = item.get("url")
        if isinstance(image_url, str) and image_url.strip():
            response = requests.get(image_url, timeout=180)
            response.raise_for_status()
            return response.content
        raise ValueError("Image generation API image item contains neither b64_json nor url.")

    def _comfy_client_for_preset(self, preset: ImageGenerationToolPreset) -> ComfyUIClient:
        """按工具配置创建 ComfyUI client；未设置 base_url 时复用默认 client。"""

        if not preset.comfy_base_url:
            return self.comfy_client
        return ComfyUIClient(preset.comfy_base_url)

    def _ensure_generation_tool_ready(self, preset: ImageGenerationToolPreset) -> None:
        """生成前校验工具配置满足运行需要。"""

        if preset.kind == ImageGenerationToolKind.COMFYUI:
            self._ensure_seed_configured(preset)
            if not preset.workflow_json:
                raise ValueError("Workflow JSON is required for ComfyUI image generation.")
            return
        if preset.kind == ImageGenerationToolKind.OPENAI_IMAGES_COMPATIBLE:
            self._required_text(preset.api_base_url, "Image API base URL")
            self._required_text(preset.model, "Image API model")
            return
        raise ValueError(f"Unsupported image generation tool kind: {preset.kind.value}")

    def _normalize_tool_payload(
        self,
        *,
        kind: ImageGenerationToolKind,
        model_profile_id: int | None,
        capabilities: dict[str, Any] | None,
        bindings: dict[str, Any] | None,
        runtime_manifest: dict[str, Any] | None,
        comfy_base_url: str | None,
        workflow_json: str | None,
        positive_node_id: str | None,
        positive_input_name: str | None,
        negative_node_id: str | None,
        negative_input_name: str | None,
        seed_node_id: str | None,
        seed_input_name: str | None,
        api_base_url: str | None,
        endpoint_path: str | None,
        api_key: str | None,
        model: str | None,
        size: str | None,
        response_format: str | None,
        seed_field_name: str | None,
        negative_prompt_field_name: str | None,
        extra_body_json: str | None,
    ) -> dict[str, Any]:
        """按工具类型规范化字段；不属于该工具的字段置空。"""

        profile = None
        if model_profile_id is not None:
            profile = self.repository.session.get(ModelProfile, model_profile_id)
            if profile is None:
                raise ValueError(f"ModelProfile not found: {model_profile_id}")
        normalized_runtime_manifest = runtime_manifest or {}
        declared_family = normalized_runtime_manifest.get("model_family")
        if profile is not None and declared_family not in {None, "", profile.family.value}:
            raise ValueError(
                f"Workflow model family {declared_family} does not match "
                f"ModelProfile family {profile.family.value}."
            )
        capability_model = WorkflowCapabilities.model_validate(
            capabilities or {"features": ["txt2img"], "limits": {}}
        )
        if WorkflowCapability.TXT2IMG not in capability_model.features:
            raise ValueError("Workflow capabilities must include txt2img.")
        binding_payload = bindings or {"schema_version": 1, "bindings": []}

        if kind == ImageGenerationToolKind.COMFYUI:
            normalized_workflow = self._normalize_workflow_json(
                self._required_text(workflow_json, "Workflow JSON")
            )
            if not binding_payload.get("bindings"):
                normalized_positive_node_id = self._required_text(
                    positive_node_id, "Positive node id"
                )
                normalized_positive_input_name = self._required_text(
                    positive_input_name,
                    "Positive input name",
                )
                legacy_bindings = [
                    {
                        "source": "prompt.positive",
                        "node_id": normalized_positive_node_id,
                        "input_name": normalized_positive_input_name,
                    }
                ]
                for source, node_id, input_name in (
                    ("prompt.negative", negative_node_id, negative_input_name),
                    ("render.seed", seed_node_id, seed_input_name),
                ):
                    if self._optional_text(node_id) and self._optional_text(input_name):
                        legacy_bindings.append(
                            {
                                "source": source,
                                "node_id": self._optional_text(node_id),
                                "input_name": self._optional_text(input_name),
                            }
                        )
                binding_payload = {"schema_version": 1, "bindings": legacy_bindings}
            binding_model = WorkflowBindings.model_validate(binding_payload)
            WorkflowCompiler().validate_configuration(
                workflow=normalized_workflow,
                capabilities=capability_model,
                bindings=binding_model,
            )
            bindings_by_source = {
                binding.source: binding for binding in binding_model.bindings
            }
            positive_binding = bindings_by_source["prompt.positive"]
            negative_binding = bindings_by_source.get("prompt.negative")
            seed_binding = bindings_by_source.get("render.seed")
            return {
                "model_profile_id": model_profile_id,
                "capabilities_json": canonical_json(capability_model.model_dump(mode="json")),
                "bindings_json": canonical_json(binding_model.model_dump(mode="json")),
                "runtime_manifest_json": canonical_json(normalized_runtime_manifest),
                "comfy_base_url": self._optional_text(comfy_base_url),
                "workflow_json": json.dumps(normalized_workflow, ensure_ascii=False),
                # 旧字段由声明式 binding 投影，避免两套配置产生漂移。
                "positive_node_id": positive_binding.node_id,
                "positive_input_name": positive_binding.input_name,
                "negative_node_id": negative_binding.node_id
                if negative_binding
                else None,
                "negative_input_name": negative_binding.input_name
                if negative_binding
                else None,
                "seed_node_id": seed_binding.node_id if seed_binding else None,
                "seed_input_name": seed_binding.input_name if seed_binding else None,
                "api_base_url": None,
                "endpoint_path": None,
                "api_key": None,
                "model": None,
                "size": None,
                "response_format": None,
                "seed_field_name": None,
                "negative_prompt_field_name": None,
                "extra_body_json": None,
            }

        if kind == ImageGenerationToolKind.OPENAI_IMAGES_COMPATIBLE:
            normalized_extra_body_json = None
            if self._optional_text(extra_body_json):
                normalized_extra_body_json = json.dumps(
                    self._normalize_extra_body_json(extra_body_json or ""),
                    ensure_ascii=False,
                )
            return {
                "model_profile_id": model_profile_id,
                "capabilities_json": canonical_json(capability_model.model_dump(mode="json")),
                "bindings_json": canonical_json(
                    WorkflowBindings.model_validate(binding_payload).model_dump(mode="json")
                ),
                "runtime_manifest_json": canonical_json(normalized_runtime_manifest),
                "comfy_base_url": None,
                "workflow_json": None,
                "positive_node_id": None,
                "positive_input_name": None,
                "negative_node_id": None,
                "negative_input_name": None,
                "seed_node_id": None,
                "seed_input_name": None,
                "api_base_url": self._required_text(api_base_url, "Image API base URL"),
                "endpoint_path": self._optional_text(endpoint_path) or "/images/generations",
                "api_key": self._optional_text(api_key),
                "model": self._required_text(model, "Image API model"),
                "size": self._optional_text(size) or "1024x1024",
                "response_format": self._optional_text(response_format) or "b64_json",
                "seed_field_name": self._optional_text(seed_field_name),
                "negative_prompt_field_name": self._optional_text(negative_prompt_field_name),
                "extra_body_json": normalized_extra_body_json,
            }

        raise ValueError(f"Unsupported image generation tool kind: {kind.value}")

    @staticmethod
    def _normalize_extra_body_json(value: str) -> dict[str, Any]:
        """校验 OpenAI Images 兼容 API 的额外请求体参数。"""

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Extra body JSON is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Extra body JSON must be an object.")
        return payload

    @staticmethod
    def _candidate_seed_pairs(candidates_per_page: int) -> list[CandidateSeedPair]:
        """生成候选序号和 seed 对；同一批次中候选序号跨页复用同一个 seed。"""

        return list(enumerate(ImageGenerationService._candidate_seeds(candidates_per_page), start=1))

    def _missing_candidate_seed_pairs_by_page(
        self,
        *,
        pages: list[ComicPage],
        candidates_per_page: int,
    ) -> dict[int, list[CandidateSeedPair]]:
        """计算继续生成需要补的候选图；候选序号按已有图片创建顺序推断。"""

        seed_by_candidate_index = self._candidate_seed_map_from_existing_images(
            pages=pages,
            candidates_per_page=candidates_per_page,
        )
        result: dict[int, list[CandidateSeedPair]] = {}
        for page in pages:
            existing_count = min(
                len(self._sorted_page_images_for_candidate_order(page)),
                candidates_per_page,
            )
            result[page.id] = [
                (candidate_index, seed_by_candidate_index[candidate_index])
                for candidate_index in range(existing_count + 1, candidates_per_page + 1)
            ]
        return result

    def _candidate_seed_map_from_existing_images(
        self,
        *,
        pages: list[ComicPage],
        candidates_per_page: int,
    ) -> dict[int, int]:
        """从历史图片推断候选序号 seed；缺失的新候选序号生成新 seed。"""

        seed_by_candidate_index: dict[int, int] = {}
        used_seeds: set[int] = set()
        for page in pages:
            for candidate_index, image in enumerate(
                self._sorted_page_images_for_candidate_order(page)[:candidates_per_page],
                start=1,
            ):
                if image.seed is None:
                    continue
                used_seeds.add(image.seed)
                seed_by_candidate_index.setdefault(candidate_index, image.seed)

        for candidate_index in range(1, candidates_per_page + 1):
            if candidate_index in seed_by_candidate_index:
                continue
            seed = self._unique_random_seed(used_seeds)
            seed_by_candidate_index[candidate_index] = seed
            used_seeds.add(seed)
        return seed_by_candidate_index

    @staticmethod
    def _sorted_page_images_for_candidate_order(page: ComicPage) -> list[ComicImage]:
        """候选序号由同页图片的创建顺序推断，旧图在前，新图在后。"""

        return sorted(
            page.images,
            key=lambda image: (
                image.created_at,
                image.id,
            ),
        )

    @staticmethod
    def _unique_random_seed(used_seeds: set[int]) -> int:
        """生成不与本批次已知 seed 冲突的随机 seed。"""

        while True:
            seed = random.randint(1, 2_147_483_647)
            if seed not in used_seeds:
                return seed

    @staticmethod
    def _candidate_seeds(candidates_per_page: int) -> list[int]:
        """为候选序号生成稳定 seed；批量生成时跨页复用同一候选序号 seed。"""

        seeds: list[int] = []
        seen: set[int] = set()
        while len(seeds) < candidates_per_page:
            seed = random.randint(1, 2_147_483_647)
            if seed in seen:
                continue
            seen.add(seed)
            seeds.append(seed)
        return seeds

    @staticmethod
    def _ensure_seed_configured(preset: ImageGenerationToolPreset) -> None:
        """图片生成必须由后端注入 seed，因此 workflow preset 需要配置 seed 输入位置。"""

        if not preset.seed_node_id or not preset.seed_input_name:
            raise ValueError("Workflow seed node id and seed input name are required for image generation.")

    def _save_image_file(
        self,
        *,
        project_id: int,
        page_no: int,
        prompt_id: str,
        index: int,
        filename: str,
        content: bytes,
    ) -> Path:
        """保存 ComfyUI 图片到 outputs，路径按项目和页码分组。"""

        suffix = Path(filename).suffix or ".png"
        directory = self.output_dir / f"project_{project_id}" / f"page_{page_no}"
        directory.mkdir(parents=True, exist_ok=True)
        safe_prompt_id = "".join(char if char.isalnum() or char in "-_." else "_" for char in prompt_id)
        local_path = directory / f"{safe_prompt_id}_{index}{suffix}"
        local_path.write_bytes(content)
        return local_path

    def _is_suspended(self, task_id: int) -> bool:
        """从数据库读取最新暂停状态，避免 SSE 长连接使用缓存状态。"""

        return self.repository.get_generation_task_status(task_id) == GenerationTaskStatus.SUSPENDED

    @staticmethod
    def _normalize_workflow_json(value: str) -> dict[str, Any]:
        """校验 workflow JSON，必须是 ComfyUI API workflow 对象。"""

        try:
            workflow = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Workflow JSON is invalid: {exc}") from exc
        if not isinstance(workflow, dict):
            raise ValueError("Workflow JSON must be an object.")
        return workflow

    @staticmethod
    def _validate_workflow_input(workflow: dict[str, Any], node_id: str, input_name: str) -> None:
        """校验节点存在且有 inputs；具体 input 允许新增，兼容部分自定义节点。"""

        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise ValueError(f"Workflow node not found: {node_id}")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(f"Workflow node has no inputs: {node_id}")
        if not input_name:
            raise ValueError("Workflow input name cannot be empty.")

    @staticmethod
    def _set_workflow_input(
        workflow: dict[str, Any],
        *,
        node_id: str,
        input_name: str,
        value: str | int,
    ) -> None:
        """向指定节点 input 写入值；节点不存在说明 preset 配置错误。"""

        node = workflow.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise ValueError(f"Workflow node input not found: {node_id}.{input_name}")
        node["inputs"][input_name] = value

    @staticmethod
    def _image_payload(image: ComicImage, page: ComicPage) -> dict[str, Any]:
        """把图片 ORM 对象转成 SSE payload。"""

        return {
            "id": image.id,
            "page_id": image.page_id,
            "generation_run_id": image.generation_run_id,
            "page_no": page.page_no,
            "image_url": f"/api/image-generation/images/{image.id}/file",
            "local_path": image.local_path,
            "seed": image.seed,
            "workflow_name": image.workflow_name,
            "prompt": image.prompt,
            "negative_prompt": image.negative_prompt,
            "score": image.score,
            "sha256": image.sha256,
            "width": image.width,
            "height": image.height,
            "is_selected": image.is_selected,
            "created_at": image.created_at.isoformat(),
        }

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        """统一校验必填文本。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty.")
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        """统一清理可选文本。"""

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
