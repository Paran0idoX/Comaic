import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import random
from typing import Any, AsyncIterator

from backend.models.comic import ComicImage, ComicPage, ComfyWorkflowPreset, GenerationTask
from backend.models.enums import ComicPageStatus, GenerationTaskStatus
from backend.repositories.comic_repository import ComicRepository
from backend.tools.comfyui_client import ComfyUIClient


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

    def list_workflow_presets(self) -> list[ComfyWorkflowPreset]:
        """读取页面维护的 ComfyUI workflow 配置。"""

        return self.repository.list_comfy_workflow_presets()

    def create_workflow_preset(
        self,
        *,
        name: str,
        workflow_json: str,
        positive_node_id: str,
        positive_input_name: str,
        description: str | None = None,
        is_default: bool = False,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
    ) -> ComfyWorkflowPreset:
        """创建 workflow 配置，并校验 JSON 与正向 Prompt 节点是否可注入。"""

        normalized_workflow = self._normalize_workflow_json(workflow_json)
        positive_node_id = self._required_text(positive_node_id, "Positive node id")
        positive_input_name = self._required_text(positive_input_name, "Positive input name")
        self._validate_workflow_input(normalized_workflow, positive_node_id, positive_input_name)
        return self.repository.create_comfy_workflow_preset(
            name=self._required_text(name, "Workflow name"),
            description=self._optional_text(description),
            workflow_json=json.dumps(normalized_workflow, ensure_ascii=False),
            is_default=is_default,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=self._optional_text(negative_node_id),
            negative_input_name=self._optional_text(negative_input_name),
            seed_node_id=self._optional_text(seed_node_id),
            seed_input_name=self._optional_text(seed_input_name),
        )

    def update_workflow_preset(
        self,
        *,
        preset_id: int,
        name: str,
        workflow_json: str,
        positive_node_id: str,
        positive_input_name: str,
        description: str | None = None,
        is_default: bool = False,
        negative_node_id: str | None = None,
        negative_input_name: str | None = None,
        seed_node_id: str | None = None,
        seed_input_name: str | None = None,
    ) -> ComfyWorkflowPreset:
        """更新 workflow 配置；校验逻辑与创建保持一致。"""

        normalized_workflow = self._normalize_workflow_json(workflow_json)
        positive_node_id = self._required_text(positive_node_id, "Positive node id")
        positive_input_name = self._required_text(positive_input_name, "Positive input name")
        self._validate_workflow_input(normalized_workflow, positive_node_id, positive_input_name)
        return self.repository.update_comfy_workflow_preset(
            preset_id=preset_id,
            name=self._required_text(name, "Workflow name"),
            description=self._optional_text(description),
            workflow_json=json.dumps(normalized_workflow, ensure_ascii=False),
            is_default=is_default,
            positive_node_id=positive_node_id,
            positive_input_name=positive_input_name,
            negative_node_id=self._optional_text(negative_node_id),
            negative_input_name=self._optional_text(negative_input_name),
            seed_node_id=self._optional_text(seed_node_id),
            seed_input_name=self._optional_text(seed_input_name),
        )

    def delete_workflow_preset(self, preset_id: int) -> None:
        """删除 workflow 配置，不影响已生成图片。"""

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
        workflow_preset_id: int,
        poll_interval_seconds: float = 2.0,
        candidates_per_page: int = 1,
        negative_prompt: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """按脚本任务批量生成图片；当前实现按页顺序提交，便于稳定暂停。"""

        script_task = self.repository.get_script_task(task_id)
        if script_task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        preset = self._get_workflow_preset(workflow_preset_id)
        pages = [
            page for page in self.repository.list_script_task_pages(task_id)
            if page.image_prompt
        ]
        if not pages:
            raise ValueError(f"Image prompts not found for script task: {task_id}")

        batch_task = self.repository.create_generation_task(
            project_id=script_task.project_id,
            page_id=None,
            batch_size=len(pages) * candidates_per_page,
        )
        batch_task = self.repository.update_generation_task(
            task_id=batch_task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        yield "start", {
            "task_id": batch_task.id,
            "script_task_id": script_task.id,
            "total": len(pages),
            "status": batch_task.status.value,
        }

        completed = 0
        succeeded = 0
        failed = 0
        try:
            for page in pages:
                if self._is_suspended(batch_task.id):
                    yield "suspended", {"task_id": batch_task.id, "status": GenerationTaskStatus.SUSPENDED.value}
                    return

                page_task = self.repository.create_generation_task(
                    project_id=script_task.project_id,
                    page_id=page.id,
                    batch_size=candidates_per_page,
                )
                page_task = self.repository.update_generation_task(
                    task_id=page_task.id,
                    status=GenerationTaskStatus.RUNNING,
                )
                yield "page_task", {
                    "task_id": batch_task.id,
                    "page_task_id": page_task.id,
                    "page_id": page.id,
                    "page_no": page.page_no,
                    "status": page_task.status.value,
                }

                try:
                    image_count = 0
                    async for event, payload in self._stream_page_images(
                        page=page,
                        page_task_id=page_task.id,
                        preset=preset,
                        candidates_per_page=candidates_per_page,
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
                        "message": str(exc),
                    }

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

    async def stream_generate_for_page(
        self,
        *,
        page_id: int,
        workflow_preset_id: int,
        poll_interval_seconds: float = 2.0,
        candidates_per_page: int = 1,
        negative_prompt: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """单页生成图片，供失败页面补跑或追加候选图。"""

        page = self._get_page(page_id)
        if not page.image_prompt:
            raise ValueError(f"Image prompt not found for page: {page_id}")
        preset = self._get_workflow_preset(workflow_preset_id)
        task = self.repository.create_generation_task(
            project_id=page.project_id,
            page_id=page.id,
            batch_size=candidates_per_page,
        )
        task = self.repository.update_generation_task(
            task_id=task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        yield "start", {"task_id": task.id, "total": 1, "status": task.status.value}
        image_count = 0
        async for event, payload in self._stream_page_images(
            page=page,
            page_task_id=task.id,
            preset=preset,
            candidates_per_page=candidates_per_page,
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

    def select_image(self, *, page_id: int, image_id: int) -> ComicPage:
        """人工选择某页最终图片。"""

        return self.repository.select_image(page_id=page_id, image_id=image_id)

    def _get_workflow_preset(self, preset_id: int) -> ComfyWorkflowPreset:
        """读取 workflow preset，不存在时给出明确错误。"""

        preset = self.repository.get_comfy_workflow_preset(preset_id)
        if preset is None:
            raise ValueError(f"ComfyWorkflowPreset not found: {preset_id}")
        return preset

    def _get_page(self, page_id: int) -> ComicPage:
        """按 id 读取页面。"""

        page = self.repository.session.get(ComicPage, page_id)
        if page is None:
            raise ValueError(f"ComicPage not found: {page_id}")
        return page

    async def _generate_page_images(
        self,
        *,
        page: ComicPage,
        page_task_id: int,
        preset: ComfyWorkflowPreset,
        candidates_per_page: int,
        poll_interval_seconds: float,
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> list[ComicImage]:
        """提交单页 workflow，等待 ComfyUI 完成后下载并落库图片。"""

        saved_images: list[ComicImage] = []
        for _ in range(candidates_per_page):
            workflow, seed = self._build_workflow(
                preset=preset,
                positive_prompt=page.image_prompt or "",
                negative_prompt=negative_prompt,
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
        preset: ComfyWorkflowPreset,
        candidates_per_page: int,
        poll_interval_seconds: float,
        negative_prompt: str | None,
        batch_task_id: int,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """提交并保存单页图片，同时实时产出 queued/polling/image 事件。"""

        for _ in range(candidates_per_page):
            workflow, seed = self._build_workflow(
                preset=preset,
                positive_prompt=page.image_prompt or "",
                negative_prompt=negative_prompt,
            )
            prompt_id = await asyncio.to_thread(self.comfy_client.queue_prompt, workflow)
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
            }

            poll_count = 0
            while True:
                poll_count += 1
                history = await asyncio.to_thread(self.comfy_client.get_history, prompt_id)
                output_images = self.comfy_client.extract_output_images(history, prompt_id)
                if output_images:
                    break
                yield "polling", {
                    "task_id": batch_task_id,
                    "page_task_id": page_task_id,
                    "page_id": page.id,
                    "page_no": page.page_no,
                    "comfy_prompt_id": prompt_id,
                    "poll_count": poll_count,
                }
                await asyncio.sleep(poll_interval_seconds)

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
                image = self.repository.add_image(
                    page_id=page.id,
                    prompt=page.image_prompt or "",
                    negative_prompt=negative_prompt,
                    local_path=str(local_path),
                    seed=seed,
                    workflow_name=preset.name,
                )
                yield "image", self._image_payload(image, page)

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
        preset: ComfyWorkflowPreset,
        positive_prompt: str,
        negative_prompt: str | None,
    ) -> tuple[dict[str, Any], int | None]:
        """复制 workflow preset 并注入正向 Prompt、可选负向 Prompt 和随机 seed。"""

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
        seed: int | None = None
        if preset.seed_node_id and preset.seed_input_name:
            seed = random.randint(1, 2_147_483_647)
            self._set_workflow_input(
                workflow,
                node_id=preset.seed_node_id,
                input_name=preset.seed_input_name,
                value=seed,
            )
        return workflow, seed

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
        local_path = directory / f"{prompt_id}_{index}{suffix}"
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
            "page_no": page.page_no,
            "image_url": f"/api/image-generation/images/{image.id}/file",
            "local_path": image.local_path,
            "seed": image.seed,
            "workflow_name": image.workflow_name,
            "prompt": image.prompt,
            "negative_prompt": image.negative_prompt,
            "score": image.score,
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
