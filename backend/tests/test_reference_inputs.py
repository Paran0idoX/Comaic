"""使用本地原图和模拟HTTP校验发送数组，不调用真实生图服务。"""
import asyncio
import base64
import json

import pytest
from backend.i18n.errors import AppError

from backend.models.comic import ImageGenerationToolPreset
from backend.models.enums import GenerationMode, ImageGenerationProvider, ImagePromptType
from backend.services.reference_inputs import prepare_renderer_spec
from backend.services.renderer_backends import ComfyUIBackend, OpenAIImagesBackend


def _spec(tmp_path, count=3):
    items = []
    for index in range(count):
        path = tmp_path / f"original-{index}.png"
        path.write_bytes(f"original image {index}".encode())
        items.append({"asset_id": index + 1, "id": index + 1, "role": "identity_full_body" if index < 2 else "scene_master",
                      "version": 1, "storage_kind": "local_file", "local_path": str(path), "mime_type": "image/png",
                      "owner": {"category": "character" if index < 2 else "scene", "key": "alice" if index < 2 else "room", "name": "Alice" if index < 2 else "Room"},
                      "purpose": "identity" if index == 1 else "appearance", "is_primary": index != 1, "priority": index, "reason": "Same owner"})
    return {"prompt": {"positive": "page camera back", "negative": ""}, "subjects": [], "scene": {},
            "required_capabilities": ["txt2img", "reference_image"], "reference_plan": {"items": items}}


def _preset(transport="json_data_url", capacity=3, comfy=False):
    return ImageGenerationToolPreset(name="mock", provider=ImageGenerationProvider.COMFYUI if comfy else ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE,
                                    prompt_type=ImagePromptType.NATURAL_LANGUAGE, api_base_url="https://mock.invalid/v1", model="mock-model",
                                    endpoint_path="/images/generations", seed_field_name="seed", negative_prompt_field_name="negative",
                                    capabilities_json=json.dumps({"features": ["txt2img", "reference_image"], "reference_images": {"max_images": capacity, "transport": "none" if comfy else transport, "label_format": "image_N", "edit_endpoint_path": "/images/edits", "image_field_name": "images"}}),
                                    bindings_json=json.dumps({"bindings": [{"source": "prompt.positive", "node_id": "1", "input_name": "text"}, {"source": "render.seed", "node_id": "2", "input_name": "seed"}], "reference_slots": [{"node_id": str(index + 3), "input_name": "image", "disconnect": [{"node_id": "10", "input_name": f"image{index + 1}"}]} for index in range(3)]}),
                                    workflow_json=json.dumps({"1": {"inputs": {"text": "old"}}, "2": {"inputs": {"seed": 0}}, **{str(index + 3): {"inputs": {"image": "example.png"}} for index in range(3)}, "10": {"inputs": {f"image{index + 1}": [str(index + 3), 0] for index in range(3)}}}))


def test_primary_capacity_before_auxiliary_and_freeze(tmp_path):
    preset = _preset(capacity=2)
    spec = _spec(tmp_path)
    prepared = prepare_renderer_spec(spec, preset, GenerationMode.FINAL)
    assert [item["asset_id"] for item in prepared["reference_inputs"]["items"]] == [1, 3]
    assert prepared["reference_inputs"]["omitted"][0]["asset_id"] == 2
    assert "image 1: Alice" in prepared["prompt"]["positive"]
    assert "image 2: Room" in prepared["prompt"]["positive"]
    preset.capabilities_json = _preset(capacity=0).capabilities_json
    assert prepare_renderer_spec(prepared, preset, GenerationMode.FINAL) == prepared
    assert "reference_inputs" not in spec


@pytest.mark.parametrize("transport", ["multipart", "json_data_url"])
def test_external_api_sends_each_original_in_prompt_order(tmp_path, monkeypatch, transport):
    received = []
    def post(url, **kwargs):
        received.append((url, kwargs))
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"id": "mock-request", "data": [{"b64_json": base64.b64encode(b"output").decode()}]}
        return Response()
    monkeypatch.setattr("backend.services.renderer_backends.requests.post", post)
    submission = asyncio.run(OpenAIImagesBackend(_preset(transport)).submit(spec=_spec(tmp_path), seed=42, mode=GenerationMode.FINAL))
    url, kwargs = received[0]
    assert url.endswith("/images/edits")
    assert [item["order"] for item in submission.applied_spec["reference_inputs"]["items"]] == [1, 2, 3]
    if transport == "multipart":
        assert [file[1][1] for file in kwargs["files"]] == [f"original image {index}".encode() for index in range(3)]
        assert kwargs["data"]["seed"] == "42"
        assert "Content-Type" not in kwargs["headers"]
        prompt = kwargs["data"]["prompt"]
    else:
        assert [base64.b64decode(value.split(",")[1]) for value in kwargs["json"]["images"]] == [f"original image {index}".encode() for index in range(3)]
        prompt = kwargs["json"]["prompt"]
    assert "image 3: Room" in prompt


@pytest.mark.parametrize("failure", ["capacity", "missing_file", "locator", "canvas"])
def test_strict_failure_makes_zero_external_requests(tmp_path, monkeypatch, failure):
    calls = []
    monkeypatch.setattr("backend.services.renderer_backends.requests.post", lambda *args, **kwargs: calls.append(args))
    preset, spec = _preset(capacity=1 if failure == "capacity" else 3), _spec(tmp_path)
    if failure == "missing_file":
        spec["reference_plan"]["items"][0]["local_path"] = str(tmp_path / "missing.png")
    elif failure == "locator":
        spec["reference_plan"]["items"][0].update(local_path=None, renderer_locator="legacy.png")
    elif failure == "canvas":
        config = json.loads(preset.capabilities_json)
        config["reference_images"]["requires_canvas"] = True
        preset.capabilities_json = json.dumps(config)
    with pytest.raises(AppError):
        asyncio.run(OpenAIImagesBackend(preset).submit(spec=spec, seed=42, mode=GenerationMode.FINAL))
    assert not calls


def test_comfy_order_upload_and_disconnect_empty_slots(tmp_path):
    class Client:
        def __init__(self): self.uploads, self.queued = [], []
        def upload_image(self, **kwargs):
            self.uploads.append(kwargs["content"])
            return f"uploaded-{len(self.uploads)}.png"
        def queue_prompt(self, workflow):
            self.queued.append(workflow)
            return "mock-prompt"
    client = Client()
    spec = _spec(tmp_path, count=1)
    submission = asyncio.run(ComfyUIBackend(_preset(comfy=True), client).submit(spec=spec, seed=42, mode=GenerationMode.FINAL))
    assert client.uploads == [b"original image 0"]
    assert submission.workflow["3"]["inputs"]["image"] == "uploaded-1.png"
    assert "4" not in submission.workflow and "5" not in submission.workflow
    assert submission.workflow["10"]["inputs"] == {"image1": ["3", 0]}


def test_historical_spec_has_no_inferred_manifest(tmp_path):
    assert "reference_inputs" not in prepare_renderer_spec({"prompt": {"positive": "old"}}, _preset(), GenerationMode.PREVIEW)
