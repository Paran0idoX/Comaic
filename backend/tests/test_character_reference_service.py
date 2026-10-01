import asyncio
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import func, select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.services.character_reference_service as service_module
from backend.api.character_reference import task_response
from backend.i18n.errors import AppError
from backend.models.comic import (
    Base,
    CharacterReferenceImage,
    ComicImage,
    ComicPage,
    ComicProject,
    ImageGenerationToolPreset,
    ImageSpec,
    OutlineCharacter,
    OutlineVersion,
    Session as ComicSession,
    StyleProfile,
    VisualAsset,
)
from backend.models.enums import (
    ApprovalStatus,
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationProvider,
    ImagePromptType,
    OutlineVersionStatus,
    SessionPurpose,
    VisualAssetRole,
    VisualAssetSource,
    VisualAssetStorageKind,
    VisualEntityType,
)
from backend.models.time import utc_now
from backend.repositories.character_reference_repository import (
    CharacterReferenceRepository,
)
from backend.services.character_reference_prompt_service import (
    CharacterReferencePromptService,
)
from backend.services.character_reference_service import CharacterReferenceService
from backend.services.renderer_backends import RenderedArtifact, RendererSubmission


def _png_bytes(color: tuple[int, int, int] = (56, 120, 210)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 40), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeRenderer:
    """只在内存中返回图片，用调用序号精确模拟单次失败或暂停。"""

    def __init__(
        self,
        *,
        fail_wait_calls: set[int] | None = None,
        on_wait=None,
        artifact_count: int = 1,
    ):
        self.fail_wait_calls = fail_wait_calls or set()
        self.on_wait = on_wait
        self.artifact_count = artifact_count
        self.submissions: list[tuple[dict, int, GenerationMode]] = []
        self.wait_calls = 0

    async def submit(self, *, spec, seed, mode):
        self.submissions.append((spec, seed, mode))
        index = len(self.submissions)
        return RendererSubmission(
            external_id=f"fake-request-{index}",
            applied_spec=spec,
            workflow={"fake": index},
            workflow_hash=f"hash-{index}",
            degradations=[
                {
                    "code": "workflow.seed_not_applied",
                    "message": "Fake renderer intentionally omits seed binding.",
                }
            ],
            seed_applied=False,
        )

    async def wait(self, submission, *, poll_interval_seconds, timeout_seconds):
        del poll_interval_seconds, timeout_seconds
        self.wait_calls += 1
        if self.on_wait is not None:
            self.on_wait(self.wait_calls)
        if self.wait_calls in self.fail_wait_calls:
            raise RuntimeError("intentional fake renderer failure")
        return [
            RenderedArtifact(
                content=_png_bytes((self.wait_calls * 20 % 255, 80, 160)),
                filename=f"{submission.external_id}-{artifact_index}.png",
            )
            for artifact_index in range(1, self.artifact_count + 1)
        ]


