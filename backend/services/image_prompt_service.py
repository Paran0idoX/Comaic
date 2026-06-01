import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from backend.agents.image_prompt_agent import ImagePromptAgent
from backend.i18n.errors import app_error_from_exception
from backend.models.comic import ImagePromptPreset, ScriptGenerationTask
from backend.models.enums import ImagePromptPresetKind, ScriptGenerationTaskStatus
from backend.repositories.comic_repository import ComicRepository
from backend.utils.prompt_loader import PromptLoader


@dataclass
class ImagePromptGenerateItem:
    """单页图片 Prompt 生成结果，包含成功页面或失败原因。"""

    page_id: int
    page_no: int
    image_prompt: str | None
    status: str
    error: str | None = None
    error_code: str | None = None


@dataclass
class ImagePromptGenerateResult:
    """脚本任务批量生成图片 Prompt 的汇总结果。"""

    task_id: int
    total: int
    succeeded: int
    failed: int
    items: list[ImagePromptGenerateItem]


@dataclass(frozen=True)
class ImagePromptSourcePage:
    """图片 Prompt 生成时使用的页面快照，避免并发任务直接持有 ORM 对象。"""

    page_id: int
    page_no: int
    page_description: str


class ImagePromptService:
    """图片 Prompt 业务服务，负责配置维护、并发生成和页面 Prompt 保存。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository；Agent 只负责生成文本，不直接操作数据库。"""

        self.repository = repository

    def list_presets(self, kind: ImagePromptPresetKind | None = None) -> list[ImagePromptPreset]:
        """读取图片 Prompt 配置；首次使用时自动初始化默认配置。"""

        self.ensure_default_presets()
        return self.repository.list_image_prompt_presets(kind)

    def create_preset(
        self,
        *,
        name: str,
        kind: ImagePromptPresetKind,
        content: str,
        description: str | None = None,
        is_default: bool = False,
    ) -> ImagePromptPreset:
        """创建图片 Prompt 配置。"""

        return self.repository.create_image_prompt_preset(
            name=self._required_text(name, "Preset name"),
            kind=kind,
            content=self._required_text(content, "Preset content"),
            description=self._optional_text(description),
            is_default=is_default,
        )

    def update_preset(
        self,
        *,
        preset_id: int,
        name: str,
        kind: ImagePromptPresetKind,
        content: str,
        description: str | None = None,
        is_default: bool = False,
    ) -> ImagePromptPreset:
        """更新图片 Prompt 配置。"""

        return self.repository.update_image_prompt_preset(
            preset_id=preset_id,
            name=self._required_text(name, "Preset name"),
            kind=kind,
            content=self._required_text(content, "Preset content"),
            description=self._optional_text(description),
            is_default=is_default,
        )

    def delete_preset(self, preset_id: int) -> None:
        """删除图片 Prompt 配置，不影响已经保存到页面的 Prompt。"""

        self.repository.delete_image_prompt_preset(preset_id)

    def list_completed_script_tasks(self, project_id: int) -> list[ScriptGenerationTask]:
        """读取项目下已完成脚本任务，供前端选择生成范围。"""

        if self.repository.get_project(project_id) is None:
            raise ValueError(f"ComicProject not found: {project_id}")
        return self.repository.list_script_tasks(
            project_id=project_id,
            status=ScriptGenerationTaskStatus.SUCCEEDED,
        )

    def list_script_task_image_prompts(self, task_id: int) -> ImagePromptGenerateResult:
        """读取某次脚本任务下已落库的图片 Prompt，用于前端切换任务时回显。"""

        task = self._get_succeeded_script_task(task_id)
        pages = [page for page in self.repository.list_script_task_pages(task.id) if page.summary]
        items = [
            ImagePromptGenerateItem(
                page_id=page.id,
                page_no=page.page_no,
                image_prompt=page.image_prompt,
                status=page.status.value,
            )
            for page in pages
        ]
        succeeded = sum(1 for item in items if item.image_prompt)
        return ImagePromptGenerateResult(
            task_id=task.id,
            total=len(items),
            succeeded=succeeded,
            failed=0,
            items=sorted(items, key=lambda item: item.page_no),
        )

    async def generate_for_script_task(
        self,
        *,
        task_id: int,
        system_prompt_preset_id: int,
        concurrency: int = 20,
    ) -> ImagePromptGenerateResult:
        """为已完成脚本任务下的全部页面并发生成图片 Prompt。"""

        system_preset, source_pages = self._prepare_generation(
            task_id=task_id,
            system_prompt_preset_id=system_prompt_preset_id,
            clear_existing=True,
        )

        normalized_concurrency = max(1, min(concurrency, 50))
        semaphore = asyncio.Semaphore(normalized_concurrency)
        agent = ImagePromptAgent()

        async def generate_one(
            page: ImagePromptSourcePage,
        ) -> tuple[ImagePromptSourcePage, str | None, str | None]:
            """限制并发调用 LLM，返回页面与生成结果，数据库写入在外层顺序完成。"""

            async with semaphore:
                try:
                    prompt = await agent.generate(
                        system_prompt=system_preset.content,
                        page_no=page.page_no,
                        page_description=page.page_description,
                    )
                    if not prompt:
                        raise ValueError("Generated image prompt cannot be empty.")
                    return page, prompt, None
                except Exception as exc:  # noqa: BLE001 - 单页失败要汇总返回，不中断其他页
                    return page, None, str(exc)

        generated = await asyncio.gather(*(generate_one(page) for page in source_pages))

        items: list[ImagePromptGenerateItem] = []
        succeeded = 0
        failed = 0
        for page, prompt, error in generated:
            if prompt is not None:
                saved_page = self.repository.update_page_prompt(page.page_id, prompt)
                succeeded += 1
                items.append(
                    ImagePromptGenerateItem(
                        page_id=saved_page.id,
                        page_no=saved_page.page_no,
                        image_prompt=saved_page.image_prompt,
                        status=saved_page.status.value,
                    )
                )
            else:
                error_code = app_error_from_exception(ValueError(error or "")).code
                failed += 1
                items.append(
                    ImagePromptGenerateItem(
                        page_id=page.page_id,
                        page_no=page.page_no,
                        image_prompt=None,
                        status="failed",
                        error=error_code,
                        error_code=error_code,
                    )
                )

        return ImagePromptGenerateResult(
            task_id=task_id,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            items=sorted(items, key=lambda item: item.page_no),
        )

    async def stream_generate_for_script_task(
        self,
        *,
        task_id: int,
        system_prompt_preset_id: int,
        concurrency: int = 20,
    ) -> AsyncIterator[tuple[str, dict]]:
        """流式生成图片 Prompt；每页落库后立即向 API 层交出 SSE payload。"""

        system_preset, source_pages = self._prepare_generation(
            task_id=task_id,
            system_prompt_preset_id=system_prompt_preset_id,
            clear_existing=True,
        )
        total = len(source_pages)
        yield "start", {
            "task_id": task_id,
            "total": total,
        }

        normalized_concurrency = max(1, min(concurrency, 50))
        semaphore = asyncio.Semaphore(normalized_concurrency)
        queue: asyncio.Queue[tuple[ImagePromptSourcePage, str | None, str | None]] = asyncio.Queue()
        agent = ImagePromptAgent()

        async def generate_one(page: ImagePromptSourcePage) -> None:
            """并发生成单页 Prompt，并把结果放入队列等待主协程顺序落库。"""

            async with semaphore:
                try:
                    prompt = await agent.generate(
                        system_prompt=system_preset.content,
                        page_no=page.page_no,
                        page_description=page.page_description,
                    )
                    if not prompt:
                        raise ValueError("Generated image prompt cannot be empty.")
                    await queue.put((page, prompt, None))
                except Exception as exc:  # noqa: BLE001 - 单页失败通过 SSE 返回，不中断整批任务
                    await queue.put((page, None, str(exc)))

        tasks = [asyncio.create_task(generate_one(page)) for page in source_pages]
        completed = 0
        succeeded = 0
        failed = 0
        try:
            for _ in source_pages:
                page, prompt, error = await queue.get()
                completed += 1
                if prompt is not None:
                    saved_page = self.repository.update_page_prompt(page.page_id, prompt)
                    succeeded += 1
                    item = ImagePromptGenerateItem(
                        page_id=saved_page.id,
                        page_no=saved_page.page_no,
                        image_prompt=saved_page.image_prompt,
                        status=saved_page.status.value,
                    )
                else:
                    error_code = app_error_from_exception(ValueError(error or "")).code
                    failed += 1
                    item = ImagePromptGenerateItem(
                        page_id=page.page_id,
                        page_no=page.page_no,
                        image_prompt=None,
                        status="failed",
                        error=error_code,
                        error_code=error_code,
                    )

                yield "page_prompt", self._item_payload(item)
                yield "progress", {
                    "task_id": task_id,
                    "completed": completed,
                    "succeeded": succeeded,
                    "failed": failed,
                    "total": total,
                }

            await asyncio.gather(*tasks)
            yield "done", {
                "task_id": task_id,
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
            }
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    def ensure_default_presets(self) -> None:
        """初始化两类默认配置，保证新库打开页面即可使用。"""

        if not self.repository.list_image_prompt_presets(
            ImagePromptPresetKind.SCRIPT_TO_IMAGE_SYSTEM_PROMPT
        ):
            self.repository.create_image_prompt_preset(
                name="Default script to image prompt",
                description="Convert a full-page comic script into an English image prompt.",
                kind=ImagePromptPresetKind.SCRIPT_TO_IMAGE_SYSTEM_PROMPT,
                content=PromptLoader.load("image_prompt_system_prompt.md"),
                is_default=True,
            )
        if not self.repository.list_image_prompt_presets(ImagePromptPresetKind.NEGATIVE_PROMPT):
            self.repository.create_image_prompt_preset(
                name="Default negative prompt",
                description="Generic negative prompt for comic image generation.",
                kind=ImagePromptPresetKind.NEGATIVE_PROMPT,
                content="low quality, blurry, bad anatomy, extra fingers, text artifacts, watermark",
                is_default=True,
            )

    def _get_preset(
        self,
        *,
        preset_id: int,
        expected_kind: ImagePromptPresetKind,
    ) -> ImagePromptPreset:
        """读取并校验配置类型，避免 SystemPrompt 与 Negative Prompt 混用。"""

        preset = self.repository.get_image_prompt_preset(preset_id)
        if preset is None:
            raise ValueError(f"ImagePromptPreset not found: {preset_id}")
        if preset.kind != expected_kind:
            raise ValueError(f"ImagePromptPreset {preset_id} kind must be {expected_kind.value}.")
        return preset

    def _get_succeeded_script_task(self, task_id: int) -> ScriptGenerationTask:
        """读取并校验已完成脚本任务，图片 Prompt 只面向稳定脚本生成。"""

        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if task.status != ScriptGenerationTaskStatus.SUCCEEDED:
            raise ValueError("ScriptGenerationTask must be succeeded before generating image prompts.")
        return task

    def _prepare_generation(
        self,
        *,
        task_id: int,
        system_prompt_preset_id: int,
        clear_existing: bool,
    ) -> tuple[ImagePromptPreset, list[ImagePromptSourcePage]]:
        """统一准备图片 Prompt 生成上下文；重新生成时先清空旧 Prompt。"""

        self.ensure_default_presets()
        task = self._get_succeeded_script_task(task_id)
        system_preset = self._get_preset(
            preset_id=system_prompt_preset_id,
            expected_kind=ImagePromptPresetKind.SCRIPT_TO_IMAGE_SYSTEM_PROMPT,
        )
        pages = [page for page in self.repository.list_script_task_pages(task.id) if page.summary]
        if not pages:
            raise ValueError(f"Script pages not found for task: {task_id}")
        if clear_existing:
            self.repository.clear_script_task_image_prompts(task.id)
        return (
            system_preset,
            [
                ImagePromptSourcePage(
                    page_id=page.id,
                    page_no=page.page_no,
                    page_description=self._page_description(page),
                )
                for page in pages
            ],
        )

    @staticmethod
    def _page_description(page) -> str:
        """把结构化分页脚本拼成图片 Prompt Agent 可理解的页面描述。"""

        return "\n".join(
            [
                f"本页摘要：{page.summary or ''}",
                f"人物：{page.characters or ''}",
                f"服装：{page.clothing or ''}",
                f"场景：{page.scene or ''}",
                f"构图：{page.composition or ''}",
                f"人物动作：{page.character_action or ''}",
                f"对话：{page.dialogue or ''}",
            ]
        ).strip()

    @staticmethod
    def _item_payload(item: ImagePromptGenerateItem) -> dict:
        """把单页生成结果转成可 JSON 序列化的 SSE payload。"""

        return {
            "page_id": item.page_id,
            "page_no": item.page_no,
            "image_prompt": item.image_prompt,
            "status": item.status,
            "error": item.error,
            "error_code": item.error_code,
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
