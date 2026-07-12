from types import SimpleNamespace

import pytest

from backend.models.enums import GenerationMode
from backend.services.renderer_backends import ComfyUIBackend, OpenAIImagesBackend


class FakeComfyClient:
    def __init__(self):
        self.uploads = []

    def upload_image(self, **kwargs):
        self.uploads.append(kwargs)
        return f"{kwargs['subfolder']}/{kwargs['filename']}"


@pytest.mark.asyncio
async def test_comfy_asset_upload_is_deduplicated_by_hash(tmp_path, monkeypatch) -> None:
    async def direct_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("backend.services.renderer_backends.asyncio.to_thread", direct_to_thread)
    image = tmp_path / "reference.png"
    image.write_bytes(b"test-image")
    client = FakeComfyClient()
    backend = ComfyUIBackend(SimpleNamespace(comfy_base_url=None), client)
    first = {
        "storage_kind": "local_file",
        "local_path": str(image),
        "sha256": "a" * 64,
    }
    second = dict(first)
    payload = {"identity_assets": [first], "identity": {"references": [second]}}

    await backend._resolve_assets(payload, {})

    assert len(client.uploads) == 1
    assert first["renderer_name"] == second["renderer_name"]


@pytest.mark.asyncio
async def test_prompt_only_backend_rejects_final_reference_requirements_without_request() -> None:
    backend = OpenAIImagesBackend(
        SimpleNamespace(
            api_base_url="https://unused.invalid",
            model="unused",
            seed_field_name=None,
        )
    )
    with pytest.raises(ValueError, match="prompt-only backend"):
        await backend.submit(
            spec={
                "prompt": {"positive": "test", "negative": ""},
                "required_capabilities": ["txt2img", "reference_image"],
            },
            seed=1,
            mode=GenerationMode.FINAL,
        )