@pytest.fixture()
def reference_fixture(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        project = ComicProject(title="Character References")
        outline_session = ComicSession(
            project=project,
            thread_id="character-reference-test",
            purpose=SessionPurpose.OUTLINE,
        )
        outline = OutlineVersion(
            project=project,
            session=outline_session,
            version_no=1,
            content="test outline",
            status=OutlineVersionStatus.ACTIVE,
            confirmed_at=utc_now(),
        )
        character = OutlineCharacter(
            outline_version=outline,
            character_key="hero",
            name="Lin",
            role="detective",
            background="from a coastal city",
            appearance="young woman with amber eyes and a small cheek scar",
            visual_anchors="amber eyes, crescent scar, narrow jaw",
            negative_constraints="never remove the cheek scar",
            default_hairstyle="short black bob",
            default_clothing="navy trench coat",
            default_accessories="silver compass pendant",
            default_color_palette="navy, amber, silver",
        )
        unused_character = OutlineCharacter(
            outline_version=outline,
            character_key="mentor",
            name="Qiao",
            appearance="older archivist",
        )
        session.add(project)
        session.flush()
        style = StyleProfile(
            project_id=project.id,
            key="ink",
            version=1,
            name="Ink Graphic Novel",
            positive_tag="graphic novel, ink linework",
            negative_tag="photorealistic",
            positive_natural_language="graphic-novel ink illustration",
            negative_natural_language="avoid photographic rendering",
            color_palette_json='["indigo", "warm gold"]',
            lighting="soft studio light",
            status=ApprovalStatus.APPROVED,
            approved_at=utc_now(),
        )
        draft_style = StyleProfile(
            project_id=project.id,
            key="draft",
            version=1,
            name="Unapproved style",
            status=ApprovalStatus.DRAFT,
        )
        tool = ImageGenerationToolPreset(
            name="Fake Hybrid Renderer",
            provider=ImageGenerationProvider.COMFYUI,
            prompt_type=ImagePromptType.HYBRID,
            is_default=True,
            capabilities_json='{"features":["txt2img"],"limits":{}}',
            bindings_json='{"schema_version":1,"bindings":[]}',
            workflow_json="{}",
        )
        no_txt2img_tool = ImageGenerationToolPreset(
            name="Img2Img Only",
            provider=ImageGenerationProvider.COMFYUI,
            prompt_type=ImagePromptType.TAG,
            capabilities_json='{"features":["img2img"],"limits":{}}',
            bindings_json='{"schema_version":1,"bindings":[]}',
            workflow_json="{}",
        )
        openai_tool = ImageGenerationToolPreset(
            name="Fake OpenAI Images",
            provider=ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE,
            prompt_type=ImagePromptType.NATURAL_LANGUAGE,
            capabilities_json='{"features":["txt2img"],"limits":{}}',
            bindings_json='{"schema_version":1,"bindings":[]}',
            api_base_url="https://images.invalid/v1",
            api_key="test-secret-that-must-not-leak",
            model="fake-image-model",
        )
        session.add_all([style, draft_style, tool, no_txt2img_tool, openai_tool])
        session.commit()
        service = CharacterReferenceService(
            CharacterReferenceRepository(session),
            output_dir=tmp_path / "outputs",
            asset_root=tmp_path / "visual-assets",
        )
        yield {
            "session": session,
            "project": project,
            "character": character,
            "unused_character": unused_character,
            "style": style,
            "draft_style": draft_style,
            "tool": tool,
            "no_txt2img_tool": no_txt2img_tool,
            "openai_tool": openai_tool,
            "service": service,
            "tmp_path": tmp_path,
        }


def _prompts(prefix: str = "edited") -> dict[str, dict[str, str]]:
    return {
        role.value: {
            "positive": f"  {prefix} positive {role.value}\nkeep whitespace  ",
            "negative": f" {prefix} negative {role.value} ",
        }
        for role in (
            VisualAssetRole.IDENTITY_FACE,
            VisualAssetRole.IDENTITY_HALF_BODY,
            VisualAssetRole.IDENTITY_FULL_BODY,
        )
    }


def _create_task(fixture, *, candidate_count: int = 2, prompts=None):
    return fixture["service"].create_task(
        character_id=fixture["character"].id,
        tool_preset_id=fixture["tool"].id,
        style_profile_id=fixture["style"].id,
        candidate_count=candidate_count,
        prompts=prompts or _prompts(),
    )


def test_prompt_compiler_supports_all_types_style_and_hybrid_order(
    reference_fixture,
) -> None:
    compiler = CharacterReferencePromptService()
    character = reference_fixture["character"]
    style = reference_fixture["style"]

    natural = compiler.compile(
        character=character,
        prompt_type=ImagePromptType.NATURAL_LANGUAGE,
        style=style,
    )
    tags = compiler.compile(
        character=character,
        prompt_type=ImagePromptType.TAG,
        style=style,
    )
    hybrid = compiler.compile(
        character=character,
        prompt_type=ImagePromptType.HYBRID,
        style=style,
    )

    for role in ("identity_face", "identity_half_body", "identity_full_body"):
        assert hybrid[role]["positive"] == (
            natural[role]["positive"] + "\n" + tags[role]["positive"]
        )
        assert hybrid[role]["negative"] == (
            natural[role]["negative"] + "\n" + tags[role]["negative"]
        )
        assert "amber eyes" in hybrid[role]["positive"]
        assert "navy trench coat" in hybrid[role]["positive"]
        assert "graphic-novel ink illustration" in hybrid[role]["positive"]
        assert "graphic novel, ink linework" in hybrid[role]["positive"]
        assert "never remove the cheek scar" in hybrid[role]["negative"]

    without_style = compiler.compile(
        character=character,
        prompt_type=ImagePromptType.NATURAL_LANGUAGE,
        style=None,
    )
    assert (
        "graphic-novel ink illustration"
        not in without_style["identity_face"]["positive"]
    )
    assert "head-and-shoulders" in natural["identity_face"]["positive"]
    assert "waist-up" in natural["identity_half_body"]["positive"]
    assert "head-to-toe" in natural["identity_full_body"]["positive"]


def test_outline_character_list_includes_characters_without_script_appearances(
    reference_fixture,
) -> None:
    characters = reference_fixture["service"].list_outline_characters(
        reference_fixture["character"].outline_version_id
    )
    assert [character.character_key for character in characters] == ["hero", "mentor"]
    project_characters = reference_fixture["service"].list_project_outline_characters(
        reference_fixture["project"].id
    )
    assert [character.character_key for character in project_characters] == [
        "hero",
        "mentor",
    ]


def test_default_two_sets_create_six_runs_with_exact_prompts_and_shared_seeds(
    reference_fixture,
) -> None:
    prompts = _prompts("verbatim")
    task = _create_task(reference_fixture, prompts=prompts)

    assert task.candidate_count == 2
    assert len(task.runs) == 6
    seeds_by_candidate = {
        index: {run.seed for run in task.runs if run.candidate_index == index}
        for index in (1, 2)
    }
    assert all(len(seeds) == 1 for seeds in seeds_by_candidate.values())
    assert seeds_by_candidate[1] != seeds_by_candidate[2]
    snapshot = json.loads(task.prompt_snapshot_json)
    assert snapshot == prompts
    for run in task.runs:
        assert run.positive_prompt == prompts[run.role.value]["positive"]
        assert run.negative_prompt == prompts[run.role.value]["negative"]


def test_fake_renderer_runs_preview_without_creating_comic_records(
    reference_fixture, monkeypatch
) -> None:
    task = _create_task(reference_fixture)
    renderer = FakeRenderer()
    monkeypatch.setattr(
        service_module, "backend_for_preset", lambda *args, **kwargs: renderer
    )

    result = asyncio.run(reference_fixture["service"].run_task(task.id))

    assert result.status == GenerationTaskStatus.SUCCEEDED
    assert len(renderer.submissions) == 6
    assert all(mode == GenerationMode.PREVIEW for _, _, mode in renderer.submissions)
    assert all(run.status == GenerationRunStatus.SUCCEEDED for run in result.runs)
    assert all(run.seed_applied is False for run in result.runs)
    assert all("seed_not_applied" in run.degradation_json for run in result.runs)
    assert all(len(run.images) == 1 for run in result.runs)

    session = reference_fixture["session"]
    assert session.scalar(select(func.count()).select_from(ComicPage)) == 0
    assert session.scalar(select(func.count()).select_from(ComicImage)) == 0
    assert session.scalar(select(func.count()).select_from(ImageSpec)) == 0


def test_failed_run_is_preserved_and_continue_only_retries_missing_run(
    reference_fixture, monkeypatch
) -> None:
    task = _create_task(reference_fixture)
    failing_renderer = FakeRenderer(fail_wait_calls={2})
    monkeypatch.setattr(
        service_module,
        "backend_for_preset",
        lambda *args, **kwargs: failing_renderer,
    )
    first_result = asyncio.run(reference_fixture["service"].run_task(task.id))

    assert first_result.status == GenerationTaskStatus.FAILED
    assert len(failing_renderer.submissions) == 6
    failed_run = next(
        run for run in first_result.runs if run.status == GenerationRunStatus.FAILED
    )
    failed_seed = failed_run.seed
    failed_prompt = failed_run.positive_prompt
    assert sum(bool(run.images) for run in first_result.runs) == 5

    reference_fixture["service"].prepare_continue(task.id)
    recovery_renderer = FakeRenderer()
    monkeypatch.setattr(
        service_module,
        "backend_for_preset",
        lambda *args, **kwargs: recovery_renderer,
    )
    final_result = asyncio.run(reference_fixture["service"].run_task(task.id))

    assert final_result.status == GenerationTaskStatus.SUCCEEDED
    assert len(recovery_renderer.submissions) == 1
    _, retried_seed, _ = recovery_renderer.submissions[0]
    assert retried_seed == failed_seed
    retried_run = next(run for run in final_result.runs if run.id == failed_run.id)
    assert retried_run.positive_prompt == failed_prompt
    assert all(run.status == GenerationRunStatus.SUCCEEDED for run in final_result.runs)
    assert sum(len(run.images) for run in final_result.runs) == 6


def test_suspend_waits_for_current_provider_request_and_stops_next_submission(
    reference_fixture, monkeypatch
) -> None:
    task = _create_task(reference_fixture)

    def suspend_after_first_wait(wait_call: int) -> None:
        if wait_call == 1:
            reference_fixture["service"].suspend_task(task.id)

    renderer = FakeRenderer(on_wait=suspend_after_first_wait)
    monkeypatch.setattr(
        service_module, "backend_for_preset", lambda *args, **kwargs: renderer
    )
    result = asyncio.run(reference_fixture["service"].run_task(task.id))

    assert result.status == GenerationTaskStatus.SUSPENDED
    assert len(renderer.submissions) == 1
    assert sum(run.status == GenerationRunStatus.SUCCEEDED for run in result.runs) == 1
    assert sum(run.status == GenerationRunStatus.PENDING for run in result.runs) == 5


def test_stale_running_task_is_suspended(reference_fixture) -> None:
    task = _create_task(reference_fixture, candidate_count=1)
    reference_fixture["service"].repository.update_task(
        task.id,
        status=GenerationTaskStatus.RUNNING,
        heartbeat_at=utc_now() - timedelta(minutes=1),
    )

    count = reference_fixture["service"].repository.suspend_stale_tasks(
        stale_before=utc_now() - timedelta(seconds=15),
        error_message="stale test",
    )
    suspended = reference_fixture["service"].get_task(task.id)

    assert count == 1
    assert suspended.status == GenerationTaskStatus.SUSPENDED
    assert suspended.error_code == "character_reference.runtime_interrupted"

    pending = _create_task(reference_fixture, candidate_count=1)
    assert reference_fixture["service"].repository.list_pending_task_ids() == [
        pending.id
    ]


def test_whole_set_approval_is_atomic_idempotent_and_preserves_history(
    reference_fixture, monkeypatch
) -> None:
    session = reference_fixture["session"]
    historical_path = reference_fixture["tmp_path"] / "historical.png"
    historical_path.write_bytes(_png_bytes((10, 20, 30)))
    historical = VisualAsset(
        project_id=reference_fixture["project"].id,
        entity_type=VisualEntityType.CHARACTER,
        entity_id=reference_fixture["character"].id,
        role=VisualAssetRole.IDENTITY_FACE,
        storage_kind=VisualAssetStorageKind.LOCAL_FILE,
        local_path=str(historical_path),
        mime_type="image/png",
        sha256="a" * 64,
        width=32,
        height=40,
        version=1,
        status=ApprovalStatus.APPROVED,
        source=VisualAssetSource.UPLOAD,
        approved_at=utc_now(),
    )
    session.add(historical)
    session.commit()
    historical_id = historical.id

    task = _create_task(reference_fixture)
    renderer = FakeRenderer(artifact_count=2)
    monkeypatch.setattr(
        service_module, "backend_for_preset", lambda *args, **kwargs: renderer
    )
    asyncio.run(reference_fixture["service"].run_task(task.id))

    approved = reference_fixture["service"].approve_candidate_set(
        task_id=task.id,
        candidate_index=1,
    )
    generated_assets = list(
        session.scalars(
            select(VisualAsset).where(
                VisualAsset.source == VisualAssetSource.GENERATED_IMAGE,
                VisualAsset.entity_id == reference_fixture["character"].id,
            )
        )
    )
    assert approved.approved_candidate_index == 1
    assert len(generated_assets) == 3
    assert {asset.role for asset in generated_assets} == {
        VisualAssetRole.IDENTITY_FACE,
        VisualAssetRole.IDENTITY_HALF_BODY,
        VisualAssetRole.IDENTITY_FULL_BODY,
    }
    assert all(asset.status == ApprovalStatus.APPROVED for asset in generated_assets)
    assert session.get(VisualAsset, historical_id).status == ApprovalStatus.APPROVED
    assert all(
        run.review_status == ApprovalStatus.APPROVED
        for run in approved.runs
        if run.candidate_index == 1
    )
    assert all(
        run.review_status == ApprovalStatus.ARCHIVED
        for run in approved.runs
        if run.candidate_index == 2
    )
    assert all(
        image.promoted_asset_id is not None
        for run in approved.runs
        if run.candidate_index == 1
        for image in run.images
        if image.artifact_index == 1
    )
    assert all(
        image.promoted_asset_id is None
        for run in approved.runs
        for image in run.images
        if image.artifact_index > 1
    )

    repeated = reference_fixture["service"].approve_candidate_set(
        task_id=task.id,
        candidate_index=1,
    )
    assert repeated.approved_candidate_index == 1
    assert (
        session.scalar(
            select(func.count())
            .select_from(VisualAsset)
            .where(VisualAsset.source == VisualAssetSource.GENERATED_IMAGE)
        )
        == 3
    )
    assert (
        session.scalar(select(func.count()).select_from(CharacterReferenceImage)) == 12
    )
    assert session.scalar(select(func.count()).select_from(ComicPage)) == 0
    assert session.scalar(select(func.count()).select_from(ComicImage)) == 0
    assert session.scalar(select(func.count()).select_from(ImageSpec)) == 0


def test_rejects_unapproved_cross_project_style_and_non_txt2img_tool(
    reference_fixture,
) -> None:
    service = reference_fixture["service"]
    with pytest.raises(AppError) as tool_error:
        service.preview_prompts(
            character_id=reference_fixture["character"].id,
            tool_preset_id=reference_fixture["no_txt2img_tool"].id,
        )
    assert tool_error.value.code == "character_reference.txt2img_required"

    with pytest.raises(AppError) as draft_style_error:
        service.preview_prompts(
            character_id=reference_fixture["character"].id,
            tool_preset_id=reference_fixture["tool"].id,
            style_profile_id=reference_fixture["draft_style"].id,
        )
    assert draft_style_error.value.code == "character_reference.style_not_approved"

    other_project = ComicProject(title="Other")
    reference_fixture["session"].add(other_project)
    reference_fixture["session"].flush()
    other_style = StyleProfile(
        project_id=other_project.id,
        key="other",
        version=1,
        name="Other style",
        status=ApprovalStatus.APPROVED,
    )
    reference_fixture["session"].add(other_style)
    reference_fixture["session"].commit()
    with pytest.raises(AppError) as style_error:
        service.preview_prompts(
            character_id=reference_fixture["character"].id,
            tool_preset_id=reference_fixture["tool"].id,
            style_profile_id=other_style.id,
        )
    assert style_error.value.code == "character_reference.style_not_approved"


def test_openai_compatible_tool_uses_renderer_abstraction_without_network(
    reference_fixture, monkeypatch
) -> None:
    service = reference_fixture["service"]
    openai_tool = reference_fixture["openai_tool"]
    _, preview = service.preview_prompts(
        character_id=reference_fixture["character"].id,
        tool_preset_id=openai_tool.id,
    )
    task = service.create_task(
        character_id=reference_fixture["character"].id,
        tool_preset_id=openai_tool.id,
        style_profile_id=None,
        candidate_count=1,
        prompts=preview,
    )
    renderer = FakeRenderer()
    monkeypatch.setattr(
        service_module, "backend_for_preset", lambda *args, **kwargs: renderer
    )

    result = asyncio.run(service.run_task(task.id))
    payload = task_response(result).model_dump(mode="json")

    assert result.status == GenerationTaskStatus.SUCCEEDED
    assert len(renderer.submissions) == 3
    assert all(
        run.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE
        for run in result.runs
    )
    assert "test-secret-that-must-not-leak" not in json.dumps(payload)
    assert "error_message" not in payload
    assert all(
        "error_message" not in run
        for candidate in payload["candidates"]
        for run in candidate["roles"].values()
    )


def test_artifact_file_rejects_outside_root_and_missing_files(
    reference_fixture,
) -> None:
    service = reference_fixture["service"]
    task = _create_task(reference_fixture, candidate_count=1)
    outside_path = reference_fixture["tmp_path"] / "outside-output.png"
    outside_path.write_bytes(_png_bytes())
    image = service.repository.add_image(
        run_id=task.runs[0].id,
        artifact_index=1,
        local_path=str(outside_path),
        mime_type="image/png",
        sha256="b" * 64,
        width=32,
        height=40,
    )

    with pytest.raises(AppError) as outside_error:
        service.artifact_file(image.id)
    assert outside_error.value.code == "character_reference.image_missing"

    image.local_path = str(reference_fixture["tmp_path"] / "outputs" / "missing.png")
    reference_fixture["session"].commit()
    with pytest.raises(AppError) as missing_error:
        service.artifact_file(image.id)
    assert missing_error.value.code == "character_reference.image_missing"
