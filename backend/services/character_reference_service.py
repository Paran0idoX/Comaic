"""人物参考图三件套的任务创建、Renderer 执行、续跑和整套批准。"""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
import secrets

from PIL import Image, UnidentifiedImageError

from backend.i18n.errors import AppError, app_error_from_exception
from backend.models.comic import (
    CharacterReferenceGenerationRun,
    CharacterReferenceGenerationTask,
    CharacterReferenceImage,
    ImageGenerationToolPreset,
    OutlineCharacter,
    StyleProfile,
)
from backend.models.enums import (
    ApprovalStatus,
    GenerationMode,
    GenerationRunStatus,
    GenerationTaskStatus,
    ImageGenerationProvider,
    VisualAssetRole,
    VisualAssetSource,
    VisualEntityType,
    WorkflowCapability,
)
from backend.models.time import utc_now
from backend.repositories.character_reference_repository import (
    CharacterReferenceRepository,
)
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.character_reference_prompt_service import (
    REFERENCE_ROLES,
    CharacterReferencePromptService,
)
from backend.services.renderer_backends import backend_for_preset
from backend.services.reference_catalog import selected_task_roles
from backend.services.reference_inputs import frozen_preset, prepare_renderer_spec
from backend.services.task_runtime import RuntimeTaskType, running_task_registry
from backend.services.visual_bible_service import VisualBibleService
from backend.services.workflow_compiler import parse_capabilities
from backend.tools.comfyui_client import ComfyUIClient
from backend.utils.json_utils import canonical_json


IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}
MAX_PROMPT_LENGTH = 30_000


