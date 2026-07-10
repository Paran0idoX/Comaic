import asyncio
import json
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar

from backend.agents.page_script_writer_agent import PageScriptWriterAgent
from backend.agents.script_planning_agent import ScriptPlanningAgent
from backend.agents.script_supervisor_agent import ScriptSupervisorAgent
from backend.i18n.errors import app_error_from_exception
from backend.models.comic import (
    ComicPage,
    ComicProject,
    OutlineCharacter,
    OutlineVersion,
    ScriptCharacter,
    ScriptGenerationTask,
    ScriptScene,
    ScriptSection,
)
from backend.models.enums import (
    PageScriptReviewStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
    ScriptSectionStatus,
)
from backend.repositories.comic_repository import ComicRepository
from backend.services.task_runtime import RuntimeTaskType, running_task_registry


AgentResultT = TypeVar("AgentResultT")
logger = logging.getLogger(__name__)


class SectionGenerationError(Exception):
    """分段生成失败，并携带本次应标记为异常的页码。"""

    def __init__(self, message: str, *, page_nos: list[int]):
        super().__init__(message)
        self.page_nos = page_nos


@dataclass
class PendingSectionReview:
    """当前 SSE 批次内的异步分段审查任务。"""

    section: ScriptSection
    pages: list[dict]
    visual_context: dict
    review_round: int
    task: asyncio.Task[dict]


@dataclass
class SectionGenerationJob:
    """分段并发 worker 的输入快照，避免 worker 临时读取会变化的上下文。"""

    section: ScriptSection
    visual_context: dict
    previous_context: dict
    target_page_nos: list[int]
    existing_pages_by_no: dict[int, dict]


