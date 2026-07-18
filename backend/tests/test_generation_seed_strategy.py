from types import SimpleNamespace

import pytest

from backend.i18n.errors import AppError
from backend.models.enums import (
    GenerationMode,
    ImagePromptType,
    PageScriptReviewStatus,
    ScriptGenerationTaskStatus,
    SeedStrategy,
)
from backend.services.image_generation_service import ImageGenerationService


class FakeGenerationRepository:
    def __init__(self, runs_by_page=None):
        self.runs_by_page = runs_by_page or {}
        self.calls = []

    def list_successful_runs(
        self, *, page_id, prompt_type, generation_mode, image_spec_id
    ):
        del prompt_type, generation_mode
        self.calls.append((page_id, image_spec_id))
        return self.runs_by_page.get(page_id, [])


def _service() -> ImageGenerationService:
    return ImageGenerationService(repository=SimpleNamespace())


def test_per_page_seeds_are_unique_and_shared_candidate_reuses_by_slot() -> None:
    pages = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    per_page = _service()._structured_seed_pairs(
        pages=pages,
        generation_repository=FakeGenerationRepository(),
        prompt_type=ImagePromptType.TAG,
        generation_mode=GenerationMode.PREVIEW,
        image_spec_ids_by_page={1: 11, 2: 12, 3: 13},
        candidates_per_page=2,
        seed_strategy=SeedStrategy.PER_PAGE,
        continue_existing=False,
    )
    per_page_seeds = [seed for pairs in per_page.values() for _, seed in pairs]
    assert len(per_page_seeds) == len(set(per_page_seeds)) == 6

    shared = _service()._structured_seed_pairs(
        pages=pages,
        generation_repository=FakeGenerationRepository(),
        prompt_type=ImagePromptType.TAG,
        generation_mode=GenerationMode.PREVIEW,
        image_spec_ids_by_page={1: 11, 2: 12, 3: 13},
        candidates_per_page=2,
        seed_strategy=SeedStrategy.SHARED_CANDIDATE,
        continue_existing=False,
    )
    assert shared[1][0][1] == shared[2][0][1] == shared[3][0][1]
    assert shared[1][1][1] == shared[2][1][1] == shared[3][1][1]
    assert shared[1][0][1] != shared[1][1][1]


def test_continue_uses_successful_generation_run_slots() -> None:
    pages = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    runs = {
        1: [SimpleNamespace(candidate_index=1, seed=101)],
        2: [
            SimpleNamespace(candidate_index=1, seed=201),
            SimpleNamespace(candidate_index=2, seed=202),
        ],
    }
    repository = FakeGenerationRepository(runs)
    result = _service()._structured_seed_pairs(
        pages=pages,
        generation_repository=repository,
        prompt_type=ImagePromptType.NATURAL_LANGUAGE,
        generation_mode=GenerationMode.FINAL,
        image_spec_ids_by_page={1: 11, 2: 12},
        candidates_per_page=2,
        seed_strategy=SeedStrategy.PER_PAGE,
        continue_existing=True,
    )

    assert [index for index, _ in result[1]] == [2]
    assert result[2] == []
    assert result[1][0][1] not in {101, 201, 202}
    assert repository.calls == [(1, 11), (2, 12)]


def test_generation_rejects_unreviewed_requested_pages() -> None:
    pages = [
        SimpleNamespace(page_no=1, script_review_status=PageScriptReviewStatus.PASSED),
        SimpleNamespace(page_no=2, script_review_status=PageScriptReviewStatus.UNREVIEWED),
    ]

    with pytest.raises(AppError) as exc_info:
        ImageGenerationService._ensure_pages_reviewed(pages)

    assert exc_info.value.code == "script.pages_not_reviewed"
    assert exc_info.value.status_code == 409
    assert exc_info.value.params == {"pages": "2"}


def test_generation_rejects_script_task_that_is_not_succeeded() -> None:
    repository = SimpleNamespace(
        get_script_task=lambda _task_id: SimpleNamespace(
            status=ScriptGenerationTaskStatus.RUNNING
        )
    )
    service = ImageGenerationService(repository=repository)

    with pytest.raises(AppError) as exc_info:
        service._get_script_task(7)

    assert exc_info.value.code == "script.task_not_succeeded"
    assert exc_info.value.status_code == 409