class CharacterReferenceService:
    """保持候选与视觉真值分离，只有整套人工批准后才创建 VisualAsset。"""

    def __init__(
        self,
        repository: CharacterReferenceRepository,
        *,
        comfy_client: ComfyUIClient | None = None,
        output_dir: str | Path = "outputs",
        asset_root: str | Path = "data/visual-assets",
        prompt_service: CharacterReferencePromptService | None = None,
    ) -> None:
        self.repository = repository
        self.comfy_client = comfy_client or ComfyUIClient(
            os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
        )
        self.output_dir = Path(output_dir)
        self.asset_root = Path(asset_root)
        self.prompt_service = prompt_service or CharacterReferencePromptService()

    def preview_prompts(
        self,
        *,
        character_id: int,
        tool_preset_id: int,
        style_profile_id: int | None = None,
    ) -> tuple[ImageGenerationToolPreset, dict[str, dict[str, str]]]:
        character = self._get_character(character_id)
        tool = self._get_tool(tool_preset_id)
        self._ensure_txt2img_tool(tool)
        style = self._get_approved_style(
            style_profile_id,
            project_id=character.outline_version.project_id,
        )
        return tool, self.prompt_service.compile(
            character=character,
            prompt_type=tool.prompt_type,
            style=style,
        )

    def create_task(
        self,
        *,
        character_id: int,
        tool_preset_id: int,
        style_profile_id: int | None,
        candidate_count: int,
        prompts: dict[str, dict[str, str]],
    ) -> CharacterReferenceGenerationTask:
        character = self._get_character(character_id)
        tool = self._get_tool(tool_preset_id)
        self._ensure_txt2img_tool(tool)
        self._get_approved_style(
            style_profile_id,
            project_id=character.outline_version.project_id,
        )
        if candidate_count < 1 or candidate_count > 4:
            raise AppError(
                "character_reference.candidate_count_invalid",
                status_code=422,
                debug_message=f"candidate_count out of range: {candidate_count}",
            )
        normalized_prompts = self._validate_prompts(prompts)
        seeds: list[int] = []
        while len(seeds) < candidate_count:
            seed = secrets.randbelow(2_147_483_647)
            if seed not in seeds:
                seeds.append(seed)
        return self.repository.create_task(
            project_id=character.outline_version.project_id,
            character_id=character.id,
            tool=tool,
            style_profile_id=style_profile_id,
            candidate_count=candidate_count,
            prompts=normalized_prompts,
            seeds=seeds,
        )

    def get_task(self, task_id: int) -> CharacterReferenceGenerationTask:
        task = self.repository.get_task(task_id)
        if task is None:
            raise AppError(
                "character_reference.task_not_found",
                status_code=404,
                debug_message=f"CharacterReferenceGenerationTask not found: {task_id}",
            )
        return task

    def list_character_tasks(
        self, character_id: int
    ) -> list[CharacterReferenceGenerationTask]:
        self._get_character(character_id)
        return self.repository.list_character_tasks(character_id)

    def list_outline_characters(
        self, outline_version_id: int
    ) -> list[OutlineCharacter]:
        if self.repository.get_outline_version(outline_version_id) is None:
            raise AppError(
                "outline.version_not_found",
                status_code=404,
                debug_message=f"OutlineVersion not found: {outline_version_id}",
            )
        return self.repository.list_outline_characters(outline_version_id)

    def list_project_outline_characters(
        self, project_id: int
    ) -> list[OutlineCharacter]:
        if self.repository.get_project(project_id) is None:
            raise AppError(
                "project.not_found",
                status_code=404,
                debug_message=f"ComicProject not found: {project_id}",
            )
        outline_version = self.repository.get_active_confirmed_outline_version(
            project_id
        )
        if outline_version is None:
            return []
        return self.repository.list_outline_characters(outline_version.id)

    def suspend_task(self, task_id: int) -> CharacterReferenceGenerationTask:
        task = self.get_task(task_id)
        if task.status not in {
            GenerationTaskStatus.PENDING,
            GenerationTaskStatus.RUNNING,
        }:
            raise AppError(
                "character_reference.task_state_invalid",
                status_code=409,
                debug_message=f"Cannot suspend task {task_id} from {task.status.value}",
            )
        return self.repository.update_task(
            task_id,
            status=GenerationTaskStatus.SUSPENDED,
            error_code=None,
            error_message=None,
            finished_at=utc_now(),
        )

    def prepare_continue(self, task_id: int) -> CharacterReferenceGenerationTask:
        task = self.get_task(task_id)
        if task.status not in {
            GenerationTaskStatus.FAILED,
            GenerationTaskStatus.SUSPENDED,
        }:
            raise AppError(
                "character_reference.task_state_invalid",
                status_code=409,
                debug_message=f"Cannot continue task {task_id} from {task.status.value}",
            )
        for run in task.runs:
            if self._primary_image(run) is not None:
                run.status = GenerationRunStatus.SUCCEEDED
                run.finished_at = utc_now()
            else:
                run.status = GenerationRunStatus.PENDING
                run.external_request_id = None
                run.error_code = None
                run.error_message = None
                run.finished_at = None
        task.status = GenerationTaskStatus.PENDING
        task.error_code = None
        task.error_message = None
        task.heartbeat_at = None
        task.finished_at = None
        self._set_progress(task)
        self.repository.session.commit()
        return self.get_task(task_id)

    async def run_task(
        self,
        task_id: int,
        *,
        poll_interval_seconds: float = 2.0,
        wait_timeout_seconds: float = 600.0,
    ) -> CharacterReferenceGenerationTask:
        task = self.get_task(task_id)
        if task.status in {
            GenerationTaskStatus.SUCCEEDED,
            GenerationTaskStatus.SUSPENDED,
        }:
            return task
        try:
            tool = self._get_tool(task.tool_preset_id)
            if task.runs:
                tool = frozen_preset(tool, json.loads(task.runs[0].applied_spec_json))
            self._ensure_txt2img_tool(tool)
            renderer = backend_for_preset(
                tool,
                default_comfy_client=self.comfy_client,
            )
        except Exception as exc:
            error = app_error_from_exception(exc)
            return self.repository.update_task(
                task.id,
                status=GenerationTaskStatus.FAILED,
                error_code=error.code,
                error_message=str(exc),
                heartbeat_at=None,
                finished_at=utc_now(),
            )
        task = self.repository.update_task(
            task.id,
            status=GenerationTaskStatus.RUNNING,
            error_code=None,
            error_message=None,
            heartbeat_at=utc_now(),
            finished_at=None,
        )
        running_task_registry.register(
            RuntimeTaskType.CHARACTER_REFERENCE_TASK,
            task.id,
        )
        try:
            for original_run in task.runs:
                current_task = self.get_task(task.id)
                if current_task.status == GenerationTaskStatus.SUSPENDED:
                    return current_task
                run = next(
                    item for item in current_task.runs if item.id == original_run.id
                )
                if self._primary_image(run) is not None:
                    continue
                try:
                    run = self.repository.update_run(
                        run.id,
                        status=GenerationRunStatus.RUNNING,
                        error_code=None,
                        error_message=None,
                        finished_at=None,
                    )
                    spec = json.loads(run.applied_spec_json)
                    # 先保存真实输入和工具参数，再进行外部提交；暂停继续复用此快照。
                    spec = prepare_renderer_spec(spec, tool, GenerationMode.PREVIEW)
                    spec.setdefault("render", {})["seed"] = run.seed
                    run = self.repository.update_run(run.id, applied_spec_json=canonical_json(spec))
                    submission = await renderer.submit(
                        spec=spec,
                        seed=run.seed,
                        mode=GenerationMode.PREVIEW,
                    )
                    run = self.repository.update_run(
                        run.id,
                        status=GenerationRunStatus.QUEUED,
                        external_request_id=submission.external_id,
                        seed_applied=submission.seed_applied,
                        workflow_json=(
                            canonical_json(submission.workflow)
                            if submission.workflow is not None
                            else None
                        ),
                        workflow_hash=submission.workflow_hash,
                        degradation_json=canonical_json(submission.degradations),
                        applied_spec_json=canonical_json(submission.applied_spec),
                    )
                    self.repository.update_run(
                        run.id,
                        status=GenerationRunStatus.RUNNING,
                    )
                    artifacts = await renderer.wait(
                        submission,
                        poll_interval_seconds=poll_interval_seconds,
                        timeout_seconds=wait_timeout_seconds,
                    )
                    if not artifacts:
                        raise AppError(
                            "character_reference.no_image",
                            status_code=502,
                            debug_message=(
                                f"Renderer returned no character reference image for run {run.id}"
                            ),
                        )
                    for artifact_index, artifact in enumerate(artifacts, start=1):
                        if any(
                            image.artifact_index == artifact_index
                            for image in run.images
                        ):
                            continue
                        metadata = self._image_metadata(artifact.content)
                        local_path = self._save_image_file(
                            task=current_task,
                            run=run,
                            request_id=submission.external_id,
                            artifact_index=artifact_index,
                            filename=artifact.filename,
                            content=artifact.content,
                            suffix=metadata[1],
                        )
                        self.repository.add_image(
                            run_id=run.id,
                            artifact_index=artifact_index,
                            local_path=str(local_path),
                            mime_type=metadata[0],
                            sha256=metadata[2],
                            width=metadata[3],
                            height=metadata[4],
                        )
                    self.repository.update_run(
                        run.id,
                        status=GenerationRunStatus.SUCCEEDED,
                        finished_at=utc_now(),
                    )
                except Exception as exc:  # noqa: BLE001 - 单张失败后继续生成其余候选
                    error = app_error_from_exception(exc)
                    self.repository.update_run(
                        run.id,
                        status=GenerationRunStatus.FAILED,
                        error_code=error.code,
                        error_message=str(exc),
                        finished_at=utc_now(),
                    )
                refreshed = self.get_task(task.id)
                self._set_progress(refreshed)
                self.repository.session.commit()

            task = self.get_task(task.id)
            failed = any(
                run.status != GenerationRunStatus.SUCCEEDED
                or self._primary_image(run) is None
                for run in task.runs
            )
            return self.repository.update_task(
                task.id,
                status=(
                    GenerationTaskStatus.FAILED
                    if failed
                    else GenerationTaskStatus.SUCCEEDED
                ),
                error_code=("character_reference.partial_failure" if failed else None),
                error_message=(
                    "One or more character reference runs failed." if failed else None
                ),
                heartbeat_at=None,
                finished_at=utc_now(),
            )
        except Exception as exc:
            error = app_error_from_exception(exc)
            return self.repository.update_task(
                task.id,
                status=GenerationTaskStatus.FAILED,
                error_code=error.code,
                error_message=str(exc),
                heartbeat_at=None,
                finished_at=utc_now(),
            )
        finally:
            running_task_registry.unregister(
                RuntimeTaskType.CHARACTER_REFERENCE_TASK,
                task.id,
            )

    def approve_candidate_set(
        self,
        *,
        task_id: int,
        candidate_index: int,
    ) -> CharacterReferenceGenerationTask:
        task = self.get_task(task_id)
        if task.approved_candidate_index is not None:
            if task.approved_candidate_index == candidate_index:
                return task
            raise AppError(
                "character_reference.already_approved",
                status_code=409,
                debug_message=(
                    f"Task {task_id} already approved candidate "
                    f"{task.approved_candidate_index}"
                ),
            )
        selected = [run for run in task.runs if run.candidate_index == candidate_index]
        selected_by_role = {run.role: run for run in selected}
        expected_roles = selected_task_roles(task)
        if set(selected_by_role) != set(expected_roles):
            raise AppError(
                "character_reference.candidate_incomplete",
                status_code=409,
                debug_message=f"Candidate set {candidate_index} is missing roles.",
            )
        primaries: dict[VisualAssetRole, CharacterReferenceImage] = {}
        for role in expected_roles:
            run = selected_by_role[role]
            primary = self._primary_image(run)
            if run.status != GenerationRunStatus.SUCCEEDED or primary is None:
                raise AppError(
                    "character_reference.candidate_incomplete",
                    status_code=409,
                    debug_message=(
                        f"Candidate set {candidate_index} role {role.value} is incomplete."
                    ),
                )
            path = Path(primary.local_path)
            if not path.is_file():
                raise AppError(
                    "character_reference.image_missing",
                    status_code=404,
                    debug_message=f"Character reference image missing: {primary.id}",
                )
            primaries[role] = primary

        session = self.repository.session
        visual_service = VisualBibleService(
            VisualBibleRepository(session),
            asset_root=self.asset_root,
        )
        try:
            for role, primary in primaries.items():
                if primary.promoted_asset_id is not None:
                    continue
                asset = visual_service.upload_asset(
                    project_id=task.project_id,
                    entity_type=task.entity_type,
                    entity_id=task.entity_id if task.entity_id is not None else task.outline_character_id,
                    entity_key=task.entity_key,
                    reference_subject_id=task.reference_subject_id,
                    outfit_variant_id=task.outfit_variant_id,
                    role=role,
                    content=Path(primary.local_path).read_bytes(),
                    source=VisualAssetSource.GENERATED_IMAGE,
                    approve=True,
                    commit=False,
                )
                primary.promoted_asset_id = asset.id
            for run in task.runs:
                run.review_status = (
                    ApprovalStatus.APPROVED
                    if run.candidate_index == candidate_index
                    else ApprovalStatus.ARCHIVED
                )
            task.approved_candidate_index = candidate_index
            session.commit()
        except Exception:
            session.rollback()
            raise
        return self.get_task(task_id)

    def artifact_file(self, image_id: int) -> tuple[Path, str | None]:
        image = self.repository.get_image(image_id)
        if image is None:
            raise AppError(
                "character_reference.image_not_found",
                status_code=404,
                debug_message=f"CharacterReferenceImage not found: {image_id}",
            )
        path = Path(image.local_path).resolve()
        root = self.output_dir.resolve()
        if root not in path.parents or not path.is_file():
            raise AppError(
                "character_reference.image_missing",
                status_code=404,
                debug_message=f"Character reference image file missing: {image_id}",
            )
        return path, image.mime_type

    def _get_character(self, character_id: int) -> OutlineCharacter:
        character = self.repository.get_character(character_id)
        if character is None:
            raise AppError(
                "character_reference.character_not_found",
                status_code=404,
                debug_message=f"OutlineCharacter not found: {character_id}",
            )
        if character.outline_version.confirmed_at is None:
            raise AppError(
                "outline.version_not_confirmed",
                status_code=409,
                debug_message=(
                    f"OutlineVersion is not confirmed: {character.outline_version_id}"
                ),
            )
        return character

    def _get_tool(self, tool_id: int) -> ImageGenerationToolPreset:
        tool = self.repository.get_tool(tool_id)
        if tool is None:
            raise AppError(
                "character_reference.tool_not_found",
                status_code=404,
                debug_message=f"ImageGenerationToolPreset not found: {tool_id}",
            )
        return tool

    def _get_approved_style(
        self,
        style_id: int | None,
        *,
        project_id: int,
    ) -> StyleProfile | None:
        if style_id is None:
            return None
        style = self.repository.get_style(style_id)
        if (
            style is None
            or style.project_id != project_id
            or style.status != ApprovalStatus.APPROVED
        ):
            raise AppError(
                "character_reference.style_not_approved",
                status_code=409,
                debug_message=(
                    f"Approved StyleProfile not found for project {project_id}: {style_id}"
                ),
            )
        return style

    @staticmethod
    def _ensure_txt2img_tool(tool: ImageGenerationToolPreset) -> None:
        capabilities = parse_capabilities(tool.capabilities_json)
        if WorkflowCapability.TXT2IMG not in capabilities.features:
            raise AppError(
                "character_reference.txt2img_required",
                status_code=409,
                debug_message=f"Tool {tool.id} does not declare txt2img.",
            )
        if tool.provider == ImageGenerationProvider.COMFYUI and not tool.workflow_json:
            raise AppError(
                "character_reference.tool_invalid",
                status_code=409,
                debug_message=f"ComfyUI tool {tool.id} has no workflow JSON.",
            )
        if tool.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE and (
            not tool.api_base_url or not tool.model
        ):
            raise AppError(
                "character_reference.tool_invalid",
                status_code=409,
                debug_message=f"OpenAI Images compatible tool {tool.id} is incomplete.",
            )

    @staticmethod
    def _validate_prompts(
        prompts: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        expected = {role.value for role in REFERENCE_ROLES}
        if set(prompts) != expected:
            raise AppError(
                "character_reference.prompts_invalid",
                status_code=422,
                debug_message=f"Prompt roles must be {sorted(expected)}.",
            )
        result: dict[str, dict[str, str]] = {}
        for role in expected:
            item = prompts.get(role) or {}
            # 校验空白时使用 strip，但快照必须保留用户提交的精确文本。
            positive = str(item.get("positive") or "")
            negative = str(item.get("negative") or "")
            if not positive.strip() or len(positive) > MAX_PROMPT_LENGTH:
                raise AppError(
                    "character_reference.prompts_invalid",
                    status_code=422,
                    debug_message=f"Invalid positive prompt for {role}.",
                )
            if len(negative) > MAX_PROMPT_LENGTH:
                raise AppError(
                    "character_reference.prompts_invalid",
                    status_code=422,
                    debug_message=f"Invalid negative prompt for {role}.",
                )
            result[role] = {"positive": positive, "negative": negative}
        return result

    @staticmethod
    def _primary_image(
        run: CharacterReferenceGenerationRun,
    ) -> CharacterReferenceImage | None:
        return next(
            (image for image in run.images if image.artifact_index == 1),
            None,
        )

    @staticmethod
    def _set_progress(task: CharacterReferenceGenerationTask) -> None:
        task.progress_json = canonical_json(
            {
                "completed": sum(
                    run.status == GenerationRunStatus.SUCCEEDED and bool(run.images)
                    for run in task.runs
                ),
                "failed": sum(
                    run.status == GenerationRunStatus.FAILED for run in task.runs
                ),
                "total": len(task.runs),
            }
        )

    @staticmethod
    def _image_metadata(
        content: bytes,
    ) -> tuple[str, str, str, int | None, int | None]:
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AppError(
                "character_reference.invalid_image",
                status_code=502,
                debug_message="Renderer returned an invalid image.",
            ) from exc
        if image_format not in IMAGE_FORMATS:
            raise AppError(
                "character_reference.invalid_image",
                status_code=502,
                debug_message=f"Unsupported renderer image format: {image_format}",
            )
        mime_type, suffix = IMAGE_FORMATS[image_format]
        return (
            mime_type,
            suffix,
            hashlib.sha256(content).hexdigest(),
            width,
            height,
        )

    def _save_image_file(
        self,
        *,
        task: CharacterReferenceGenerationTask,
        run: CharacterReferenceGenerationRun,
        request_id: str,
        artifact_index: int,
        filename: str,
        content: bytes,
        suffix: str,
    ) -> Path:
        directory = (
            self.output_dir
            / f"project_{task.project_id}"
            / "character_references"
            / f"character_{task.outline_character_id}"
            / f"task_{task.id}"
            / f"candidate_{run.candidate_index}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        safe_request = "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in request_id
        )
        original_suffix = Path(filename).suffix.lower()
        chosen_suffix = (
            original_suffix
            if original_suffix in {".png", ".jpg", ".jpeg", ".webp"}
            else suffix
        )
        path = directory / (
            f"{run.role.value}_{safe_request}_{artifact_index}{chosen_suffix}"
        )
        path.write_bytes(content)
        return path