class ScriptService:
    """分页脚本业务服务，负责任务编排、页面脚本落库和 SSE 事件产出。"""

    def __init__(self, repository: ComicRepository):
        """注入 Repository，Agent 生成结果统一由 Service 决定如何落库。"""

        self.repository = repository

    def get_script_task(self, task_id: int) -> ScriptGenerationTask:
        """读取脚本生成任务；不存在时抛出明确错误。"""

        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        return task

    def list_project_pages(self, *, project_id: int) -> list[ComicPage]:
        """读取项目页面脚本，供 API 展示生成结果。"""

        self._get_project(project_id)
        return self.repository.list_project_pages(project_id)

    def list_script_tasks(
        self,
        *,
        project_id: int,
        outline_version_id: int | None = None,
        mode: ScriptGenerationMode | None = None,
        status: ScriptGenerationTaskStatus | None = None,
    ) -> list[ScriptGenerationTask]:
        """读取项目下脚本任务；分页脚本页会按大纲版本筛选。"""

        self._get_project(project_id)
        if outline_version_id is not None:
            outline_version = self.repository.get_outline_version(outline_version_id)
            if outline_version is None:
                raise ValueError(f"OutlineVersion not found: {outline_version_id}")
            if outline_version.session.project_id != project_id:
                raise ValueError("OutlineVersion does not belong to project.")
        return self.repository.list_script_tasks(
            project_id=project_id,
            outline_version_id=outline_version_id,
            mode=mode,
            status=status,
        )

    def list_script_task_pages(self, *, task_id: int) -> list[ComicPage]:
        """读取指定脚本任务下的页面脚本，避免项目级页面混入其它任务。"""

        self.get_script_task(task_id)
        return self.repository.list_script_task_pages(task_id)

    def list_script_scenes(self, *, task_id: int) -> list[ScriptScene]:
        """读取指定脚本任务下的中心化场景设定。"""

        self.get_script_task(task_id)
        return self.repository.list_script_scenes(task_id)

    def list_script_characters(self, *, task_id: int) -> list[ScriptCharacter]:
        """读取指定脚本任务下的中心化角色设定。"""

        self.get_script_task(task_id)
        return self.repository.list_script_characters(task_id)

    def upsert_manual_page_script(
        self,
        *,
        project_id: int,
        page_no: int,
        task_id: int | None = None,
        summary: str,
        characters: str,
        clothing: str,
        scene: str,
        composition: str,
        character_action: str,
        dialogue: str,
    ) -> ComicPage:
        """人工新增或更新结构化单页脚本；生成任务结束后由前端编辑使用。"""

        self._get_project(project_id)
        page_payload = self._normalize_manual_page_payload(
            summary=summary,
            characters=characters,
            clothing=clothing,
            scene=scene,
            composition=composition,
            character_action=character_action,
            dialogue=dialogue,
        )
        section = self._resolve_manual_section(project_id=project_id, page_no=page_no, task_id=task_id)
        return self.repository.upsert_page_script(
            project_id=project_id,
            page_no=page_no,
            section_id=section.id,
            **page_payload,
        )

    def clear_page_script(
        self,
        *,
        project_id: int,
        page_no: int,
        task_id: int | None = None,
    ) -> ComicPage:
        """人工清空单页脚本；不删除页面行，避免破坏后续关联数据。"""

        self._get_project(project_id)
        if task_id is not None:
            task = self.get_script_task(task_id)
            if task.project_id != project_id:
                raise ValueError("ScriptGenerationTask does not belong to project.")
            page = self.repository.get_script_task_page(task_id=task_id, page_no=page_no)
            if page is None:
                raise ValueError(f"ComicPage not found for task {task_id}: {page_no}")
            return self.repository.clear_page_script_by_id(page.id)
        return self.repository.clear_page_script(project_id=project_id, page_no=page_no)

    def delete_project_pages(self, *, project_id: int) -> None:
        """硬删除当前项目的全部页面数据行，供前端“删除全部脚本”使用。"""

        self._get_project(project_id)
        self.repository.delete_project_pages(project_id)

    def list_script_task_sections(self, *, task_id: int) -> list[ScriptSection]:
        """读取脚本任务下的分段内容，供前端后续按分段展示页面。"""

        self.get_script_task(task_id)
        return self.repository.list_script_sections(task_id)

    def delete_script_task_sections(self, *, task_id: int) -> None:
        """删除脚本任务下全部分段，并同步删除分段下的页面脚本。"""

        self.get_script_task(task_id)
        self.repository.delete_script_task_sections(task_id)

    def suspend_script_task(self, *, task_id: int) -> ScriptGenerationTask:
        """暂停批量脚本任务；运行中的 SSE 流会轮询该状态并停止 Agent。"""

        self.get_script_task(task_id)
        return self.repository.suspend_script_task(task_id)

    async def generate_single_page_script(
        self,
        *,
        project_id: int,
        page_no: int,
        total_pages: int,
        outline_version_id: int | None = None,
        user_requirement: str | None = None,
    ) -> tuple[ScriptGenerationTask, ComicPage]:
        """同步生成单页脚本并保存到 comic_page。"""

        self._validate_page_args(page_no=page_no, total_pages=total_pages)
        outline_version = self._resolve_outline_version(
            project_id=project_id,
            outline_version_id=outline_version_id,
        )
        task = self.repository.create_script_task(
            project_id=project_id,
            outline_version_id=outline_version.id,
            mode=ScriptGenerationMode.SINGLE,
            status=ScriptGenerationTaskStatus.RUNNING,
            total_pages=total_pages,
            target_page_no=page_no,
            user_requirement=user_requirement,
        )
        running_task_registry.register(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)

        try:
            section = self._create_single_page_section(
                task_id=task.id,
                page_no=page_no,
            )
            outline_characters = self._outline_characters_context(outline_version.id)
            section_scenes = [self._default_single_page_scene()]
            section_characters = self._default_single_page_characters(outline_characters)
            self._save_section_visual_settings(
                task_id=task.id,
                section_id=section.id,
                outline_version_id=outline_version.id,
                scenes=section_scenes,
                characters=section_characters,
            )
            writer_agent = PageScriptWriterAgent()
            supervisor_agent = ScriptSupervisorAgent()
            previous_context = {"completed_section_summaries": [], "recent_full_sections": []}
            feedback = ""
            normalized_pages: list[dict] | None = None
            for attempt in range(1, 4):
                pages = await writer_agent.generate_page(
                    outline=outline_version.content,
                    total_pages=total_pages,
                    current_section=self._section_to_payload(section),
                    target_page_no=page_no,
                    section_scenes=section_scenes,
                    section_characters=section_characters,
                    previous_context=previous_context,
                    outline_characters=outline_characters,
                    user_requirement=user_requirement or "",
                    feedback=feedback,
                )
                normalized_pages = self._normalize_single_page(
                    pages=pages,
                    section=section,
                    page_no=page_no,
                )
                review_result = await supervisor_agent.review_section_pages(
                    outline=outline_version.content,
                    current_section=self._section_to_payload(section),
                    section_scenes=section_scenes,
                    section_characters=section_characters,
                    outline_characters=outline_characters,
                    pages=normalized_pages,
                )
                if self._section_review_passed(review_result):
                    break
                feedback = self._review_feedback(review_result.get("reviews", []))
                if attempt >= 3:
                    raise ValueError(f"单页脚本连续 3 次监督未通过：{feedback}")
            if normalized_pages is None:
                raise ValueError(f"Generated script missing page_no: {page_no}")
            page_payload = self._find_page_payload(normalized_pages, page_no)
            visual_settings = self._visual_settings_for_section(
                task_id=task.id,
                section_id=section.id,
                outline_version_id=outline_version.id,
                pages=normalized_pages,
            )
            page = self.repository.upsert_page_script(
                project_id=project_id,
                page_no=page_no,
                section_id=section.id,
                scene_id=visual_settings["scene_ids_by_key"][page_payload["scene_key"]],
                character_ids=[
                    visual_settings["character_ids_by_key"][key]
                    for key in page_payload.get("character_keys", [])
                ],
                **self._page_payload_for_save(page_payload),
            )
            self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
            )
            task = self.get_script_task(task.id)
            return task, page
        except Exception as exc:
            self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            raise
        finally:
            running_task_registry.unregister(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)

    async def stream_batch_script_generation(
        self,
        *,
        project_id: int,
        total_pages: int,
        outline_version_id: int | None = None,
        user_requirement: str | None = None,
    ):
        """批量生成分页脚本，并以事件形式返回任务进度。"""

        self._validate_total_pages(total_pages)
        outline_version = self._resolve_outline_version(
            project_id=project_id,
            outline_version_id=outline_version_id,
        )
        task = self.repository.create_script_task(
            project_id=project_id,
            outline_version_id=outline_version.id,
            mode=ScriptGenerationMode.BATCH,
            status=ScriptGenerationTaskStatus.RUNNING,
            total_pages=total_pages,
            user_requirement=user_requirement,
        )
        running_task_registry.register(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)
        try:
            async for event, payload in self._stream_batch_task(
                task=task,
                outline_version=outline_version,
                user_requirement=user_requirement or "",
                is_continue=False,
            ):
                yield event, payload
        finally:
            running_task_registry.unregister(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)

    async def stream_continue_batch_script_generation(
        self,
        *,
        task_id: int,
        user_requirement: str | None = None,
    ):
        """继续未完成的批量脚本任务；复用原任务分段与已落库页面。"""

        task = self.get_script_task(task_id)
        if task.mode != ScriptGenerationMode.BATCH:
            raise ValueError("ScriptGenerationTask must be batch mode before continuing.")
        if task.status not in {
            ScriptGenerationTaskStatus.SUSPENDED,
            ScriptGenerationTaskStatus.FAILED,
        }:
            raise ValueError("ScriptGenerationTask must be suspended or failed before continuing.")
        if task.outline_version_id is None:
            raise ValueError("OutlineVersion not found: None")

        outline_version = self.repository.get_outline_version(task.outline_version_id)
        if outline_version is None:
            raise ValueError(f"OutlineVersion not found: {task.outline_version_id}")

        task = self.repository.update_script_task(
            task_id=task.id,
            status=ScriptGenerationTaskStatus.RUNNING,
        )
        running_task_registry.register(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)
        try:
            async for event, payload in self._stream_batch_task(
                task=task,
                outline_version=outline_version,
                user_requirement=user_requirement or task.user_requirement or "",
                is_continue=True,
            ):
                yield event, payload
        finally:
            running_task_registry.unregister(RuntimeTaskType.SCRIPT_GENERATION_TASK, task.id)

    async def _stream_batch_task(
        self,
        *,
        task: ScriptGenerationTask,
        outline_version: OutlineVersion,
        user_requirement: str,
        is_continue: bool,
    ):
        """执行批量脚本任务；新建和继续生成共用这一条 section 编排链路。"""

        total_pages = task.total_pages
        project_id = task.project_id
        yield "task", {"task_id": task.id, "status": task.status.value}
        yield "phase", {
            "code": "script.continue.started" if is_continue else "script.planning.started"
        }

        try:
            persisted_sections = self.repository.list_script_sections(task.id)
            outline_characters = self._outline_characters_context(outline_version.id)
            if not persisted_sections:
                normalized_sections: list[dict] | None = None
                planning_feedback = ""
                planning_agent = ScriptPlanningAgent()
                for attempt in range(1, 4):
                    if self._is_script_task_suspended(task.id):
                        yield "suspended", {
                            "task_id": task.id,
                            "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                        }
                        return
                    if attempt > 1:
                        yield "phase", {
                            "code": "script.planning.retry",
                            "attempt": attempt,
                        }
                    suspended, raw_sections = await self._await_agent_or_suspended(
                        task.id,
                        planning_agent.generate_section_plan(
                            outline=outline_version.content,
                            total_pages=total_pages,
                            outline_characters=outline_characters,
                            user_requirement=user_requirement,
                            feedback=planning_feedback,
                        ),
                    )
                    if suspended:
                        yield "suspended", {
                            "task_id": task.id,
                            "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                        }
                        return
                    try:
                        normalized_sections = self._normalize_section_plan(
                            sections=raw_sections,
                            total_pages=total_pages,
                        )
                        break
                    except ValueError as exc:
                        planning_feedback = str(exc)
                        if attempt >= 3:
                            raise ValueError(f"分段计划连续 3 次校验失败：{planning_feedback}") from exc

                if normalized_sections is None:
                    raise ValueError("分段计划生成失败。")
                if self._is_script_task_suspended(task.id):
                    yield "suspended", {
                        "task_id": task.id,
                        "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                    }
                    return

                persisted_sections = self._persist_section_plan(
                    task_id=task.id,
                    outline_version_id=outline_version.id,
                    normalized_sections=normalized_sections,
                )
            yield "section_plan", {
                "sections": [self._section_to_payload(section) for section in persisted_sections]
            }
            for section in persisted_sections:
                yield "section", self._section_to_payload(section)
            yield "phase", {"code": "script.planning.locked"}

            async for event_name, payload in self._stream_concurrent_sections(
                task=task,
                outline_version=outline_version,
                persisted_sections=persisted_sections,
                outline_characters=outline_characters,
                user_requirement=user_requirement,
            ):
                yield event_name, payload
                if event_name == "suspended":
                    return
            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
            )
            yield "done", {"task_id": task.id, "status": task.status.value}
        except Exception as exc:
            logger.exception(
                "Script batch task failed task_id=%s project_id=%s outline_version_id=%s",
                task.id,
                task.project_id,
                task.outline_version_id,
            )
            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            error = app_error_from_exception(exc)
            yield "error", {
                "task_id": task.id,
                "status": task.status.value,
                "code": error.code,
            }

    def _get_project(self, project_id: int) -> ComicProject:
        """校验项目存在；脚本任务必须挂在已有项目下。"""

        project = self.repository.get_project(project_id)
        if project is None:
            raise ValueError(f"ComicProject not found: {project_id}")
        return project

    def _resolve_outline_version(
        self,
        *,
        project_id: int,
        outline_version_id: int | None,
    ) -> OutlineVersion:
        """按请求指定或项目 active 版本读取大纲。"""

        self._get_project(project_id)
        if outline_version_id is not None:
            outline_version = self.repository.get_outline_version(outline_version_id)
            if outline_version is None:
                raise ValueError(f"OutlineVersion not found: {outline_version_id}")
            if outline_version.session.project_id != project_id:
                raise ValueError("OutlineVersion does not belong to project.")
            if outline_version.confirmed_at is None:
                raise ValueError("OutlineVersion is not confirmed.")
            return outline_version

        outline_version = self.repository.get_active_outline_version_for_project(project_id)
        if outline_version is None:
            raise ValueError(f"Active outline not found for project: {project_id}")
        if outline_version.confirmed_at is None:
            raise ValueError("OutlineVersion is not confirmed.")
        return outline_version

    def _resolve_manual_section(
        self,
        *,
        project_id: int,
        page_no: int,
        task_id: int | None = None,
    ) -> ScriptSection:
        """人工新增脚本时找到可挂载分段；优先挂到前端当前选中的脚本任务。"""

        if task_id is not None:
            task = self.get_script_task(task_id)
            if task.project_id != project_id:
                raise ValueError("ScriptGenerationTask does not belong to project.")
            if page_no > task.total_pages:
                raise ValueError("page_no must be between 1 and task.total_pages")
        else:
            existing_page = self.repository.get_project_page(project_id=project_id, page_no=page_no)
            if existing_page is not None and existing_page.section is not None:
                return existing_page.section
            task = self.repository.get_latest_script_task_for_project(project_id)

        if task is None:
            task = self.repository.create_script_task(
                project_id=project_id,
                outline_version_id=self.repository.get_active_outline_version_for_project(project_id).id
                if self.repository.get_active_outline_version_for_project(project_id) is not None
                else None,
                mode=ScriptGenerationMode.SINGLE,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
                total_pages=max(page_no, 1),
                target_page_no=page_no,
                user_requirement="manual",
            )

        section = self.repository.find_section_for_page(task_id=task.id, page_no=page_no)
        if section is not None:
            return section

        return self.repository.upsert_script_section(
            task_id=task.id,
            section_no=page_no,
            page_start=page_no,
            page_end=page_no,
            title="手动新增",
            description="人工新增页面脚本时自动创建的分段。",
        )

    def _create_single_page_section(self, *, task_id: int, page_no: int) -> ScriptSection:
        """单页生成没有完整节奏计划时，为该页创建一个最小分段。"""

        return self.repository.upsert_script_section(
            task_id=task_id,
            section_no=1,
            page_start=page_no,
            page_end=page_no,
            title="单页生成",
            description=f"第 {page_no} 页单页脚本生成。",
        )

    @staticmethod
    def _validate_total_pages(total_pages: int) -> None:
        """校验总页数，避免无意义的脚本生成请求。"""

        if total_pages <= 0:
            raise ValueError("total_pages must be greater than 0")

    def _validate_page_args(self, *, page_no: int, total_pages: int) -> None:
        """校验单页生成页码范围。"""

        self._validate_total_pages(total_pages)
        if page_no <= 0 or page_no > total_pages:
            raise ValueError("page_no must be between 1 and total_pages")

    def _persist_section_plan(
        self,
        *,
        task_id: int,
        outline_version_id: int,
        normalized_sections: list[dict],
    ) -> list[ScriptSection]:
        """保存已校验通过的分段计划和视觉设定；这是任务内唯一锁定入口。"""

        self.repository.update_script_task(
            task_id=task_id,
            section_plan=self._json_dumps(normalized_sections),
        )
        persisted_sections: list[ScriptSection] = []
        for section in normalized_sections:
            persisted_section = self.repository.upsert_script_section(
                task_id=task_id,
                section_no=section["section_no"],
                page_start=section["page_start"],
                page_end=section["page_end"],
                title=section["title"],
                description=section["description"],
            )
            self._save_section_visual_settings(
                task_id=task_id,
                section_id=persisted_section.id,
                outline_version_id=outline_version_id,
                scenes=section["scenes"],
                characters=section["characters"],
            )
            persisted_sections.append(persisted_section)
        return persisted_sections

    async def _await_agent_or_suspended(
        self,
        task_id: int,
        coro: Awaitable[AgentResultT],
    ) -> tuple[bool, AgentResultT | None]:
        """等待 Agent 调用，同时轮询暂停状态；暂停后取消当前调用并返回信号。"""

        agent_task = asyncio.create_task(coro)
        while True:
            done, _ = await asyncio.wait({agent_task}, timeout=1)
            if done:
                return False, agent_task.result()
            if self._is_script_task_suspended(task_id):
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
                return True, None

    @staticmethod
    def _recent_section_pages_for_writer(
        *,
        pages_by_no: dict[int, dict],
        target_page_no: int,
        include_target: bool,
        limit: int = 5,
    ) -> list[dict]:
        """裁剪 Writer 上下文，只保留当前分段内目标页附近最近页面。"""

        candidate_page_nos = [
            page_no
            for page_no in sorted(pages_by_no)
            if page_no < target_page_no or (include_target and page_no == target_page_no)
        ]
        return [pages_by_no[page_no] for page_no in candidate_page_nos[-limit:]]

    async def _stream_concurrent_sections(
        self,
        *,
        task: ScriptGenerationTask,
        outline_version: OutlineVersion,
        persisted_sections: list[ScriptSection],
        outline_characters: list[dict],
        user_requirement: str,
    ):
        """按 section 并发生成脚本；主 generator 串行落库和输出 SSE。"""

        jobs: list[SectionGenerationJob] = []
        for section in persisted_sections:
            if self._is_script_task_suspended(task.id):
                yield "suspended", {
                    "task_id": task.id,
                    "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                }
                return
            if section.status == ScriptSectionStatus.COMPLETED and self.repository.is_script_section_completed(section.id):
                yield "phase", {
                    "code": "script.section.skipped",
                    "section_no": section.section_no,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                }
                continue
            target_page_nos = self.repository.list_script_section_unpassed_page_nos(section.id)
            if not target_page_nos:
                section = self.repository.update_script_section_status(
                    section_id=section.id,
                    status=ScriptSectionStatus.COMPLETED,
                    error_message=None,
                )
                yield "section", self._section_to_payload(section)
                yield "phase", {
                    "code": "script.section.skipped",
                    "section_no": section.section_no,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                }
                continue
            section = self.repository.reset_script_section_for_generation(section.id)
            yield "section", self._section_to_payload(section)
            existing_pages_by_no = {
                page.page_no: self._page_to_writer_payload(page)
                for page in self.repository.list_script_task_pages(task.id)
                if page.section_id == section.id
                and page.script_review_status == PageScriptReviewStatus.PASSED
                and page.summary
            }
            jobs.append(
                SectionGenerationJob(
                    section=section,
                    visual_context=self._section_visual_context(
                        task_id=task.id,
                        section=section,
                        outline_version_id=outline_version.id,
                    ),
                    previous_context=self._build_previous_sections_context(
                        task_id=task.id,
                        current_section_no=section.section_no,
                    ),
                    target_page_nos=target_page_nos,
                    existing_pages_by_no=existing_pages_by_no,
                )
            )

        if not jobs:
            return

        configured_concurrency = self.repository.get_app_settings().script_section_max_concurrency
        worker_count = min(len(jobs), max(1, min(20, configured_concurrency)))
        yield "phase", {
            "code": "script.sections.concurrent_started",
            "count": len(jobs),
            "section_count": len(jobs),
            "worker_count": worker_count,
        }

        job_queue: asyncio.Queue[SectionGenerationJob | None] = asyncio.Queue()
        event_queue: asyncio.Queue[dict] = asyncio.Queue()
        for job in jobs:
            job_queue.put_nowait(job)
        for _ in range(worker_count):
            job_queue.put_nowait(None)

        workers = [
            asyncio.create_task(
                self._section_generation_worker(
                    worker_no=worker_no,
                    job_queue=job_queue,
                    event_queue=event_queue,
                    task_id=task.id,
                    outline=outline_version.content,
                    total_pages=task.total_pages,
                    outline_characters=outline_characters,
                    user_requirement=user_requirement,
                )
            )
            for worker_no in range(1, worker_count + 1)
        ]
        completed_workers = 0
        saved_pages_by_section: dict[int, dict[int, ComicPage]] = {}

        try:
            while completed_workers < worker_count:
                if self._is_script_task_suspended(task.id):
                    for worker in workers:
                        worker.cancel()
                    yield "suspended", {
                        "task_id": task.id,
                        "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                    }
                    return
                try:
                    message = await asyncio.wait_for(event_queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    continue

                message_type = message.get("type")
                if message_type == "worker_done":
                    completed_workers += 1
                    continue
                if message_type == "worker_error":
                    for worker in workers:
                        worker.cancel()
                    failed_section = message.get("section")
                    if isinstance(failed_section, ScriptSection):
                        error_message = str(message["error"])
                        self.repository.update_script_section_status(
                            section_id=failed_section.id,
                            status=ScriptSectionStatus.FAILED,
                            error_message=error_message,
                        )
                        failed_pages = self.repository.mark_section_pages_review_failed(
                            project_id=task.project_id,
                            section_id=failed_section.id,
                            page_nos=list(message.get("target_page_nos", [])),
                            error_message=error_message,
                        )
                        for page in failed_pages:
                            yield "page", {
                                "action": "updated",
                                "page": self._page_to_payload(page),
                                "page_no": page.page_no,
                                "revision_note": "",
                            }
                        yield "section", self._section_to_payload(
                            self.repository.get_script_section_by_no(
                                task_id=failed_section.task_id,
                                section_no=failed_section.section_no,
                            )
                            or failed_section
                        )
                    raise message["error"]
                if message_type == "suspended":
                    for worker in workers:
                        worker.cancel()
                    yield "suspended", {
                        "task_id": task.id,
                        "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                    }
                    return
                if message_type == "event":
                    yield message["event"], message["payload"]
                    continue
                if message_type == "page_save":
                    section = message["section"]
                    page_payload = message["page_payload"]
                    visual_settings = self._visual_settings_for_section(
                        task_id=task.id,
                        section_id=section.id,
                        outline_version_id=outline_version.id,
                        pages=[page_payload],
                    )
                    saved_page = self._save_section_pages(
                        project_id=task.project_id,
                        section=section,
                        pages=[page_payload],
                        visual_settings=visual_settings,
                        script_review_status=PageScriptReviewStatus.REVIEWING,
                    )[0]
                    saved_pages_by_section.setdefault(section.id, {})[saved_page.page_no] = saved_page
                    yield "page", {
                        "action": "updated" if message.get("is_revision") else "created",
                        "page": self._page_to_payload(saved_page),
                        "page_no": saved_page.page_no,
                        "revision_note": page_payload.get("revision_note", ""),
                    }
                    yield "phase", {
                        "code": "script.page.saved",
                        "section_no": section.section_no,
                        "page_no": saved_page.page_no,
                    }
                    continue
                if message_type == "section_review_passed":
                    section = message["section"]
                    page_nos = list(message.get("page_nos", []))
                    passed_pages = self.repository.update_section_pages_review_status(
                        section_id=section.id,
                        page_nos=page_nos,
                        status=PageScriptReviewStatus.PASSED,
                        error_message=None,
                    )
                    for page in passed_pages:
                        yield "page", {
                            "action": "updated",
                            "page": self._page_to_payload(page),
                            "page_no": page.page_no,
                            "revision_note": "",
                        }
                    completed_section = self.repository.update_script_section_status(
                        section_id=section.id,
                        status=ScriptSectionStatus.COMPLETED,
                        error_message=None,
                    )
                    yield "section", self._section_to_payload(completed_section)
                    section_pages = self.repository.list_script_task_pages(task.id)
                    section_pages = [
                        page for page in section_pages if page.section_id == completed_section.id
                    ]
                    yield "section_pages", {
                        "section": self._section_to_payload(completed_section),
                        "pages": [self._page_to_payload(page) for page in section_pages],
                        "reviews": [],
                    }
                    continue
                if message_type == "section_pages":
                    section = message["section"]
                    saved_pages_by_no = saved_pages_by_section.get(section.id, {})
                    section_saved_pages = [
                        saved_pages_by_no[page_no]
                        for page_no in sorted(saved_pages_by_no)
                    ]
                    yield "section_pages", {
                        "section": self._section_to_payload(section),
                        "pages": [self._page_to_payload(page) for page in section_saved_pages],
                        "reviews": message.get("reviews", []),
                    }
        finally:
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _section_generation_worker(
        self,
        *,
        worker_no: int,
        job_queue: asyncio.Queue[SectionGenerationJob | None],
        event_queue: asyncio.Queue[dict],
        task_id: int,
        outline: str,
        total_pages: int,
        outline_characters: list[dict],
        user_requirement: str,
    ) -> None:
        """并发 worker：顺序处理分段队列，内部不直接写数据库。"""

        writer_agent = PageScriptWriterAgent()
        supervisor_agent = ScriptSupervisorAgent()
        try:
            while True:
                job = await job_queue.get()
                try:
                    if job is None:
                        return
                    await self._run_section_generation_job(
                        worker_no=worker_no,
                        event_queue=event_queue,
                        task_id=task_id,
                        outline=outline,
                        total_pages=total_pages,
                        outline_characters=outline_characters,
                        user_requirement=user_requirement,
                        writer_agent=writer_agent,
                        supervisor_agent=supervisor_agent,
                        job=job,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - worker 失败由主 generator 统一处理
                    failed_page_nos = getattr(exc, "page_nos", None)
                    await event_queue.put(
                        {
                            "type": "worker_error",
                            "section": job.section if job is not None else None,
                            "section_no": job.section.section_no if job is not None else None,
                            "target_page_nos": failed_page_nos
                            if isinstance(failed_page_nos, list)
                            else (job.target_page_nos if job is not None else []),
                            "error": exc,
                        }
                    )
                    return
                finally:
                    job_queue.task_done()
        finally:
            await event_queue.put({"type": "worker_done", "worker_no": worker_no})

    async def _run_section_generation_job(
        self,
        *,
        worker_no: int,
        event_queue: asyncio.Queue[dict],
        task_id: int,
        outline: str,
        total_pages: int,
        outline_characters: list[dict],
        user_requirement: str,
        writer_agent: PageScriptWriterAgent,
        supervisor_agent: ScriptSupervisorAgent,
        job: SectionGenerationJob,
    ) -> None:
        """生成单个分段：逐页初稿、整段审查、问题页局部修订。"""

        section = job.section
        await self._put_sse_event(
            event_queue,
            "phase",
            {
                "code": "script.section.worker_started",
                "worker_no": worker_no,
                "section_no": section.section_no,
            },
        )
        await self._put_sse_event(
            event_queue,
            "phase",
            {
                "code": "script.section.generating",
                "section_no": section.section_no,
                "page_start": section.page_start,
                "page_end": section.page_end,
            },
        )
        section_pages_by_no: dict[int, dict] = dict(job.existing_pages_by_no)
        for page_no in job.target_page_nos:
            current_pages = self._recent_section_pages_for_writer(
                pages_by_no=section_pages_by_no,
                target_page_no=page_no,
                include_target=False,
            )
            suspended, page_payload, page_events = await self._generate_page_payload(
                writer_agent=writer_agent,
                task_id=task_id,
                outline=outline,
                total_pages=total_pages,
                section=section,
                page_no=page_no,
                visual_context=job.visual_context,
                outline_characters=outline_characters,
                previous_context=job.previous_context,
                user_requirement=user_requirement,
                current_pages=current_pages,
                is_revision=False,
                feedback="",
            )
            for event_name, payload in page_events:
                await self._put_sse_event(event_queue, event_name, payload)
            if suspended:
                await event_queue.put({"type": "suspended"})
                return
            if page_payload is None:
                raise SectionGenerationError(
                    f"第 {page_no} 页脚本生成失败。",
                    page_nos=[page_no],
                )
            section_pages_by_no[page_no] = page_payload
            await event_queue.put(
                {
                    "type": "page_save",
                    "section": section,
                    "page_payload": page_payload,
                    "is_revision": False,
                }
            )

        section_pages = [section_pages_by_no[page_no] for page_no in sorted(job.target_page_nos)]
        await self._put_sse_event(
            event_queue,
            "phase",
            {"code": "script.section.saved", "section_no": section.section_no},
        )
        await event_queue.put({"type": "section_pages", "section": section, "reviews": []})

        review_round = 1
        while True:
            await self._put_sse_event(
                event_queue,
                "phase",
                {
                    "code": "script.section.review_started",
                    "section_no": section.section_no,
                    "attempt": review_round,
                },
            )
            suspended, review_result = await self._await_agent_or_suspended(
                task_id,
                supervisor_agent.review_section_pages(
                    outline=outline,
                    current_section=self._section_to_payload(section),
                    section_scenes=job.visual_context["scenes"],
                    section_characters=job.visual_context["characters"],
                    outline_characters=outline_characters,
                    pages=section_pages,
                ),
            )
            if suspended:
                await event_queue.put({"type": "suspended"})
                return
            reviews = [
                review if isinstance(review, dict) else {"summary": str(review)}
                for review in review_result.get("reviews", [])
            ]
            for review in reviews:
                await self._put_sse_event(
                    event_queue,
                    "review",
                    {"section_no": section.section_no, **review},
                )
            if self._section_review_passed(review_result):
                await event_queue.put(
                    {
                        "type": "section_review_passed",
                        "section": section,
                        "page_nos": sorted(section_pages_by_no),
                    }
                )
                await self._put_sse_event(
                    event_queue,
                    "phase",
                    {
                        "code": "script.section.review_passed",
                        "section_no": section.section_no,
                    },
                )
                await self._put_sse_event(
                    event_queue,
                    "phase",
                    {
                        "code": "script.section.worker_completed",
                        "worker_no": worker_no,
                        "section_no": section.section_no,
                    },
                )
                return

            revision_page_nos = self._revision_page_nos_from_reviews(reviews)
            if not revision_page_nos:
                raise SectionGenerationError(
                    f"第 {section.section_no} 段监督未通过，但没有可修订页码。",
                    page_nos=job.target_page_nos,
                )
            if review_round >= 3:
                feedback = self._review_feedback(reviews)
                raise SectionGenerationError(
                    f"第 {section.section_no} 段脚本连续 3 次监督未通过：{feedback}",
                    page_nos=revision_page_nos,
                )

            await self._put_sse_event(
                event_queue,
                "phase",
                {
                    "code": "script.section.review_revision_started",
                    "section_no": section.section_no,
                    "revision_page_nos": revision_page_nos,
                },
            )
            feedback_by_page_no = self._review_feedback_by_page_no(reviews)
            for page_no in revision_page_nos:
                current_pages = self._recent_section_pages_for_writer(
                    pages_by_no=section_pages_by_no,
                    target_page_no=page_no,
                    include_target=True,
                )
                suspended, page_payload, page_events = await self._generate_page_payload(
                    writer_agent=writer_agent,
                    task_id=task_id,
                    outline=outline,
                    total_pages=total_pages,
                    section=section,
                    page_no=page_no,
                    visual_context=job.visual_context,
                    outline_characters=outline_characters,
                    previous_context={"completed_section_summaries": [], "recent_full_sections": []},
                    user_requirement=user_requirement,
                    current_pages=current_pages,
                    is_revision=True,
                    feedback=feedback_by_page_no.get(page_no, self._review_feedback(reviews)),
                )
                for event_name, payload in page_events:
                    await self._put_sse_event(event_queue, event_name, payload)
                if suspended:
                    await event_queue.put({"type": "suspended"})
                    return
                if page_payload is None:
                    raise SectionGenerationError(
                        f"第 {page_no} 页修订失败。",
                        page_nos=[page_no],
                    )
                section_pages_by_no[page_no] = page_payload
                await event_queue.put(
                    {
                        "type": "page_save",
                        "section": section,
                        "page_payload": page_payload,
                        "is_revision": True,
                    }
                )
            section_pages = [
                section_pages_by_no[page_no]
                for page_no in sorted(job.target_page_nos)
            ]
            review_round += 1

    @staticmethod
    async def _put_sse_event(
        event_queue: asyncio.Queue[dict],
        event_name: str,
        payload: dict,
    ) -> None:
        """把普通 SSE 事件包装进 worker 队列。"""

        await event_queue.put({"type": "event", "event": event_name, "payload": payload})

    async def _generate_page_payload(
        self,
        *,
        writer_agent: PageScriptWriterAgent,
        task_id: int,
        outline: str,
        total_pages: int,
        section: ScriptSection,
        page_no: int,
        visual_context: dict,
        outline_characters: list[dict],
        previous_context: dict,
        user_requirement: str,
        current_pages: list[dict],
        is_revision: bool,
        feedback: str,
    ) -> tuple[bool, dict | None, list[tuple[str, dict]]]:
        """只生成并校验单页 payload，不落库；并发 worker 使用。"""

        events: list[tuple[str, dict]] = []
        page_feedback = feedback
        for attempt in range(1, 4):
            if self._is_script_task_suspended(task_id):
                return True, None, events
            events.append(
                (
                    "phase",
                    {
                        "code": "script.page.generating",
                        "section_no": section.section_no,
                        "page_no": page_no,
                        "attempt": attempt,
                    },
                )
            )
            suspended, raw_pages = await self._await_agent_or_suspended(
                task_id,
                writer_agent.generate_page(
                    outline=outline,
                    total_pages=total_pages,
                    current_section=self._section_to_payload(section),
                    target_page_no=page_no,
                    section_scenes=visual_context["scenes"],
                    section_characters=visual_context["characters"],
                    previous_context=previous_context,
                    outline_characters=outline_characters,
                    user_requirement=user_requirement,
                    feedback=page_feedback,
                    is_revision=is_revision,
                    current_pages=current_pages,
                ),
            )
            if suspended:
                return True, None, events
            try:
                normalized_page = self._normalize_single_page(
                    pages=raw_pages,
                    section=section,
                    page_no=page_no,
                )[0]
                self._validate_page_visual_references(
                    pages=[normalized_page],
                    visual_context=visual_context,
                )
                return False, normalized_page, events
            except ValueError as exc:
                page_feedback = str(exc)
                events.append(
                    (
                        "phase",
                        {
                            "code": "script.page.validation_failed",
                            "section_no": section.section_no,
                            "page_no": page_no,
                            "attempt": attempt,
                        },
                    )
                )
                if attempt >= 3:
                    raise ValueError(f"第 {page_no} 页脚本连续 3 次校验失败：{page_feedback}") from exc
        return False, None, events

    @staticmethod
    def _validate_page_visual_references(*, pages: list[dict], visual_context: dict) -> None:
        """用 worker 内存中的视觉设定先做引用校验，避免无效页面进入落库队列。"""

        scene_keys = {
            str(scene.get("scene_key", "")).strip()
            for scene in visual_context.get("scenes", [])
            if isinstance(scene, dict)
        }
        character_keys = {
            str(character.get("character_key", "")).strip()
            for character in visual_context.get("characters", [])
            if isinstance(character, dict)
        }
        for page in pages:
            page_no = page.get("page_no")
            scene_key = str(page.get("scene_key", "")).strip()
            if scene_key not in scene_keys:
                raise ValueError(f"page {page_no} scene_key not found: {scene_key}")
            page_character_keys = page.get("character_keys", [])
            page_characters_text = str(page.get("characters", "")).strip()
            if page_characters_text and page_characters_text != "无" and not page_character_keys:
                raise ValueError(f"page {page_no} has characters text but no character_keys")
            for character_key in page_character_keys:
                if character_key not in character_keys:
                    raise ValueError(f"page {page_no} character_key not found: {character_key}")

    async def _generate_and_save_page(
        self,
        *,
        writer_agent: PageScriptWriterAgent,
        task_id: int,
        project_id: int,
        outline: str,
        total_pages: int,
        section: ScriptSection,
        page_no: int,
        visual_context: dict,
        outline_characters: list[dict],
        previous_context: dict,
        user_requirement: str,
        current_pages: list[dict],
        is_revision: bool,
        feedback: str,
    ) -> tuple[bool, dict | None, ComicPage | None, list[tuple[str, dict]]]:
        """生成并保存单页脚本；失败只重试当前页，不影响其它页。"""

        events: list[tuple[str, dict]] = []
        page_feedback = feedback
        for attempt in range(1, 4):
            if self._is_script_task_suspended(task_id):
                return True, None, None, events
            events.append(
                (
                    "phase",
                    {
                        "code": "script.page.generating",
                        "section_no": section.section_no,
                        "page_no": page_no,
                        "attempt": attempt,
                    },
                )
            )
            suspended, raw_pages = await self._await_agent_or_suspended(
                task_id,
                writer_agent.generate_page(
                    outline=outline,
                    total_pages=total_pages,
                    current_section=self._section_to_payload(section),
                    target_page_no=page_no,
                    section_scenes=visual_context["scenes"],
                    section_characters=visual_context["characters"],
                    previous_context=previous_context,
                    outline_characters=outline_characters,
                    user_requirement=user_requirement,
                    feedback=page_feedback,
                    is_revision=is_revision,
                    current_pages=current_pages,
                ),
            )
            if suspended:
                return True, None, None, events
            try:
                normalized_page = self._normalize_single_page(
                    pages=raw_pages,
                    section=section,
                    page_no=page_no,
                )[0]
                visual_settings = self._visual_settings_for_section(
                    task_id=task_id,
                    section_id=section.id,
                    outline_version_id=0,
                    pages=[normalized_page],
                )
                saved_page = self._save_section_pages(
                    project_id=project_id,
                    section=section,
                    pages=[normalized_page],
                    visual_settings=visual_settings,
                )[0]
                events.append(
                    (
                        "page",
                        {
                            "action": "updated" if is_revision else "created",
                            "page": self._page_to_payload(saved_page),
                            "page_no": saved_page.page_no,
                            "revision_note": normalized_page.get("revision_note", ""),
                        },
                    )
                )
                events.append(
                    (
                        "phase",
                        {
                            "code": "script.page.saved",
                            "section_no": section.section_no,
                            "page_no": page_no,
                        },
                    )
                )
                return False, normalized_page, saved_page, events
            except ValueError as exc:
                page_feedback = str(exc)
                events.append(
                    (
                        "phase",
                        {
                            "code": "script.page.validation_failed",
                            "section_no": section.section_no,
                            "page_no": page_no,
                            "attempt": attempt,
                        },
                    )
                )
                if attempt >= 3:
                    raise ValueError(f"第 {page_no} 页脚本连续 3 次校验失败：{page_feedback}") from exc
        return False, None, None, events

    def _start_section_review(
        self,
        *,
        supervisor_agent: ScriptSupervisorAgent,
        outline: str,
        section: ScriptSection,
        visual_context: dict,
        outline_characters: list[dict],
        pages: list[dict],
        review_round: int,
    ) -> PendingSectionReview:
        """启动当前分段异步审查；审查输入不包含其它分段上下文。"""

        review_task = asyncio.create_task(
            supervisor_agent.review_section_pages(
                outline=outline,
                current_section=self._section_to_payload(section),
                section_scenes=visual_context["scenes"],
                section_characters=visual_context["characters"],
                outline_characters=outline_characters,
                pages=pages,
            )
        )
        return PendingSectionReview(
            section=section,
            pages=pages,
            visual_context=visual_context,
            review_round=review_round,
            task=review_task,
        )

    async def _drain_completed_section_reviews(
        self,
        *,
        pending_reviews: list[PendingSectionReview],
        supervisor_agent: ScriptSupervisorAgent,
        writer_agent: PageScriptWriterAgent,
        task_id: int,
        project_id: int,
        outline: str,
        total_pages: int,
        outline_characters: list[dict],
        user_requirement: str,
        wait: bool,
    ) -> tuple[bool, list[tuple[str, dict]]]:
        """处理已经完成的异步监督审查，并对问题页做局部修订。"""

        events: list[tuple[str, dict]] = []
        if not pending_reviews:
            return False, events
        if self._is_script_task_suspended(task_id):
            self._cancel_pending_reviews(pending_reviews)
            return True, events
        if wait and not any(pending.task.done() for pending in pending_reviews):
            await asyncio.wait(
                {pending.task for pending in pending_reviews},
                timeout=1,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._is_script_task_suspended(task_id):
                self._cancel_pending_reviews(pending_reviews)
                return True, events

        completed = [pending for pending in pending_reviews if pending.task.done()]
        for pending in completed:
            pending_reviews.remove(pending)
            review_result = pending.task.result()
            reviews = [
                review if isinstance(review, dict) else {"summary": str(review)}
                for review in review_result.get("reviews", [])
            ]
            for review in reviews:
                events.append(("review", {"section_no": pending.section.section_no, **review}))
            if self._section_review_passed(review_result):
                events.append(
                    (
                        "phase",
                        {
                            "code": "script.section.review_passed",
                            "section_no": pending.section.section_no,
                        },
                    )
                )
                continue

            revision_page_nos = self._revision_page_nos_from_reviews(reviews)
            if not revision_page_nos:
                raise ValueError(f"第 {pending.section.section_no} 段监督未通过，但没有可修订页码。")
            if pending.review_round >= 3:
                feedback = self._review_feedback(reviews)
                raise ValueError(
                    f"第 {pending.section.section_no} 段脚本连续 3 次监督未通过：{feedback}"
                )
            events.append(
                (
                    "phase",
                    {
                        "code": "script.section.review_revision_started",
                        "section_no": pending.section.section_no,
                        "revision_page_nos": revision_page_nos,
                    },
                )
            )
            pages_by_no = {int(page["page_no"]): page for page in pending.pages}
            feedback_by_page_no = self._review_feedback_by_page_no(reviews)
            for page_no in revision_page_nos:
                current_pages = self._recent_section_pages_for_writer(
                    pages_by_no=pages_by_no,
                    target_page_no=page_no,
                    include_target=True,
                )
                suspended, page_payload, _saved_page, page_events = await self._generate_and_save_page(
                    writer_agent=writer_agent,
                    task_id=task_id,
                    project_id=project_id,
                    outline=outline,
                    total_pages=total_pages,
                    section=pending.section,
                    page_no=page_no,
                    visual_context=pending.visual_context,
                    outline_characters=outline_characters,
                    previous_context={"completed_section_summaries": [], "recent_full_sections": []},
                    user_requirement=user_requirement,
                    current_pages=current_pages,
                    is_revision=True,
                    feedback=feedback_by_page_no.get(page_no, self._review_feedback(reviews)),
                )
                events.extend(page_events)
                if suspended:
                    return True, events
                if page_payload is None:
                    raise ValueError(f"第 {page_no} 页修订失败。")
                pages_by_no[page_no] = page_payload
            revised_pages = [pages_by_no[key] for key in sorted(pages_by_no)]
            pending_reviews.append(
                self._start_section_review(
                    supervisor_agent=supervisor_agent,
                    outline=outline,
                    section=pending.section,
                    visual_context=pending.visual_context,
                    outline_characters=outline_characters,
                    pages=revised_pages,
                    review_round=pending.review_round + 1,
                )
            )
            events.append(
                (
                    "phase",
                    {
                        "code": "script.section.review_started",
                        "section_no": pending.section.section_no,
                        "attempt": pending.review_round + 1,
                    },
                )
            )
        return False, events

    @staticmethod
    def _cancel_pending_reviews(pending_reviews: list[PendingSectionReview]) -> None:
        """暂停任务时取消仍在运行的监督审查调用。"""

        for pending in pending_reviews:
            if not pending.task.done():
                pending.task.cancel()
        pending_reviews.clear()

    def _is_script_task_suspended(self, task_id: int) -> bool:
        """从数据库判断任务是否已被前端暂停，避免长任务继续落库。"""

        return self.repository.get_script_task_status(task_id) == ScriptGenerationTaskStatus.SUSPENDED

    @staticmethod
    def _find_page_payload(pages: list, page_no: int) -> dict:
        """从 Agent 输出中找到指定页；单页输出缺页时给出明确错误。"""

        for page in pages:
            if int(page.get("page_no", 0)) == page_no:
                return page
        if len(pages) == 1:
            return pages[0]
        raise ValueError(f"Generated script missing page_no: {page_no}")

    @staticmethod
    def _normalize_manual_page_payload(
        *,
        summary: str,
        characters: str,
        clothing: str,
        scene: str,
        composition: str,
        character_action: str,
        dialogue: str,
    ) -> dict:
        """校验人工编辑的结构化脚本，确保保存的数据可直接用于后续图片 Prompt。"""

        payload = {
            "summary": summary.strip(),
            "characters": characters.strip(),
            "clothing": clothing.strip(),
            "scene": scene.strip(),
            "composition": composition.strip(),
            "character_action": character_action.strip(),
            "dialogue": dialogue.strip() or "无",
        }
        for field_name in (
            "summary",
            "characters",
            "clothing",
            "scene",
            "composition",
            "character_action",
        ):
            if not payload[field_name]:
                raise ValueError(f"Page field cannot be empty: {field_name}")
        return payload

    @staticmethod
    def _page_payload_for_save(page_payload: dict) -> dict:
        """从 Agent 输出中取出真正落库的页面结构化字段。"""

        return {
            "summary": str(page_payload.get("summary", "")).strip(),
            "characters": str(page_payload.get("characters", "")).strip(),
            "clothing": str(page_payload.get("clothing", "")).strip(),
            "scene": str(page_payload.get("scene", "")).strip(),
            "composition": str(page_payload.get("composition", "")).strip(),
            "character_action": str(page_payload.get("character_action", "")).strip(),
            "dialogue": str(page_payload.get("dialogue", "")).strip() or "无",
        }

    @staticmethod
    def _page_to_writer_payload(page: ComicPage) -> dict:
        """把已落库页面转成 Writer 上下文需要的结构化页面字段。"""

        return {
            "section_no": page.section.section_no if page.section is not None else None,
            "page_no": page.page_no,
            "scene_key": page.script_scene.scene_key if page.script_scene is not None else "",
            "character_keys": [
                character.character_key
                for character in sorted(page.visual_characters, key=lambda item: item.character_key)
            ],
            "summary": page.summary or "",
            "characters": page.characters or "",
            "clothing": page.clothing or "",
            "scene": page.scene or "",
            "composition": page.composition or "",
            "character_action": page.character_action or "",
            "dialogue": page.dialogue or "无",
            "is_revision": False,
            "revision_note": "",
        }

    @staticmethod
    def _normalize_scene_payload(raw_scene: dict) -> dict:
        """规范化中心化场景设定，确保后续 Prompt 可以稳定复用。"""

        payload = {
            "scene_key": str(raw_scene.get("scene_key", "")).strip(),
            "name": str(raw_scene.get("name", "")).strip(),
            "location_type": str(raw_scene.get("location_type", "")).strip(),
            "time_of_day": str(raw_scene.get("time_of_day", "")).strip(),
            "lighting": str(raw_scene.get("lighting", "")).strip(),
            "weather": str(raw_scene.get("weather", "")).strip(),
            "environment_details": str(raw_scene.get("environment_details", "")).strip(),
            "color_palette": str(raw_scene.get("color_palette", "")).strip(),
            "visual_anchors": str(raw_scene.get("visual_anchors", "")).strip(),
            "negative_constraints": str(raw_scene.get("negative_constraints", "")).strip(),
        }
        for field_name in ("scene_key", "name", "environment_details", "visual_anchors"):
            if not payload[field_name]:
                raise ValueError(f"scene setting missing required field: {field_name}")
        return payload

    @staticmethod
    def _normalize_character_payload(raw_character: dict) -> dict:
        """规范化分段角色细化设定，允许发型服装在当前分段内覆盖默认值。"""

        payload = {
            "character_key": str(raw_character.get("character_key", "")).strip(),
            "name": str(raw_character.get("name", "")).strip(),
            "section_role": str(raw_character.get("section_role", "")).strip(),
            "current_hairstyle": str(raw_character.get("current_hairstyle", "")).strip(),
            "current_clothing": str(raw_character.get("current_clothing", "")).strip(),
            "current_accessories": str(raw_character.get("current_accessories", "")).strip(),
            "current_state": str(raw_character.get("current_state", "")).strip(),
            "emotion": str(raw_character.get("emotion", "")).strip(),
            "temporary_changes": str(raw_character.get("temporary_changes", "")).strip() or "无",
            "visual_anchors": str(raw_character.get("visual_anchors", "")).strip(),
            "negative_constraints": str(raw_character.get("negative_constraints", "")).strip(),
        }
        for field_name in ("character_key", "name", "section_role", "visual_anchors"):
            if not payload[field_name]:
                raise ValueError(f"character setting missing required field: {field_name}")
        return payload

    def _save_section_visual_settings(
        self,
        *,
        task_id: int,
        section_id: int,
        outline_version_id: int,
        scenes: list,
        characters: list,
    ) -> None:
        """保存规划阶段锁定的场景圣经和当前分段角色设定。"""

        scene_payloads = [
            self._normalize_scene_payload(scene)
            for scene in scenes
            if isinstance(scene, dict)
        ]
        character_payloads = [
            self._normalize_character_payload(character)
            for character in characters
            if isinstance(character, dict)
        ]
        if not scene_payloads:
            raise ValueError("section visual settings must include at least one scene")
        if not character_payloads:
            raise ValueError("section visual settings must include at least one character")
        outline_characters_by_key = {
            character.character_key: character
            for character in self.repository.list_outline_characters(outline_version_id)
        }
        for scene in scene_payloads:
            self.repository.upsert_script_scene(task_id=task_id, **scene)
        for character in character_payloads:
            self.repository.upsert_script_section_character(
                section_id=section_id,
                outline_character_id=(
                    outline_characters_by_key[character["character_key"]].id
                    if character["character_key"] in outline_characters_by_key
                    else None
                ),
                task_id=task_id,
                **character,
            )

    def _visual_settings_for_section(
        self,
        *,
        task_id: int,
        section_id: int,
        outline_version_id: int,
        pages: list[dict],
    ) -> dict:
        """读取已锁定视觉设定并校验页面引用，防止 Writer 新增或改写设定。"""

        del outline_version_id
        scene_ids_by_key = {
            scene.scene_key: scene.id
            for scene in self.repository.list_script_scenes(task_id)
        }
        character_ids_by_key = {
            character.character_key: character.id
            for character in self.repository.list_script_section_characters(section_id)
        }
        for page in pages:
            scene_key = str(page.get("scene_key", "")).strip()
            if not scene_key:
                raise ValueError(f"page {page.get('page_no')} missing required field: scene_key")
            if scene_key not in scene_ids_by_key:
                raise ValueError(f"page {page.get('page_no')} scene_key not found: {scene_key}")
            page_character_keys = page.get("character_keys", [])
            page_characters_text = str(page.get("characters", "")).strip()
            if page_characters_text and page_characters_text != "无" and not page_character_keys:
                raise ValueError(
                    f"page {page.get('page_no')} has characters text but no character_keys"
                )
            for character_key in page_character_keys:
                if character_key not in character_ids_by_key:
                    raise ValueError(
                        f"page {page.get('page_no')} character_key not found: {character_key}"
                    )

        return {
            "scene_ids_by_key": scene_ids_by_key,
            "character_ids_by_key": character_ids_by_key,
        }

    def _section_visual_context(
        self,
        *,
        task_id: int,
        section: ScriptSection,
        outline_version_id: int,
    ) -> dict:
        """读取当前分段已锁定的场景和角色设定，作为 Writer/Supervisor 的唯一视觉来源。"""

        del outline_version_id
        task = self.get_script_task(task_id)
        planned_section = self._planned_section_payload(
            section_plan=task.section_plan,
            section_no=section.section_no,
        )
        planned_scene_keys = {
            str(scene.get("scene_key", "")).strip()
            for scene in planned_section.get("scenes", [])
            if isinstance(scene, dict)
        }
        all_scenes = [self._scene_to_payload(scene) for scene in self.repository.list_script_scenes(task_id)]
        section_scenes = (
            [scene for scene in all_scenes if scene["scene_key"] in planned_scene_keys]
            if planned_scene_keys
            else all_scenes
        )
        section_characters = [
            self._character_to_payload(character)
            for character in self.repository.list_script_section_characters(section.id)
        ]
        if not section_scenes:
            raise ValueError(f"section {section.section_no} has no locked scenes")
        if not section_characters:
            raise ValueError(f"section {section.section_no} has no locked characters")
        return {
            "scenes": section_scenes,
            "characters": section_characters,
        }

    @staticmethod
    def _planned_section_payload(*, section_plan: str | None, section_no: int) -> dict:
        """从任务保存的 section_plan JSON 中取回某个分段的原始规划内容。"""

        if not section_plan:
            return {}
        try:
            sections = json.loads(section_plan)
        except json.JSONDecodeError:
            return {}
        if not isinstance(sections, list):
            return {}
        for section in sections:
            if isinstance(section, dict) and int(section.get("section_no", 0)) == section_no:
                return section
        return {}

    @staticmethod
    def _section_review_passed(review_result: dict) -> bool:
        """判断监督结果是否整体通过；只要任一页不通过就进入修订重试。"""

        reviews = review_result.get("reviews", [])
        valid_reviews = [review for review in reviews if isinstance(review, dict)]
        return bool(valid_reviews) and all(bool(review.get("passed")) for review in valid_reviews)

    @staticmethod
    def _review_feedback(reviews: list[dict]) -> str:
        """把监督意见压成给 Writer 的修订反馈，保持按页定位。"""

        feedback_lines: list[str] = []
        for review in reviews:
            if review.get("passed"):
                continue
            suggestions = review.get("revision_suggestions", [])
            if not isinstance(suggestions, list):
                suggestions = [str(suggestions)]
            feedback_lines.append(
                "第 {page_no} 页：{summary}；修改意见：{suggestions}".format(
                    page_no=review.get("page_no", "-"),
                    summary=review.get("summary", ""),
                    suggestions="；".join(str(item) for item in suggestions if str(item).strip()),
                )
            )
        return "\n".join(feedback_lines) or "监督未通过，请按逐页意见修订。"

    @staticmethod
    def _review_feedback_by_page_no(reviews: list[dict]) -> dict[int, str]:
        """把监督意见按页码拆分，供单页修订时精确传入。"""

        feedback_by_page_no: dict[int, str] = {}
        scene_revision_rule = (
            "硬性结构限制：每页只能绑定一个 scene_key；修订时必须让 scene、composition、"
            "character_action 完全服务于同一个主场景，删除其它场景的核心家具、主光源、"
            "空间结构或主体道具。"
        )
        for review in reviews:
            if not isinstance(review, dict) or review.get("passed"):
                continue
            try:
                page_no = int(review.get("page_no", 0))
            except (TypeError, ValueError):
                continue
            if page_no <= 0:
                continue
            suggestions = review.get("revision_suggestions", [])
            if not isinstance(suggestions, list):
                suggestions = [str(suggestions)]
            feedback_by_page_no[page_no] = "{rule}\n第 {page_no} 页：{summary}；修改意见：{suggestions}".format(
                rule=scene_revision_rule,
                page_no=page_no,
                summary=review.get("summary", ""),
                suggestions="；".join(str(item) for item in suggestions if str(item).strip()),
            )
        return feedback_by_page_no

    @staticmethod
    def _revision_page_nos_from_reviews(reviews: list[dict]) -> list[int]:
        """从监督结果中提取需要局部修订的页码。"""

        page_nos: set[int] = set()
        for review in reviews:
            if not isinstance(review, dict) or review.get("passed"):
                continue
            try:
                page_no = int(review.get("page_no", 0))
            except (TypeError, ValueError):
                continue
            if page_no > 0:
                page_nos.add(page_no)
        return sorted(page_nos)

    @staticmethod
    def _default_single_page_scene() -> dict:
        """单页生成兼容入口使用的最小默认场景；前端主流程已不使用单页生成。"""

        return {
            "scene_key": "single_page_scene",
            "name": "单页场景",
            "location_type": "按当前页面脚本决定",
            "time_of_day": "按当前页面脚本决定",
            "lighting": "按当前页面脚本决定",
            "weather": "按当前页面脚本决定",
            "environment_details": "根据大纲和本页内容生成统一场景。",
            "color_palette": "按当前页面情绪决定。",
            "visual_anchors": "保持大纲中的主要地点和氛围一致。",
            "negative_constraints": "不要生成与大纲冲突的地点和时代元素。",
        }

    @staticmethod
    def _default_single_page_characters(outline_characters: list[dict]) -> list[dict]:
        """单页生成兼容入口把大纲角色基准转成当前分段角色设定默认值。"""

        if not outline_characters:
            return [
                {
                    "character_key": "unknown_character",
                    "name": "未指定角色",
                    "section_role": "按当前页面脚本决定",
                    "current_hairstyle": "按当前页面脚本决定",
                    "current_clothing": "按当前页面脚本决定",
                    "current_accessories": "无",
                    "current_state": "按当前页面脚本决定",
                    "emotion": "按当前页面脚本决定",
                    "temporary_changes": "无",
                    "visual_anchors": "保持角色在大纲中的识别特征。",
                    "negative_constraints": "不要生成与大纲冲突的角色设定。",
                }
            ]
        return [
            {
                "character_key": str(character.get("character_key", "")).strip(),
                "name": str(character.get("name", "")).strip(),
                "section_role": str(character.get("role", "")).strip() or "单页出场角色",
                "current_hairstyle": str(character.get("default_hairstyle", "")).strip() or "沿用大纲默认发型",
                "current_clothing": str(character.get("default_clothing", "")).strip() or "沿用大纲默认服装",
                "current_accessories": str(character.get("default_accessories", "")).strip() or "沿用大纲默认配件",
                "current_state": "按当前页面脚本决定",
                "emotion": "按当前页面脚本决定",
                "temporary_changes": "无",
                "visual_anchors": str(character.get("visual_anchors", "")).strip() or "沿用大纲角色视觉锚点",
                "negative_constraints": str(character.get("negative_constraints", "")).strip() or "不得违背大纲角色基准",
            }
            for character in outline_characters
            if str(character.get("character_key", "")).strip()
        ]

    @staticmethod
    def _normalize_section_plan(*, sections: list, total_pages: int) -> list[dict]:
        """校验并规范化分段计划，作为页面提交页码范围的权威依据。"""

        normalized_sections: list[dict] = []
        seen_section_nos: set[int] = set()
        for raw_section in sections:
            if not isinstance(raw_section, dict):
                raise ValueError("section plan item must be an object")
            section_no = int(raw_section["section_no"])
            page_start = int(raw_section["page_start"])
            page_end = int(raw_section["page_end"])
            if section_no in seen_section_nos:
                raise ValueError(f"duplicate section_no: {section_no}")
            if page_start < 1 or page_end > total_pages or page_start > page_end:
                raise ValueError(
                    f"invalid page range for section {section_no}: {page_start}-{page_end}"
                )
            seen_section_nos.add(section_no)
            normalized_sections.append(
                {
                    "section_no": section_no,
                    "page_start": page_start,
                    "page_end": page_end,
                    "title": str(raw_section.get("title", "")),
                    "description": str(raw_section.get("description", "")),
                    "scenes": [
                        ScriptService._normalize_scene_payload(scene)
                        for scene in raw_section.get("scenes", [])
                        if isinstance(scene, dict)
                    ],
                    "characters": [
                        ScriptService._normalize_character_payload(character)
                        for character in raw_section.get("characters", [])
                        if isinstance(character, dict)
                    ],
                }
            )

        if not normalized_sections:
            raise ValueError("section plan cannot be empty")
        normalized_sections.sort(key=lambda section: section["page_start"])

        expected_start = 1
        for index, section in enumerate(normalized_sections, start=1):
            if section["section_no"] != index:
                raise ValueError(
                    f"section_no must start at 1 and increase by 1; expected {index}, "
                    f"got {section['section_no']}"
                )
            if section["page_start"] != expected_start:
                raise ValueError(
                    f"section plan must be continuous; expected page_start={expected_start}, "
                    f"got {section['page_start']} for section {section['section_no']}"
                )
            if not section["scenes"]:
                raise ValueError(f"section {section['section_no']} must define at least one scene")
            if not section["characters"]:
                raise ValueError(f"section {section['section_no']} must define at least one character")
            expected_start = section["page_end"] + 1
        if expected_start != total_pages + 1:
            raise ValueError(
                f"section plan must cover pages 1-{total_pages}; "
                f"last covered page is {expected_start - 1}"
            )
        return normalized_sections

    def _normalize_section_pages(self, *, pages: list, section: ScriptSection) -> list[dict]:
        """校验当前分段脚本输出，确保 Agent 只能交付当前 section 的完整页码范围。"""

        expected_page_nos = set(range(section.page_start, section.page_end + 1))
        return self._normalize_pages_for_expected_page_nos(
            pages=pages,
            section=section,
            expected_page_nos=expected_page_nos,
            error_label=(
                f"section {section.section_no} pages must cover "
                f"{section.page_start}-{section.page_end}"
            ),
        )

    def _normalize_single_page(
        self,
        *,
        pages: list,
        section: ScriptSection,
        page_no: int,
    ) -> list[dict]:
        """校验单页 Writer 输出，只允许返回当前目标页。"""

        return self._normalize_pages_for_expected_page_nos(
            pages=pages,
            section=section,
            expected_page_nos={page_no},
            error_label=(
                f"section {section.section_no} page generation must return exactly page {page_no}"
            ),
        )

    def _normalize_revision_pages(
        self,
        *,
        pages: list,
        section: ScriptSection,
        expected_page_nos: list[int],
    ) -> list[dict]:
        """校验监督修订输出，只允许返回被监督点名的页面。"""

        expected_page_no_set = set(expected_page_nos)
        return self._normalize_pages_for_expected_page_nos(
            pages=pages,
            section=section,
            expected_page_nos=expected_page_no_set,
            error_label=(
                f"section {section.section_no} revision pages must be exactly "
                f"{sorted(expected_page_no_set)}"
            ),
        )

    def _normalize_pages_for_expected_page_nos(
        self,
        *,
        pages: list,
        section: ScriptSection,
        expected_page_nos: set[int],
        error_label: str,
    ) -> list[dict]:
        """统一校验页面脚本字段和页码集合；全量/局部修订共用这一套规则。"""

        if not isinstance(pages, list) or not pages:
            raise ValueError("section pages cannot be empty")
        if not expected_page_nos:
            raise ValueError("expected page numbers cannot be empty")

        required_text_fields = [
            "scene_key",
            "summary",
            "characters",
            "clothing",
            "scene",
            "composition",
            "character_action",
            "dialogue",
        ]
        normalized_pages: list[dict] = []
        seen_page_nos: set[int] = set()
        for raw_page in pages:
            if not isinstance(raw_page, dict):
                raise ValueError("page item must be an object")
            section_no = int(raw_page.get("section_no", 0))
            page_no = int(raw_page.get("page_no", 0))
            if section_no != section.section_no:
                raise ValueError(
                    f"page {page_no} section_no must be {section.section_no}, got {section_no}"
                )
            if page_no < section.page_start or page_no > section.page_end:
                raise ValueError(
                    f"page_no must be in section {section.section_no} range "
                    f"{section.page_start}-{section.page_end}, got {page_no}"
                )
            if page_no in seen_page_nos:
                raise ValueError(f"duplicate page_no in section {section.section_no}: {page_no}")
            character_keys = raw_page.get("character_keys", [])
            if not isinstance(character_keys, list):
                raise ValueError(f"page {page_no} character_keys must be a list")
            for field_name in required_text_fields:
                if not str(raw_page.get(field_name, "")).strip():
                    raise ValueError(f"page {page_no} missing required field: {field_name}")
            seen_page_nos.add(page_no)
            normalized_pages.append(
                {
                    "section_no": section_no,
                    "page_no": page_no,
                    "scene_key": str(raw_page.get("scene_key", "")).strip(),
                    "character_keys": [
                        str(character_key).strip()
                        for character_key in character_keys
                        if str(character_key).strip()
                    ],
                    "summary": str(raw_page.get("summary", "")).strip(),
                    "characters": str(raw_page.get("characters", "")).strip(),
                    "clothing": str(raw_page.get("clothing", "")).strip(),
                    "scene": str(raw_page.get("scene", "")).strip(),
                    "composition": str(raw_page.get("composition", "")).strip(),
                    "character_action": str(raw_page.get("character_action", "")).strip(),
                    "dialogue": str(raw_page.get("dialogue", "")).strip() or "无",
                    "is_revision": bool(raw_page.get("is_revision", False)),
                    "revision_note": str(raw_page.get("revision_note", "")).strip(),
                }
            )

        if seen_page_nos != expected_page_nos:
            missing = sorted(expected_page_nos - seen_page_nos)
            extra = sorted(seen_page_nos - expected_page_nos)
            raise ValueError(f"{error_label}; missing={missing}, extra={extra}")
        return sorted(normalized_pages, key=lambda page: page["page_no"])

    @staticmethod
    def _merge_revision_pages(
        *,
        current_pages: list[dict] | None,
        revision_pages: list[dict],
    ) -> list[dict]:
        """把监督修订页按 page_no 覆盖进当前完整 section 页面集。"""

        if not current_pages:
            raise ValueError("revision cannot be merged before full section pages exist")
        pages_by_no = {int(page["page_no"]): page for page in current_pages}
        for page in revision_pages:
            pages_by_no[int(page["page_no"])] = page
        return [pages_by_no[page_no] for page_no in sorted(pages_by_no)]

    def _save_section_pages(
        self,
        *,
        project_id: int,
        section: ScriptSection,
        pages: list[dict],
        visual_settings: dict,
        script_review_status: PageScriptReviewStatus = PageScriptReviewStatus.UNREVIEWED,
    ) -> list[ComicPage]:
        """当前 section 通过校验后再批量落库，避免保存半成品页面。"""

        saved_pages: list[ComicPage] = []
        for page_payload in pages:
            scene_id = visual_settings["scene_ids_by_key"][page_payload["scene_key"]]
            character_ids = [
                visual_settings["character_ids_by_key"][key]
                for key in page_payload.get("character_keys", [])
            ]
            saved_pages.append(
                self.repository.upsert_page_script(
                    project_id=project_id,
                    page_no=int(page_payload["page_no"]),
                    section_id=section.id,
                    scene_id=scene_id,
                    character_ids=character_ids,
                    script_review_status=script_review_status,
                    script_review_error=None,
                    **self._page_payload_for_save(page_payload),
                )
            )
        return saved_pages

    def _build_previous_sections_context(
        self,
        *,
        task_id: int,
        current_section_no: int,
    ) -> dict:
        """为当前分段生成准备历史上下文：全部摘要 + 最近两个完整分段结构化脚本。"""

        sections = [
            section
            for section in self.repository.list_script_sections(task_id)
            if section.section_no < current_section_no
        ]
        pages_by_section_id: dict[int, list[ComicPage]] = {}
        for page in self.repository.list_script_task_pages(task_id):
            if page.section_id is None:
                continue
            pages_by_section_id.setdefault(page.section_id, []).append(page)

        summaries: list[dict] = []
        for section in sections:
            section_pages = sorted(
                pages_by_section_id.get(section.id, []),
                key=lambda page: page.page_no,
            )
            page_nos = [page.page_no for page in section_pages if page.summary]
            summaries.append(
                {
                    "section_no": section.section_no,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "title": section.title,
                    "description": section.description,
                    "generated_pages": (
                        f"{min(page_nos)}-{max(page_nos)}" if page_nos else "无"
                    ),
                    "script_summary": self._script_excerpt(
                        "\n".join(self._page_context_text(page) for page in section_pages),
                        limit=300,
                    ),
                }
            )

        recent_full_sections: list[dict] = []
        for section in sections[-2:]:
            section_pages = sorted(
                pages_by_section_id.get(section.id, []),
                key=lambda page: page.page_no,
            )
            recent_full_sections.append(
                {
                    "section_no": section.section_no,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "title": section.title,
                    "pages": [
                        {
                            "page_no": page.page_no,
                            "summary": page.summary or "",
                            "characters": page.characters or "",
                            "clothing": page.clothing or "",
                            "scene": page.scene or "",
                            "composition": page.composition or "",
                            "character_action": page.character_action or "",
                            "dialogue": page.dialogue or "",
                        }
                        for page in section_pages
                        if page.summary
                    ],
                }
            )

        return {
            "completed_section_summaries": summaries,
            "recent_full_sections": recent_full_sections,
            "known_scenes": [
                self._scene_to_payload(scene)
                for scene in self.repository.list_script_scenes(task_id)
            ],
        }

    def _outline_characters_context(self, outline_version_id: int) -> list[dict]:
        """读取已确认大纲版本下的角色基准，供分段 Agent 细化当前分段状态。"""

        return [
            self._outline_character_to_payload(character)
            for character in self.repository.list_outline_characters(outline_version_id)
        ]

    @staticmethod
    def _script_excerpt(text: str, *, limit: int) -> str:
        """压缩历史脚本，给后续分段提供衔接线索但控制上下文长度。"""

        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _page_context_text(page: ComicPage) -> str:
        """把结构化页面脚本压成历史上下文文本，供后续分段保持衔接。"""

        return " ".join(
            value
            for value in [
                page.summary,
                page.characters,
                page.clothing,
                page.scene,
                page.composition,
                page.character_action,
                page.dialogue,
            ]
            if value
        )

    @staticmethod
    def _page_to_payload(page: ComicPage) -> dict:
        """把页面 ORM 对象转成 SSE 可 JSON 序列化的字典。"""

        return {
            "id": page.id,
            "project_id": page.project_id,
            "section_id": page.section_id,
            "section_no": page.section.section_no if page.section is not None else None,
            "task_id": page.section.task_id if page.section is not None else None,
            "scene_id": page.scene_id,
            "scene_key": page.script_scene.scene_key if page.script_scene is not None else None,
            "character_keys": [
                character.character_key
                for character in sorted(page.visual_characters, key=lambda item: item.character_key)
            ],
            "page_no": page.page_no,
            "summary": page.summary,
            "characters": page.characters,
            "clothing": page.clothing,
            "scene": page.scene,
            "composition": page.composition,
            "character_action": page.character_action,
            "dialogue": page.dialogue,
            "image_prompt": page.image_prompt,
            "status": page.status.value,
            "script_review_status": page.script_review_status.value,
            "script_review_error": page.script_review_error,
            "created_at": page.created_at.isoformat(),
            "updated_at": page.updated_at.isoformat(),
        }

    @staticmethod
    def _scene_to_payload(scene: ScriptScene) -> dict:
        """把中心化场景设定转成 Agent 上下文和 API 可复用的结构。"""

        return {
            "id": scene.id,
            "task_id": scene.task_id,
            "scene_key": scene.scene_key,
            "name": scene.name,
            "location_type": scene.location_type,
            "time_of_day": scene.time_of_day,
            "lighting": scene.lighting,
            "weather": scene.weather,
            "environment_details": scene.environment_details,
            "color_palette": scene.color_palette,
            "visual_anchors": scene.visual_anchors,
            "negative_constraints": scene.negative_constraints,
            "created_at": scene.created_at.isoformat(),
            "updated_at": scene.updated_at.isoformat(),
        }

    @staticmethod
    def _character_to_payload(character: ScriptCharacter) -> dict:
        """把分段角色设定转成 Agent 上下文和 API 可复用的结构。"""

        return {
            "id": character.id,
            "section_id": character.section_id,
            "task_id": character.section.task_id if character.section is not None else None,
            "outline_character_id": character.outline_character_id,
            "character_key": character.character_key,
            "name": character.name,
            "section_role": character.section_role,
            "current_hairstyle": character.current_hairstyle,
            "current_clothing": character.current_clothing,
            "current_accessories": character.current_accessories,
            "current_state": character.current_state,
            "emotion": character.emotion,
            "temporary_changes": character.temporary_changes,
            "visual_anchors": character.visual_anchors,
            "negative_constraints": character.negative_constraints,
            "outline_character": (
                ScriptService._outline_character_to_payload(character.outline_character)
                if character.outline_character is not None
                else None
            ),
            "created_at": character.created_at.isoformat(),
            "updated_at": character.updated_at.isoformat(),
        }

    @staticmethod
    def _outline_character_to_payload(character: OutlineCharacter) -> dict:
        """把大纲角色基准设定转成 Agent 上下文字典。"""

        return {
            "id": character.id,
            "outline_version_id": character.outline_version_id,
            "character_key": character.character_key,
            "name": character.name,
            "role": character.role,
            "background": character.background,
            "appearance": character.appearance,
            "visual_anchors": character.visual_anchors,
            "negative_constraints": character.negative_constraints,
            "default_hairstyle": character.default_hairstyle,
            "default_clothing": character.default_clothing,
            "default_accessories": character.default_accessories,
            "default_color_palette": character.default_color_palette,
        }

    @staticmethod
    def _section_to_payload(section: ScriptSection) -> dict:
        """把分段 ORM 对象转成 SSE/API 可以直接使用的字典。"""

        return {
            "id": section.id,
            "task_id": section.task_id,
            "section_no": section.section_no,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "title": section.title,
            "description": section.description,
            "status": section.status.value,
            "error_message": section.error_message,
            "created_at": section.created_at.isoformat(),
            "updated_at": section.updated_at.isoformat(),
        }

    @staticmethod
    def _json_dumps(value) -> str:
        """用统一格式保存 Agent 结构化中间结果。"""

        import json

        return json.dumps(value, ensure_ascii=False)
