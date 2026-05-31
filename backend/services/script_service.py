from backend.agents.script_deep_agent import ScriptDeepAgent
from backend.agents.script_planning_agent import ScriptPlanningAgent
from backend.models.comic import (
    ComicPage,
    ComicProject,
    OutlineVersion,
    ScriptGenerationTask,
    ScriptSection,
)
from backend.models.enums import ScriptGenerationMode, ScriptGenerationTaskStatus
from backend.repositories.comic_repository import ComicRepository


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

    def upsert_manual_page_script(self, *, project_id: int, page_no: int, script: str) -> ComicPage:
        """人工新增或更新单页脚本；生成任务结束后由前端编辑使用。"""

        self._get_project(project_id)
        normalized_script = script.strip()
        if not normalized_script:
            raise ValueError("Page script cannot be empty")
        section = self._resolve_manual_section(project_id=project_id, page_no=page_no)
        return self.repository.upsert_page_script(
            project_id=project_id,
            page_no=page_no,
            script=normalized_script,
            section_id=section.id,
        )

    def clear_page_script(self, *, project_id: int, page_no: int) -> ComicPage:
        """人工清空单页脚本；不删除页面行，避免破坏后续关联数据。"""

        self._get_project(project_id)
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

        try:
            result = await ScriptDeepAgent().generate_single_page(
                outline=outline_version.content,
                total_pages=total_pages,
                page_no=page_no,
                user_requirement=user_requirement or "",
            )
            page_payload = self._find_page_payload(result.get("pages", []), page_no)
            page = self.repository.upsert_page_script(
                project_id=project_id,
                page_no=page_no,
                script=self._format_page_script(page_payload),
                section_id=self._create_single_page_section(
                    task_id=task.id,
                    page_no=page_no,
                ).id,
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
        yield "task", {"task_id": task.id, "status": task.status.value}
        yield "phase", {"message": "正在生成故事节奏划分"}

        try:
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
                        "message": f"分段计划校验失败，正在第 {attempt} 次重试",
                    }
                raw_sections = await planning_agent.generate_section_plan(
                    outline=outline_version.content,
                    total_pages=total_pages,
                    user_requirement=user_requirement or "",
                    feedback=planning_feedback,
                )
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
                normalized_sections=normalized_sections,
            )
            yield "section_plan", {
                "sections": [self._section_to_payload(section) for section in persisted_sections]
            }
            for section in persisted_sections:
                yield "section", self._section_to_payload(section)
            yield "phase", {"message": "分段计划已锁定，正在生成页面脚本"}

            script_agent = ScriptDeepAgent()
            for section in persisted_sections:
                if self._is_script_task_suspended(task.id):
                    yield "suspended", {"task_id": task.id, "status": ScriptGenerationTaskStatus.SUSPENDED.value}
                    return

                yield "phase", {
                    "message": (
                        f"正在生成第 {section.section_no} 段"
                        f"（第 {section.page_start}-{section.page_end} 页）"
                    )
                }
                feedback = ""
                normalized_pages: list[dict] | None = None
                result: dict | None = None
                for attempt in range(1, 4):
                    if self._is_script_task_suspended(task.id):
                        yield "suspended", {
                            "task_id": task.id,
                            "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                        }
                        return
                    if attempt > 1:
                        yield "phase", {
                            "message": (
                                f"第 {section.section_no} 段脚本校验失败，"
                                f"正在第 {attempt} 次重试"
                            )
                        }
                    result = await script_agent.generate_section(
                        outline=outline_version.content,
                        total_pages=total_pages,
                        current_section=self._section_to_payload(section),
                        previous_context=self._build_previous_sections_context(
                            task_id=task.id,
                            current_section_no=section.section_no,
                        ),
                        user_requirement=user_requirement or "",
                        feedback=feedback,
                    )
                    yield "phase", {
                        "message": (
                            f"第 {section.section_no} 段 Agent 已返回，"
                            f"正在校验第 {section.page_start}-{section.page_end} 页"
                        )
                    }
                    try:
                        normalized_pages = self._normalize_section_pages(
                            pages=result.get("pages", []),
                            section=section,
                        )
                        yield "phase", {
                            "message": (
                                f"第 {section.section_no} 段校验通过，"
                                f"正在保存 {len(normalized_pages)} 页脚本"
                            )
                        }
                        break
                    except ValueError as exc:
                        feedback = str(exc)
                        yield "phase", {
                            "message": f"第 {section.section_no} 段脚本校验失败：{feedback}"
                        }
                        if attempt >= 3:
                            raise ValueError(
                                f"第 {section.section_no} 段脚本连续 3 次校验失败：{feedback}"
                            ) from exc

                if normalized_pages is None or result is None:
                    raise ValueError(f"第 {section.section_no} 段脚本生成失败。")
                if self._is_script_task_suspended(task.id):
                    yield "suspended", {
                        "task_id": task.id,
                        "status": ScriptGenerationTaskStatus.SUSPENDED.value,
                    }
                    return

                saved_pages = self._save_section_pages(
                    project_id=project_id,
                    section=section,
                    pages=normalized_pages,
                )
                yield "phase", {
                    "message": f"第 {section.section_no} 段已保存，正在推送页面列表"
                }
                reviews = [
                    review if isinstance(review, dict) else {"comments": str(review)}
                    for review in result.get("reviews", [])
                ]
                for review in reviews:
                    yield "review", {"section_no": section.section_no, **review}
                yield "section_pages", {
                    "section": self._section_to_payload(section),
                    "pages": [self._page_to_payload(page) for page in saved_pages],
                    "reviews": reviews,
                }

            if self._is_script_task_suspended(task.id):
                yield "suspended", {"task_id": task.id, "status": ScriptGenerationTaskStatus.SUSPENDED.value}
                return
            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.SUCCEEDED,
            )
            yield "done", {"task_id": task.id, "status": task.status.value}
        except Exception as exc:
            task = self.repository.update_script_task(
                task_id=task.id,
                status=ScriptGenerationTaskStatus.FAILED,
                error_message=str(exc),
            )
            yield "error", {
                "task_id": task.id,
                "status": task.status.value,
                "message": str(exc),
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
            return outline_version

        outline_version = self.repository.get_active_outline_version_for_project(project_id)
        if outline_version is None:
            raise ValueError(f"Active outline not found for project: {project_id}")
        return outline_version

    def _resolve_manual_section(self, *, project_id: int, page_no: int) -> ScriptSection:
        """人工新增脚本时找到可挂载分段；没有历史任务时创建手动任务和分段。"""

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
        normalized_sections: list[dict],
    ) -> list[ScriptSection]:
        """保存已校验通过的分段计划；这是任务内唯一允许锁定分段的入口。"""

        self.repository.update_script_task(
            task_id=task_id,
            section_plan=self._json_dumps(normalized_sections),
        )
        return [
            self.repository.upsert_script_section(
                task_id=task_id,
                section_no=section["section_no"],
                page_start=section["page_start"],
                page_end=section["page_end"],
                title=section["title"],
                description=section["description"],
            )
            for section in normalized_sections
        ]

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
    def _format_page_script(page_payload: dict) -> str:
        """把结构化页面脚本转换为适合保存展示的中文文本。"""

        return "\n".join(
            [
                f"页面目标：{page_payload.get('page_goal', '')}",
                f"画面内容：{page_payload.get('scene', '')}",
                f"角色动作：{page_payload.get('character_action', '')}",
                f"对白或旁白：{page_payload.get('dialogue_or_caption', '')}",
                f"完整脚本：{page_payload.get('script', '')}",
            ]
        ).strip()

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
            expected_start = section["page_end"] + 1
        if expected_start != total_pages + 1:
            raise ValueError(
                f"section plan must cover pages 1-{total_pages}; "
                f"last covered page is {expected_start - 1}"
            )
        return normalized_sections

    def _normalize_section_pages(self, *, pages: list, section: ScriptSection) -> list[dict]:
        """校验当前分段脚本输出，确保 Agent 只能交付当前 section 的完整页码范围。"""

        if not isinstance(pages, list) or not pages:
            raise ValueError("section pages cannot be empty")

        required_text_fields = [
            "page_goal",
            "scene",
            "character_action",
            "dialogue_or_caption",
            "script",
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
            for field_name in required_text_fields:
                if not str(raw_page.get(field_name, "")).strip():
                    raise ValueError(f"page {page_no} missing required field: {field_name}")
            seen_page_nos.add(page_no)
            normalized_pages.append(
                {
                    "section_no": section_no,
                    "page_no": page_no,
                    "page_goal": str(raw_page.get("page_goal", "")).strip(),
                    "scene": str(raw_page.get("scene", "")).strip(),
                    "character_action": str(raw_page.get("character_action", "")).strip(),
                    "dialogue_or_caption": str(raw_page.get("dialogue_or_caption", "")).strip(),
                    "script": str(raw_page.get("script", "")).strip(),
                    "is_revision": bool(raw_page.get("is_revision", False)),
                    "revision_note": str(raw_page.get("revision_note", "")).strip(),
                }
            )

        expected_page_nos = set(range(section.page_start, section.page_end + 1))
        if seen_page_nos != expected_page_nos:
            missing = sorted(expected_page_nos - seen_page_nos)
            extra = sorted(seen_page_nos - expected_page_nos)
            raise ValueError(
                f"section {section.section_no} pages must cover "
                f"{section.page_start}-{section.page_end}; missing={missing}, extra={extra}"
            )
        return sorted(normalized_pages, key=lambda page: page["page_no"])

    def _save_section_pages(
        self,
        *,
        project_id: int,
        section: ScriptSection,
        pages: list[dict],
    ) -> list[ComicPage]:
        """当前 section 通过校验后再批量落库，避免保存半成品页面。"""

        saved_pages: list[ComicPage] = []
        for page_payload in pages:
            saved_pages.append(
                self.repository.upsert_page_script(
                    project_id=project_id,
                    page_no=int(page_payload["page_no"]),
                    script=self._format_page_script(page_payload),
                    section_id=section.id,
                )
            )
        return saved_pages

    def _build_previous_sections_context(
        self,
        *,
        task_id: int,
        current_section_no: int,
    ) -> dict:
        """为当前分段生成准备历史上下文：全部摘要 + 最近两个完整分段脚本。"""

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
            page_nos = [page.page_no for page in section_pages if page.script]
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
                        "\n".join(page.script or "" for page in section_pages),
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
                            "script": page.script or "",
                        }
                        for page in section_pages
                        if page.script
                    ],
                }
            )

        return {
            "completed_section_summaries": summaries,
            "recent_full_sections": recent_full_sections,
        }

    @staticmethod
    def _script_excerpt(text: str, *, limit: int) -> str:
        """压缩历史脚本，给后续分段提供衔接线索但控制上下文长度。"""

        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _page_to_payload(page: ComicPage) -> dict:
        """把页面 ORM 对象转成 SSE 可 JSON 序列化的字典。"""

        return {
            "id": page.id,
            "project_id": page.project_id,
            "section_id": page.section_id,
            "section_no": page.section.section_no if page.section is not None else None,
            "task_id": page.section.task_id if page.section is not None else None,
            "page_no": page.page_no,
            "script": page.script,
            "status": page.status.value,
            "created_at": page.created_at.isoformat(),
            "updated_at": page.updated_at.isoformat(),
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
            "created_at": section.created_at.isoformat(),
            "updated_at": section.updated_at.isoformat(),
        }

    @staticmethod
    def _json_dumps(value) -> str:
        """用统一格式保存 Agent 结构化中间结果。"""

        import json

        return json.dumps(value, ensure_ascii=False)
