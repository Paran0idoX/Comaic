from types import SimpleNamespace

import pytest

from backend.agents.page_script_writer_agent import PageScriptWriterAgent
from backend.models.enums import PageScriptReviewStatus, ScriptGenerationTaskStatus
from backend.services.script_service import ScriptService


def test_writer_input_lists_exact_allowed_visual_keys() -> None:
    """把允许 key 放在输入前部，降低模型沿用上一分段场景的概率。"""

    prompt = PageScriptWriterAgent._build_section_input(
        outline="测试大纲",
        total_pages=50,
        current_section={"section_no": 8, "page_start": 36, "page_end": 40},
        target_page_no=36,
        section_scenes=[
            {"scene_key": "hidden_staircase", "name": "隐藏楼梯"},
            {"scene_key": "corridor_outside", "name": "走廊"},
        ],
        section_characters=[{"character_key": "lin_lan", "name": "林岚"}],
        previous_context={},
        outline_characters=[],
        user_requirement="",
        feedback="",
        is_revision=False,
        current_pages=[],
    )

    assert "本页 scene_key 允许值（只能逐字复制其中一个）：hidden_staircase、corridor_outside" in prompt
    assert "本页 character_keys 允许值（只能逐字复制，或无角色时返回空数组）：lin_lan" in prompt


def test_visual_reference_feedback_lists_allowed_scene_keys() -> None:
    """校验失败反馈必须给出可用 key，才能让同页重试形成有效闭环。"""

    with pytest.raises(ValueError) as exc_info:
        ScriptService._validate_page_visual_references(
            pages=[
                {
                    "page_no": 36,
                    "scene_key": "hidden_office",
                    "character_keys": ["lin_lan"],
                    "characters": "林岚",
                }
            ],
            visual_context={
                "scenes": [
                    {"scene_key": "hidden_staircase"},
                    {"scene_key": "corridor_outside"},
                ],
                "characters": [{"character_key": "lin_lan"}],
            },
        )

    message = str(exc_info.value)
    assert "hidden_office" in message
    assert "corridor_outside、hidden_staircase" in message
    assert "重写整页" in message


@pytest.mark.asyncio
async def test_single_page_generation_saves_supervisor_passed_status(monkeypatch) -> None:
    """单页已通过 Supervisor 后应直接可进入后续链路，不能再次落成未审查。"""

    class Repository:
        def __init__(self):
            self.task = SimpleNamespace(
                id=7,
                project_id=1,
                status=ScriptGenerationTaskStatus.RUNNING,
            )
            self.saved_kwargs = None

        def create_script_task(self, **_kwargs):
            return self.task

        def upsert_page_script(self, **kwargs):
            self.saved_kwargs = kwargs
            return SimpleNamespace(id=9, page_no=3)

        def update_script_task(self, *, status, **_kwargs):
            self.task.status = status
            return self.task

        def get_script_task(self, _task_id):
            return self.task

    class Writer:
        async def generate_page(self, **_kwargs):
            return [{"page_no": 3}]

    class Supervisor:
        async def review_section_pages(self, **_kwargs):
            return {"passed": True, "reviews": [{"page_no": 3, "passed": True}]}

    repository = Repository()
    service = ScriptService(repository)
    section = SimpleNamespace(id=8, task_id=7, page_start=3, page_end=3)
    page_payload = {
        "page_no": 3,
        "scene_key": "single_scene",
        "character_keys": ["hero"],
        "summary": "summary",
        "characters": "hero",
        "clothing": "coat",
        "scene": "room",
        "composition": "medium shot",
        "character_action": "stands",
        "dialogue": "none",
    }

    monkeypatch.setattr(
        "backend.services.script_service.PageScriptWriterAgent", lambda: Writer()
    )
    monkeypatch.setattr(
        "backend.services.script_service.ScriptSupervisorAgent", lambda: Supervisor()
    )
    monkeypatch.setattr(
        service,
        "_resolve_outline_version",
        lambda **_kwargs: SimpleNamespace(id=2, content="outline"),
    )
    monkeypatch.setattr(service, "_create_single_page_section", lambda **_kwargs: section)
    monkeypatch.setattr(service, "_section_to_payload", lambda _section: {})
    monkeypatch.setattr(service, "_outline_characters_context", lambda _id: [])
    monkeypatch.setattr(service, "_save_section_visual_settings", lambda **_kwargs: None)
    monkeypatch.setattr(service, "_normalize_single_page", lambda **_kwargs: [page_payload])
    monkeypatch.setattr(
        service,
        "_visual_settings_for_section",
        lambda **_kwargs: {
            "scene_ids_by_key": {"single_scene": 11},
            "character_ids_by_key": {"hero": 12},
        },
    )

    task, _page = await service.generate_single_page_script(
        project_id=1,
        page_no=3,
        total_pages=5,
        outline_version_id=2,
    )

    assert task.status == ScriptGenerationTaskStatus.SUCCEEDED
    assert repository.saved_kwargs["script_review_status"] == PageScriptReviewStatus.PASSED
