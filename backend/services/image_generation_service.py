import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import random
from typing import Any, AsyncIterator

from PIL import Image

from backend.i18n.errors import app_error_from_exception
from backend.models.comic import (
    ComicImage,
    ComicPage,
    GenerationTask,
    ImageGenerationToolPreset,
    ImageSpec,
    ScriptGenerationTask,
)
from backend.models.enums import (
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationProvider,
    ImagePromptType,
    SeedStrategy,
    WorkflowCapability,
)
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.generation_repository import GenerationRepository
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_service import ImageSpecService
from backend.services.renderer_backends import backend_for_preset
from backend.services.task_runtime import RuntimeTaskType, running_task_registry
from backend.services.workflow_compiler import (
    WorkflowBindings,
    WorkflowCapabilities,
    WorkflowCompiler,
)
from backend.tools.comfyui_client import ComfyUIClient
from backend.utils.json_utils import canonical_json


CandidateSeedPair = tuple[int, int]


class ImageGenerationService:
    """模型无关图片生成编排：工具按 Prompt 类型消费 ImageSpec。"""

    def __init__(
        self,
        repository: ComicRepository,
        *,
        comfy_client: ComfyUIClient | None = None,
        output_dir: str | Path = "outputs",
    ):
        self.repository = repository
        self.comfy_client = comfy_client or ComfyUIClient(
            os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
        )
        self.output_dir = Path(output_dir)

    # Tool presets -----------------------------------------------------
    def list_tool_presets(self) -> list[ImageGenerationToolPreset]:
        return self.repository.list_image_generation_tool_presets()

    def list_workflow_presets(self) -> list[ImageGenerationToolPreset]:
        """兼容旧路由名称；返回 ComfyUI provider 的工具。"""

        return self.repository.list_comfy_workflow_presets()

    def create_tool_preset(
        self,
        *,
        name: str,
        provider: ImageGenerationProvider,
        prompt_type: ImagePromptType,
        description: str | None = None,
        is_default: bool = False,
        capabilities: dict[str, Any] | None = None,
        bindings: dict[str, Any] | None = None,
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
        payload = self._normalize_tool_payload(
            provider=provider,
            capabilities=capabilities,
            bindings=bindings,
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
            name=self._required_text(name, "Tool name"),
            description=self._optional_text(description),
            provider=provider,
            prompt_type=prompt_type,
            is_default=is_default,
            **payload,
        )

    def update_tool_preset(
        self,
        *,
        preset_id: int,
        name: str,
        provider: ImageGenerationProvider,
        prompt_type: ImagePromptType,
        description: str | None = None,
        is_default: bool = False,
        capabilities: dict[str, Any] | None = None,
        bindings: dict[str, Any] | None = None,
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
        payload = self._normalize_tool_payload(
            provider=provider,
            capabilities=capabilities,
            bindings=bindings,
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
            name=self._required_text(name, "Tool name"),
            description=self._optional_text(description),
            provider=provider,
            prompt_type=prompt_type,
            is_default=is_default,
            **payload,
        )

    def delete_tool_preset(self, preset_id: int) -> None:
        self.repository.delete_image_generation_tool_preset(preset_id)

    def create_workflow_preset(self, **kwargs) -> ImageGenerationToolPreset:
        kwargs.pop("provider", None)
        return self.create_tool_preset(
            provider=ImageGenerationProvider.COMFYUI,
            **kwargs,
        )

    def update_workflow_preset(
        self,
        *,
        preset_id: int,
        **kwargs,
    ) -> ImageGenerationToolPreset:
        kwargs.pop("provider", None)
        return self.update_tool_preset(
            preset_id=preset_id,
            provider=ImageGenerationProvider.COMFYUI,
            **kwargs,
        )

    def delete_workflow_preset(self, preset_id: int) -> None:
        self.repository.delete_comfy_workflow_preset(preset_id)

    # Public generation API -------------------------------------------
    def list_script_task_pages(self, task_id: int) -> list[ComicPage]:
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return self.repository.list_script_task_pages(task_id)

    def suspend_generation_task(self, task_id: int) -> GenerationTask:
        return self.repository.suspend_generation_task(task_id)

    async def stream_generate_for_script_task(
        self,
        *,
        task_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        wait_timeout_seconds: float = 600.0,
        candidates_per_page: int = 1,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        script_task = self._get_script_task(task_id)
        async for event, payload in self._stream_generate_pages(
            script_task=script_task,
            pages=self.repository.list_script_task_pages(task_id),
            preset=self._get_tool_preset(tool_preset_id),
            candidates_per_page=candidates_per_page,
            poll_interval_seconds=poll_interval_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            generation_mode=generation_mode,
            seed_strategy=seed_strategy,
            continue_existing=False,
        ):
            yield event, payload

    async def stream_continue_for_script_task(
        self,
        *,
        task_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        wait_timeout_seconds: float = 600.0,
        candidates_per_page: int = 1,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        script_task = self._get_script_task(task_id)
        async for event, payload in self._stream_generate_pages(
            script_task=script_task,
            pages=self.repository.list_script_task_pages(task_id),
            preset=self._get_tool_preset(tool_preset_id),
            candidates_per_page=candidates_per_page,
            poll_interval_seconds=poll_interval_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            generation_mode=generation_mode,
            seed_strategy=seed_strategy,
            continue_existing=True,
        ):
            yield event, payload

    async def stream_generate_for_page(
        self,
        *,
        page_id: int,
        tool_preset_id: int,
        poll_interval_seconds: float = 2.0,
        wait_timeout_seconds: float = 600.0,
        candidates_per_page: int = 1,
        generation_mode: GenerationMode = GenerationMode.PREVIEW,
        seed_strategy: SeedStrategy = SeedStrategy.PER_PAGE,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        page = self._get_page(page_id)
        if page.section is None:
            raise ValueError(f"ComicPage has no script task: {page_id}")
        script_task = self._get_script_task(page.section.task_id)
        async for event, payload in self._stream_generate_pages(
            script_task=script_task,
            pages=[page],
            preset=self._get_tool_preset(tool_preset_id),
            candidates_per_page=candidates_per_page,
            poll_interval_seconds=poll_interval_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            generation_mode=generation_mode,
            seed_strategy=seed_strategy,
            continue_existing=False,
        ):
            yield event, payload

    def select_image(self, *, page_id: int, image_id: int) -> ComicPage:
        return self.repository.select_image(page_id=page_id, image_id=image_id)

    # Structured generation ------------------------------------------
    async def _stream_generate_pages(
        self,
        *,
        script_task: ScriptGenerationTask,
        pages: list[ComicPage],
        preset: ImageGenerationToolPreset,
        candidates_per_page: int,
        poll_interval_seconds: float,
        wait_timeout_seconds: float,
        generation_mode: GenerationMode,
        seed_strategy: SeedStrategy,
        continue_existing: bool,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """按工具 Prompt 类型读取最新规格，并为每个候选保存完整运行记录。"""

        self._ensure_generation_tool_ready(preset)
        generation_repository = GenerationRepository(self.repository.session)
        spec_service = ImageSpecService(ImageSpecRepository(self.repository.session))
        current_continuity_hash = spec_service.current_continuity_source_hash(
            script_task.id
        )
        page_specs: dict[int, ImageSpec] = {}
        for page in pages:
            spec = generation_repository.latest_spec_for_page(
                page_id=page.id,
                prompt_type=preset.prompt_type,
                generation_mode=generation_mode,
            )
            if spec is None:
                raise ValueError(
                    f"ImageSpec not found for page {page.page_no}, prompt type "
                    f"{preset.prompt_type.value}, mode {generation_mode.value}."
                )
            if spec.snapshot.compilation.source_hash != current_continuity_hash:
                raise ValueError(f"ImageSpec is stale for page: {page.page_no}")
            if spec.source_hash != spec_service.current_image_spec_source_hash(spec):
                raise ValueError(f"ImageSpec is stale for page: {page.page_no}")
            page_specs[page.id] = spec

        page_seed_pairs = self._structured_seed_pairs(
            pages=pages,
            generation_repository=generation_repository,
            prompt_type=preset.prompt_type,
            generation_mode=generation_mode,
            image_spec_ids_by_page={page_id: spec.id for page_id, spec in page_specs.items()},
            candidates_per_page=candidates_per_page,
            seed_strategy=seed_strategy,
            continue_existing=continue_existing,
        )
        pages_to_generate = [page for page in pages if page_seed_pairs.get(page.id)]
        batch_size = sum(len(page_seed_pairs[page.id]) for page in pages_to_generate)
        batch_task = self.repository.create_generation_task(
            project_id=script_task.project_id,
            page_id=pages_to_generate[0].id if len(pages_to_generate) == 1 else None,
            batch_size=batch_size,
        )
        batch_task = self.repository.update_generation_task(
            task_id=batch_task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        running_task_registry.register(RuntimeTaskType.GENERATION_TASK, batch_task.id)
        renderer = backend_for_preset(
            preset,
            default_comfy_client=self.comfy_client,
        )
        succeeded = 0
        failed = 0
        completed = 0
        try:
            yield "start", {
                "task_id": batch_task.id,
                "script_task_id": script_task.id,
                "total": len(pages_to_generate),
                "batch_size": batch_size,
                "generation_mode": generation_mode.value,
                "seed_strategy": seed_strategy.value,
                "provider": preset.provider.value,
                "prompt_type": preset.prompt_type.value,
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
                running_task_registry.register(
                    RuntimeTaskType.GENERATION_TASK,
                    page_task.id,
                )
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
                        run = generation_repository.create_run(
                            generation_task_id=page_task.id,
                            page_id=page.id,
                            image_spec_id=spec.id,
                            tool_preset_id=preset.id,
                            provider=preset.provider,
                            prompt_type=preset.prompt_type,
                            candidate_index=candidate_index,
                            seed=seed,
                            seed_strategy=seed_strategy,
                            generation_mode=generation_mode,
                            bindings_json=preset.bindings_json,
                            resolved_assets_json=canonical_json(
                                self._resolved_assets(spec_payload)
                            ),
                            degradation_json=canonical_json(spec_degradations),
                            applied_spec_json=canonical_json(spec_payload),
                        )
                        try:
                            submission = await renderer.submit(
                                spec=spec_payload,
                                seed=seed,
                                mode=generation_mode,
                            )
                            degradations = spec_degradations + submission.degradations
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
                                degradation_json=canonical_json(degradations),
                                applied_spec_json=canonical_json(submission.applied_spec),
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
                                "degradations": degradations,
                            }
                            generation_repository.update_run(
                                run_id=run.id,
                                status=GenerationRunStatus.RUNNING,
                            )
                            artifacts = await renderer.wait(
                                submission,
                                poll_interval_seconds=poll_interval_seconds,
                                timeout_seconds=wait_timeout_seconds,
                            )
                            if not artifacts:
                                raise ValueError(
                                    f"Renderer generated no images for page: {page.page_no}"
                                )
                            for index, artifact in enumerate(artifacts, start=1):
                                local_path = self._save_image_file(
                                    project_id=page.project_id,
                                    page_no=page.page_no,
                                    request_id=submission.external_id,
                                    index=index,
                                    filename=artifact.filename,
                                    content=artifact.content,
                                )
                                sha256, width, height = self._image_metadata(artifact.content)
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
                except Exception as exc:  # noqa: BLE001 - 单页失败后继续其余页面
                    page_failed = True
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
                        "code": app_error_from_exception(exc).code,
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

    # Seed and provenance ---------------------------------------------
    def _structured_seed_pairs(
        self,
        *,
        pages: list[ComicPage],
        generation_repository: GenerationRepository,
        prompt_type: ImagePromptType,
        generation_mode: GenerationMode,
        image_spec_ids_by_page: dict[int, int],
        candidates_per_page: int,
        seed_strategy: SeedStrategy,
        continue_existing: bool,
    ) -> dict[int, list[CandidateSeedPair]]:
        existing_by_page: dict[int, dict[int, int]] = {}
        used_seeds: set[int] = set()
        shared_seeds: dict[int, int] = {}
        for page in pages:
            runs = generation_repository.list_successful_runs(
                page_id=page.id,
                prompt_type=prompt_type,
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
            if (
                isinstance(item.get("id"), int)
                and item.get("role")
                and item.get("storage_kind")
            ):
                assets[item["id"]] = {
                    key: item.get(key)
                    for key in (
                        "id",
                        "role",
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
    def _unique_random_seed(used_seeds: set[int]) -> int:
        while True:
            seed = random.randint(1, 2_147_483_647)
            if seed not in used_seeds:
                return seed

    # Validation and persistence helpers -----------------------------
    def _normalize_tool_payload(
        self,
        *,
        provider: ImageGenerationProvider,
        capabilities: dict[str, Any] | None,
        bindings: dict[str, Any] | None,
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
        capability_model = WorkflowCapabilities.model_validate(
            capabilities or {"features": ["txt2img"], "limits": {}}
        )
        if WorkflowCapability.TXT2IMG not in capability_model.features:
            raise ValueError("Workflow capabilities must include txt2img.")
        if WorkflowCapability.LORA in capability_model.features:
            raise ValueError(
                "LoRA is configured inside the ComfyUI workflow, not as a tool capability."
            )
        binding_payload = bindings or {"schema_version": 1, "bindings": []}

        if provider == ImageGenerationProvider.COMFYUI:
            workflow = self._normalize_workflow_json(
                self._required_text(workflow_json, "Workflow JSON")
            )
            if not binding_payload.get("bindings"):
                positive_node = self._required_text(
                    positive_node_id,
                    "Positive node id",
                )
                positive_input = self._required_text(
                    positive_input_name,
                    "Positive input name",
                )
                legacy_bindings: list[dict[str, str]] = [
                    {
                        "source": "prompt.positive",
                        "node_id": positive_node,
                        "input_name": positive_input,
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
                                "node_id": self._optional_text(node_id) or "",
                                "input_name": self._optional_text(input_name) or "",
                            }
                        )
                binding_payload = {"schema_version": 1, "bindings": legacy_bindings}
            binding_model = WorkflowBindings.model_validate(binding_payload)
            WorkflowCompiler().validate_configuration(
                workflow=workflow,
                capabilities=capability_model,
                bindings=binding_model,
            )
            by_source = {item.source: item for item in binding_model.bindings}
            positive = by_source["prompt.positive"]
            negative = by_source.get("prompt.negative")
            seed = by_source.get("render.seed")
            return {
                "capabilities_json": canonical_json(capability_model.model_dump(mode="json")),
                "bindings_json": canonical_json(binding_model.model_dump(mode="json")),
                "comfy_base_url": self._optional_text(comfy_base_url),
                "workflow_json": json.dumps(workflow, ensure_ascii=False),
                "positive_node_id": positive.node_id,
                "positive_input_name": positive.input_name,
                "negative_node_id": negative.node_id if negative else None,
                "negative_input_name": negative.input_name if negative else None,
                "seed_node_id": seed.node_id if seed else None,
                "seed_input_name": seed.input_name if seed else None,
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

        if provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE:
            extra_json = None
            if self._optional_text(extra_body_json):
                extra_json = json.dumps(
                    self._normalize_extra_body_json(extra_body_json or ""),
                    ensure_ascii=False,
                )
            return {
                "capabilities_json": canonical_json(capability_model.model_dump(mode="json")),
                "bindings_json": canonical_json(
                    WorkflowBindings.model_validate(binding_payload).model_dump(mode="json")
                ),
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
                # 具体模型只属于 provider 工具，不进入项目、ImageSpec 或视觉资产。
                "model": self._required_text(model, "Image API model"),
                "size": self._optional_text(size) or "1024x1024",
                "response_format": self._optional_text(response_format) or "b64_json",
                "seed_field_name": self._optional_text(seed_field_name),
                "negative_prompt_field_name": self._optional_text(
                    negative_prompt_field_name
                ),
                "extra_body_json": extra_json,
            }
        raise ValueError(f"Unsupported image generation provider: {provider.value}")

    def _ensure_generation_tool_ready(self, preset: ImageGenerationToolPreset) -> None:
        if preset.provider == ImageGenerationProvider.COMFYUI:
            if not preset.workflow_json:
                raise ValueError("Workflow JSON is required for ComfyUI image generation.")
            # seed 可不绑定；preview 会记录降级，final 则由 WorkflowCompiler 拒绝。
            return
        if preset.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE:
            self._required_text(preset.api_base_url, "Image API base URL")
            self._required_text(preset.model, "Image API model")
            return
        raise ValueError(
            f"Unsupported image generation provider: {preset.provider.value}"
        )

    def _get_tool_preset(self, preset_id: int) -> ImageGenerationToolPreset:
        preset = self.repository.get_image_generation_tool_preset(preset_id)
        if preset is None:
            raise ValueError(f"ImageGenerationToolPreset not found: {preset_id}")
        return preset

    def _get_script_task(self, task_id: int) -> ScriptGenerationTask:
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return task

    def _get_page(self, page_id: int) -> ComicPage:
        page = self.repository.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        return page

    @staticmethod
    def _normalize_workflow_json(value: str) -> dict[str, Any]:
        try:
            workflow = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Workflow JSON is invalid: {exc}") from exc
        if not isinstance(workflow, dict):
            raise ValueError("Workflow JSON must be an object.")
        return workflow

    @staticmethod
    def _normalize_extra_body_json(value: str) -> dict[str, Any]:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Extra body JSON is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Extra body JSON must be an object.")
        return payload

    @staticmethod
    def _image_metadata(content: bytes) -> tuple[str, int | None, int | None]:
        digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
        except Exception:  # noqa: BLE001 - 文件仍可保存，尺寸只是可选溯源
            return digest, None, None
        return digest, width, height

    def _save_image_file(
        self,
        *,
        project_id: int,
        page_no: int,
        request_id: str,
        index: int,
        filename: str,
        content: bytes,
    ) -> Path:
        suffix = Path(filename).suffix or ".png"
        directory = self.output_dir / f"project_{project_id}" / f"page_{page_no}"
        directory.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            char if char.isalnum() or char in "-_." else "_" for char in request_id
        )
        local_path = directory / f"{safe_id}_{index}{suffix}"
        local_path.write_bytes(content)
        return local_path

    def _is_suspended(self, task_id: int) -> bool:
        return (
            self.repository.get_generation_task_status(task_id)
            == GenerationTaskStatus.SUSPENDED
        )

    @staticmethod
    def _image_payload(image: ComicImage, page: ComicPage) -> dict[str, Any]:
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
    def _required_text(value: str | None, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty.")
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
