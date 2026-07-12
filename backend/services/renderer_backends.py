import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

import requests

from backend.i18n.errors import AppError
from backend.models.comic import ImageGenerationToolPreset
from backend.models.enums import GenerationMode, ImageGenerationProvider
from backend.services.workflow_compiler import (
    WorkflowCompiler,
    parse_bindings,
    parse_capabilities,
)
from backend.tools.comfyui_client import ComfyUIClient
from backend.utils.json_utils import canonical_hash


@dataclass(frozen=True)
class RendererSubmission:
    external_id: str
    applied_spec: dict[str, Any]
    workflow: dict[str, Any] | None
    workflow_hash: str | None
    degradations: list[dict[str, str]]
    seed_applied: bool
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedArtifact:
    content: bytes
    filename: str


class RendererBackend(Protocol):
    async def submit(
        self,
        *,
        spec: dict[str, Any],
        seed: int,
        mode: GenerationMode,
    ) -> RendererSubmission: ...

    async def wait(
        self,
        submission: RendererSubmission,
        *,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> list[RenderedArtifact]: ...


class ComfyUIBackend:
    """ComfyUI Renderer：上传本地条件资产、编译 binding、排队并下载结果。"""

    def __init__(self, preset: ImageGenerationToolPreset, default_client: ComfyUIClient):
        self.preset = preset
        self.client = (
            ComfyUIClient(preset.comfy_base_url)
            if preset.comfy_base_url
            else default_client
        )
        self.compiler = WorkflowCompiler()

    async def submit(
        self,
        *,
        spec: dict[str, Any],
        seed: int,
        mode: GenerationMode,
    ) -> RendererSubmission:
        if not self.preset.workflow_json:
            raise ValueError("Workflow JSON is required for ComfyUI image generation.")
        applied_spec = deepcopy(spec)
        await self._resolve_assets(applied_spec, {})

        workflow = json.loads(self.preset.workflow_json)
        compiled = self.compiler.compile(
            workflow=workflow,
            spec=applied_spec,
            seed=seed,
            capabilities=parse_capabilities(self.preset.capabilities_json),
            bindings=parse_bindings(self.preset.bindings_json),
            mode=mode,
        )
        external_id = await asyncio.to_thread(
            self.client.queue_prompt,
            compiled.workflow,
        )
        return RendererSubmission(
            external_id=external_id,
            applied_spec=compiled.applied_spec,
            workflow=compiled.workflow,
            workflow_hash=canonical_hash(compiled.workflow),
            degradations=compiled.degradations,
            seed_applied=any(
                item.source == "render.seed"
                for item in parse_bindings(self.preset.bindings_json).bindings
            ),
        )

    async def wait(
        self,
        submission: RendererSubmission,
        *,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> list[RenderedArtifact]:
        deadline = monotonic() + max(0.01, timeout_seconds)
        while True:
            history = await asyncio.to_thread(
                self.client.get_history,
                submission.external_id,
            )
            images = self.client.extract_output_images(history, submission.external_id)
            if images:
                break
            execution_error = self.client.extract_execution_error(
                history,
                submission.external_id,
            )
            if execution_error:
                raise AppError(
                    "image_generation.comfyui_execution_failed",
                    status_code=502,
                    debug_message=(
                        f"ComfyUI prompt {submission.external_id} failed: "
                        f"{execution_error}"
                    ),
                )
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AppError(
                    "image_generation.comfyui_timeout",
                    status_code=504,
                    debug_message=(
                        f"ComfyUI prompt {submission.external_id} did not finish within "
                        f"{timeout_seconds:g} seconds."
                    ),
                )
            await asyncio.sleep(min(poll_interval_seconds, remaining))
        result: list[RenderedArtifact] = []
        for image in images:
            content = await asyncio.to_thread(
                self.client.download_view_image,
                filename=image["filename"],
                subfolder=image["subfolder"],
                image_type=image["type"],
            )
            result.append(RenderedArtifact(content=content, filename=image["filename"]))
        return result

    async def _resolve_assets(self, value: Any, uploaded: dict[str, str]) -> None:
        """把 ImageSpec 中本地文件替换成 ComfyUI input 名称，原始 spec 保持不变。"""

        if isinstance(value, list):
            for item in value:
                await self._resolve_assets(item, uploaded)
            return
        if not isinstance(value, dict):
            return
        if value.get("storage_kind") == "local_file" and value.get("local_path"):
            path = Path(str(value["local_path"]))
            if not path.is_file():
                raise ValueError(f"Visual asset file not found: {path}")
            digest = str(value.get("sha256") or canonical_hash({"path": str(path)}))
            remote_name = uploaded.get(digest)
            if remote_name is None:
                remote_name = await asyncio.to_thread(
                    self.client.upload_image,
                    content=path.read_bytes(),
                    filename=f"{digest}{path.suffix or '.png'}",
                    subfolder=f"comaic/{digest[:2]}",
                    overwrite=False,
                )
                uploaded[digest] = remote_name
            value["renderer_name"] = remote_name
        elif value.get("storage_kind") == "renderer_locator" and value.get(
            "renderer_locator"
        ):
            value["renderer_name"] = value["renderer_locator"]
        for child in value.values():
            await self._resolve_assets(child, uploaded)


class OpenAIImagesBackend:
    """OpenAI Images 兼容 Renderer；P0 只支持 Prompt-only 规格。"""

    def __init__(self, preset: ImageGenerationToolPreset):
        self.preset = preset

    async def submit(
        self,
        *,
        spec: dict[str, Any],
        seed: int,
        mode: GenerationMode,
    ) -> RendererSubmission:
        required = set(spec.get("required_capabilities", []))
        missing = sorted(required - {"txt2img"})
        degradations = [
            {
                "code": "workflow.capability_missing",
                "message": f"OpenAI Images compatible backend cannot apply {item}.",
            }
            for item in missing
        ]
        if not self.preset.seed_field_name:
            degradations.append(
                {
                    "code": "workflow.seed_not_applied",
                    "message": "Image API does not expose a seed field.",
                }
            )
        if (spec.get("prompt") or {}).get("negative") and not self.preset.negative_prompt_field_name:
            degradations.append(
                {
                    "code": "workflow.condition_unbound",
                    "message": "Image API does not expose a negative prompt field.",
                }
            )
        if mode == GenerationMode.FINAL and degradations:
            raise ValueError(
                "Final prompt-only backend cannot satisfy ImageSpec: "
                + ", ".join(item["message"] for item in degradations)
            )
        payload = await asyncio.to_thread(self._request, spec=spec, seed=seed)
        external_id = str(payload.get("id") or f"image-api-{uuid4().hex}")
        return RendererSubmission(
            external_id=external_id,
            applied_spec=deepcopy(spec),
            workflow=None,
            workflow_hash=None,
            degradations=degradations,
            seed_applied=bool(self.preset.seed_field_name),
            context={"response": payload},
        )

    async def wait(
        self,
        submission: RendererSubmission,
        *,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> list[RenderedArtifact]:
        del poll_interval_seconds, timeout_seconds
        image_items = submission.context.get("response", {}).get("data")
        if not isinstance(image_items, list) or not image_items:
            raise ValueError("Image generation API returned no images.")
        result: list[RenderedArtifact] = []
        for index, item in enumerate(image_items, start=1):
            content = await asyncio.to_thread(self._content, item)
            result.append(
                RenderedArtifact(
                    content=content,
                    filename=f"{submission.external_id}_{index}.png",
                )
            )
        return result

    def _request(self, *, spec: dict[str, Any], seed: int) -> dict[str, Any]:
        if not self.preset.api_base_url or not self.preset.model:
            raise ValueError("Image API base URL and model are required.")
        body: dict[str, Any] = {
            "model": self.preset.model,
            "prompt": spec["prompt"]["positive"],
            "n": 1,
        }
        if self.preset.size:
            body["size"] = self.preset.size
        if self.preset.response_format:
            body["response_format"] = self.preset.response_format
        if self.preset.extra_body_json:
            extra = json.loads(self.preset.extra_body_json)
            if not isinstance(extra, dict):
                raise ValueError("Extra body JSON must be an object.")
            body.update(extra)
        if self.preset.seed_field_name:
            body[self.preset.seed_field_name] = seed
        negative = spec.get("prompt", {}).get("negative")
        if negative and self.preset.negative_prompt_field_name:
            body[self.preset.negative_prompt_field_name] = negative
        headers = {"Content-Type": "application/json"}
        if self.preset.api_key:
            headers["Authorization"] = f"Bearer {self.preset.api_key}"
        endpoint = (self.preset.endpoint_path or "/images/generations").lstrip("/")
        response = requests.post(
            f"{self.preset.api_base_url.rstrip('/')}/{endpoint}",
            json=body,
            headers=headers,
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Image generation API response must be a JSON object.")
        return payload

    @staticmethod
    def _content(item: Any) -> bytes:
        if not isinstance(item, dict):
            raise ValueError("Image generation API image item must be an object.")
        if isinstance(item.get("b64_json"), str) and item["b64_json"].strip():
            return base64.b64decode(item["b64_json"])
        if isinstance(item.get("url"), str) and item["url"].strip():
            response = requests.get(item["url"], timeout=180)
            response.raise_for_status()
            return response.content
        raise ValueError("Image generation API item contains neither b64_json nor url.")


def backend_for_preset(
    preset: ImageGenerationToolPreset,
    *,
    default_comfy_client: ComfyUIClient,
) -> RendererBackend:
    if preset.provider == ImageGenerationProvider.COMFYUI:
        return ComfyUIBackend(preset, default_comfy_client)
    if preset.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE:
        return OpenAIImagesBackend(preset)
    raise ValueError(f"Unsupported image generation provider: {preset.provider.value}")
