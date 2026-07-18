from types import SimpleNamespace

import pytest

from backend.i18n.errors import AppError
from backend.models.enums import PageScriptReviewStatus, ScriptGenerationTaskStatus
from backend.services.script_service import ScriptService


class ReviewRepository:
    """复审服务的最小内存仓库；测试不创建真实模型或数据库连接。"""

    def __init__(self, pages):
        self.pages = pages
        self.task = SimpleNamespace(
            id=3,
            status=ScriptGenerationTaskStatus.SUCCEEDED,
            outline_version_id=2,
        )
        self.outline = SimpleNamespace(id=2, content="outline")

    def get_script_task(self, task_id):
        return self.task if task_id == self.task.id else None

    def get_outline_version(self, outline_version_id):
        return self.outline if outline_version_id == self.outline.id else None

    def list_script_task_pages(self, _task_id):
        return self.pages

    def update_page_script_review_status(self, *, page_id, status, error_message=None):
        page = next(item for item in self.pages if item.id == page_id)
        page.script_review_status = status
        page.script_review_error = error_message
        return page


def _page(page_id, page_no, section, status):
    return SimpleNamespace(
        id=page_id,
        page_no=page_no,
        summary=f"page {page_no}",
        section=section,
        script_review_status=status,
        script_review_error=None,
    )


def _service(repository):
    service = ScriptService(repository)
    service._outline_characters_context = lambda _outline_id: []
    service._section_visual_context = lambda **_kwargs: {
        "scenes": [{"scene_key": "room"}],
        "characters": [{"character_key": "hero"}],
    }
    service._section_to_payload = lambda section: {"section_no": section.section_no}
    service._page_to_writer_payload = lambda page: {
        "page_no": page.page_no,
        "scene_key": "room",
        "character_keys": ["hero"],
    }
    service._page_to_payload = lambda page: {
        "id": page.id,
        "page_no": page.page_no,
        "script_review_status": page.script_review_status.value,
        "script_review_error": page.script_review_error,
    }
    return service


@pytest.mark.asyncio
async def test_review_existing_pages_updates_each_result_without_rewriting(monkeypatch) -> None:
    section = SimpleNamespace(id=8, section_no=9, task_id=3)
    pages = [
        _page(1, 41, section, PageScriptReviewStatus.UNREVIEWED),
        _page(2, 42, section, PageScriptReviewStatus.FAILED),
        _page(3, 43, section, PageScriptReviewStatus.PASSED),
    ]
    repository = ReviewRepository(pages)
    service = _service(repository)

    class Supervisor:
        async def review_section_pages(self, **kwargs):
            assert [item["page_no"] for item in kwargs["pages"]] == [41, 42]
            return {
                "passed": False,
                "reviews": [
                    {"page_no": 41, "passed": True, "summary": "ok"},
                    {
                        "page_no": 42,
                        "passed": False,
                        "summary": "conflict",
                        "revision_suggestions": ["keep the watch attached"],
                    },
                ],
            }

    monkeypatch.setattr(
        "backend.services.script_service.ScriptSupervisorAgent", lambda: Supervisor()
    )

    events = [
        item
        async for item in service.stream_review_script_pages(task_id=3)
    ]

    assert pages[0].script_review_status == PageScriptReviewStatus.PASSED
    assert pages[1].script_review_status == PageScriptReviewStatus.FAILED
    assert "keep the watch attached" in pages[1].script_review_error
    assert pages[2].script_review_status == PageScriptReviewStatus.PASSED
    assert events[-1] == (
        "done",
        {
            "task_id": 3,
            "total": 2,
            "passed": 1,
            "failed": 1,
            "failed_page_nos": [42],
        },
    )


@pytest.mark.asyncio
async def test_review_existing_pages_failure_does_not_leave_reviewing(monkeypatch) -> None:
    section = SimpleNamespace(id=8, section_no=9, task_id=3)
    page = _page(1, 41, section, PageScriptReviewStatus.UNREVIEWED)
    repository = ReviewRepository([page])
    service = _service(repository)

    class Supervisor:
        async def review_section_pages(self, **_kwargs):
            raise RuntimeError("provider failed")

    monkeypatch.setattr(
        "backend.services.script_service.ScriptSupervisorAgent", lambda: Supervisor()
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        async for _event in service.stream_review_script_pages(task_id=3):
            pass

    assert page.script_review_status == PageScriptReviewStatus.FAILED
    assert page.script_review_error == "common.internal_error"


@pytest.mark.asyncio
async def test_review_existing_pages_rejects_when_every_page_passed() -> None:
    section = SimpleNamespace(id=8, section_no=9, task_id=3)
    page = _page(1, 41, section, PageScriptReviewStatus.PASSED)
    service = _service(ReviewRepository([page]))

    with pytest.raises(AppError) as exc_info:
        async for _event in service.stream_review_script_pages(task_id=3):
            pass

    assert exc_info.value.code == "script.pages_review_not_needed"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_review_existing_pages_rejects_invalid_page_numbers_before_agent() -> None:
    section = SimpleNamespace(id=8, section_no=9, task_id=3)
    page = _page(1, 41, section, PageScriptReviewStatus.UNREVIEWED)
    service = _service(ReviewRepository([page]))

    with pytest.raises(AppError) as exc_info:
        async for _event in service.stream_review_script_pages(
            task_id=3,
            page_nos=[],
        ):
            pass

    assert exc_info.value.code == "common.validation_error"
    assert exc_info.value.status_code == 422
