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
    scene_key: str | None = None
    character_keys: list[str] | None = None
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
    scene_key: str | None
    character_keys: list[str]


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
                scene_key=page.script_scene.scene_key if page.script_scene is not None else None,
                character_keys=[
                    character.character_key
                    for character in sorted(page.visual_characters, key=lambda item: item.character_key)
                ],
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
                    prompt = await self._generate_prompt(
                        agent=agent,
                        system_prompt=system_preset.content,
                        page=page,
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
                        scene_key=page.scene_key,
                        character_keys=page.character_keys,
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
                        scene_key=page.scene_key,
                        character_keys=page.character_keys,
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
                    prompt = await self._generate_prompt(
                        agent=agent,
                        system_prompt=system_preset.content,
                        page=page,
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
                        scene_key=page.scene_key,
                        character_keys=page.character_keys,
                    )
                else:
                    error_code = app_error_from_exception(ValueError(error or "")).code
                    failed += 1
                    item = ImagePromptGenerateItem(
                        page_id=page.page_id,
                        page_no=page.page_no,
                        image_prompt=None,
                        status="failed",
                        scene_key=page.scene_key,
                        character_keys=page.character_keys,
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
        scene_positions = self._scene_positions(pages)
        return (
            system_preset,
            [
                ImagePromptSourcePage(
                    page_id=page.id,
                    page_no=page.page_no,
                    page_description=self._page_description(
                        page,
                        scene_position=scene_positions.get(page.id, "standalone"),
                    ),
                    scene_key=page.script_scene.scene_key if page.script_scene is not None else None,
                    character_keys=[
                        character.character_key
                        for character in sorted(page.visual_characters, key=lambda item: item.character_key)
                    ],
                )
                for page in pages
            ],
        )

    async def _generate_prompt(
        self,
        *,
        agent: ImagePromptAgent,
        system_prompt: str,
        page: ImagePromptSourcePage,
    ) -> str:
        """生成单页 Prompt；中心化视觉设定只作为输入上下文，不拼入最终落库文本。"""

        prompt = await agent.generate(
            system_prompt=system_prompt,
            page_no=page.page_no,
            page_description=page.page_description,
        )
        return prompt.strip()

    @staticmethod
    def _scene_positions(pages: list) -> dict[int, str]:
        """计算页面在同一场景中的位置，帮助 Prompt 区分建立镜头、延续和转场。"""

        pages_by_scene_id: dict[int | None, list] = {}
        for page in pages:
            pages_by_scene_id.setdefault(page.scene_id, []).append(page)
        positions: dict[int, str] = {}
        for scene_pages in pages_by_scene_id.values():
            sorted_pages = sorted(scene_pages, key=lambda item: item.page_no)
            total = len(sorted_pages)
            for index, page in enumerate(sorted_pages):
                if total == 1:
                    positions[page.id] = "standalone"
                elif index == 0:
                    positions[page.id] = "establishing"
                elif index == total - 1:
                    positions[page.id] = "transition"
                else:
                    positions[page.id] = "continuation"
        return positions

    @staticmethod
    def _visual_consistency_context(page, *, scene_position: str) -> str:
        """构造最终 Prompt 必须携带的视觉锁定上下文，强化跨页一致性。"""

        scene = page.script_scene
        lines = [
            "VISUAL CONSISTENCY LOCK",
            f"scene_key: {scene.scene_key if scene is not None else ''}",
            f"scene_name: {scene.name if scene is not None else ''}",
            f"scene_position: {scene_position}",
            f"location_type: {scene.location_type if scene is not None else ''}",
            f"time_of_day: {scene.time_of_day if scene is not None else ''}",
            f"lighting: {scene.lighting if scene is not None else ''}",
            f"weather: {scene.weather if scene is not None else ''}",
            f"environment_details: {scene.environment_details if scene is not None else ''}",
            f"scene_color_palette: {scene.color_palette if scene is not None else ''}",
            f"scene_visual_anchors: {scene.visual_anchors if scene is not None else ''}",
            f"scene_negative_constraints: {scene.negative_constraints if scene is not None else ''}",
        ]
        characters = sorted(page.visual_characters, key=lambda item: item.character_key)
        if characters:
            lines.append("CHARACTER CONSISTENCY LOCK")
        for character in characters:
            baseline = character.outline_character
            lines.extend(
                [
                    f"character_key: {character.character_key}",
                    f"name: {character.name}",
                    f"baseline_role: {baseline.role if baseline is not None else ''}",
                    f"baseline_background: {baseline.background if baseline is not None else ''}",
                    f"baseline_appearance: {baseline.appearance if baseline is not None else ''}",
                    f"baseline_visual_anchors: {baseline.visual_anchors if baseline is not None else ''}",
                    f"default_hairstyle: {baseline.default_hairstyle if baseline is not None else ''}",
                    f"default_clothing: {baseline.default_clothing if baseline is not None else ''}",
                    f"default_accessories: {baseline.default_accessories if baseline is not None else ''}",
                    f"default_color_palette: {baseline.default_color_palette if baseline is not None else ''}",
                    f"section_role: {character.section_role}",
                    f"current_hairstyle: {character.current_hairstyle}",
                    f"current_clothing: {character.current_clothing}",
                    f"current_accessories: {character.current_accessories}",
                    f"current_state: {character.current_state}",
                    f"emotion: {character.emotion}",
                    f"temporary_changes: {character.temporary_changes}",
                    f"character_visual_anchors: {character.visual_anchors}",
                    f"character_negative_constraints: {character.negative_constraints}",
                ]
            )
        return "\n".join(line for line in lines if line.strip())

    @staticmethod
    def _page_description(page, *, scene_position: str) -> str:
        """把结构化分页脚本拼成图片 Prompt Agent 可理解的页面描述。"""

        scene = page.script_scene
        character_lines = []
        for character in sorted(page.visual_characters, key=lambda item: item.character_key):
            baseline = character.outline_character
            character_lines.append(
                "\n".join(
                    [
                        f"- 角色 key：{character.character_key}",
                        f"  名称：{character.name}",
                        f"  大纲身份：{baseline.role if baseline is not None else ''}",
                        f"  大纲背景：{baseline.background if baseline is not None else ''}",
                        f"  固定样貌：{baseline.appearance if baseline is not None else ''}",
                        f"  固定识别锚点：{baseline.visual_anchors if baseline is not None else ''}",
                        f"  默认发型：{baseline.default_hairstyle if baseline is not None else ''}",
                        f"  默认服装：{baseline.default_clothing if baseline is not None else ''}",
                        f"  默认配件：{baseline.default_accessories if baseline is not None else ''}",
                        f"  默认色彩：{baseline.default_color_palette if baseline is not None else ''}",
                        f"  当前分段身份/状态：{character.section_role}",
                        f"  当前发型：{character.current_hairstyle}",
                        f"  当前服装：{character.current_clothing}",
                        f"  当前配件：{character.current_accessories}",
                        f"  当前身体状态：{character.current_state}",
                        f"  当前情绪：{character.emotion}",
                        f"  临时变化：{character.temporary_changes}",
                        f"  当前分段视觉锚点：{character.visual_anchors}",
                        f"  当前分段禁止变化：{character.negative_constraints}",
                    ]
                )
            )
        return "\n".join(
            [
                "【中心化场景设定】",
                ImagePromptService._visual_consistency_context(
                    page,
                    scene_position=scene_position,
                ),
                f"场景 key：{scene.scene_key if scene is not None else ''}",
                f"场景名称：{scene.name if scene is not None else ''}",
                f"地点类型：{scene.location_type if scene is not None else ''}",
                f"时间：{scene.time_of_day if scene is not None else ''}",
                f"固定光线：{scene.lighting if scene is not None else ''}",
                f"天气/空气：{scene.weather if scene is not None else ''}",
                f"稳定环境细节：{scene.environment_details if scene is not None else ''}",
                f"场景色彩：{scene.color_palette if scene is not None else ''}",
                f"场景视觉锚点：{scene.visual_anchors if scene is not None else ''}",
                f"场景禁止变化：{scene.negative_constraints if scene is not None else ''}",
                f"本页在该场景中的位置：{scene_position}",
                "【中心化角色设定】",
                "\n".join(character_lines) if character_lines else "无固定角色出场。",
                "【本页局部变化】",
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
            "scene_key": item.scene_key,
            "character_keys": item.character_keys or [],
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
