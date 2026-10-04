"""使用本地原图和模拟HTTP校验发送数组，不调用真实生图服务。"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path

import pytest
from backend.i18n.errors import AppError

from backend.models.comic import ImageGenerationToolPreset
from backend.models.enums import GenerationMode, ImageGenerationProvider, ImagePromptType
from backend.services.reference_inputs import prepare_renderer_spec, validate_renderer_spec
from backend.services.reference_selection_service import ReferenceSelectionService
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


@pytest.mark.parametrize("broken", ["missing", "changed"])
def test_optional_references_still_reject_invalid_transmitted_files(tmp_path, broken):
    spec = _spec(tmp_path)
    item = spec["reference_plan"]["items"][0]
    path = Path(item["local_path"])
    item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if broken == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed original")
    with pytest.raises(AppError) as caught:
        prepare_renderer_spec(spec, _preset(), GenerationMode.PREVIEW)
    assert caught.value.code == ("reference.input.file_unavailable" if broken == "missing" else "reference.input.file_changed")


def test_tool_without_references_uses_text_and_reports_omissions(tmp_path):
    prepared = prepare_renderer_spec(_spec(tmp_path), _preset(capacity=0), GenerationMode.PREVIEW)
    assert prepared["reference_inputs"]["items"] == []
    assert len(prepared["reference_inputs"]["omitted"]) == 3
    assert prepared["reference_inputs"]["degradations"]
    assert "reference_image" not in prepared["required_capabilities"]


def test_optional_reference_precheck_blocks_invalid_api_configuration(tmp_path):
    preset = _preset()
    prepared = prepare_renderer_spec(_spec(tmp_path), preset, GenerationMode.PREVIEW)
    preset.api_base_url = None
    prepared.pop("renderer_config")
    with pytest.raises(AppError, match="reference.input.configuration_invalid"):
        validate_renderer_spec(prepared, preset, GenerationMode.PREVIEW)


def test_primary_capacity_before_auxiliary_and_freeze(tmp_path):
    preset = _preset(capacity=2)
    spec = _spec(tmp_path)
    prepared = prepare_renderer_spec(spec, preset, GenerationMode.FINAL)
    assert [item["asset_id"] for item in prepared["reference_inputs"]["items"]] == [1, 3]
    assert prepared["reference_inputs"]["omitted"][0]["asset_id"] == 2
    assert "<image1>: Alice" in prepared["prompt"]["positive"]
    assert "<image2>: Room" in prepared["prompt"]["positive"]
    preset.capabilities_json = _preset(capacity=0).capabilities_json
    assert prepare_renderer_spec(prepared, preset, GenerationMode.FINAL) == prepared
    assert "reference_inputs" not in spec


@pytest.mark.parametrize("capacity", [5, 6])
def test_three_characters_keep_all_primaries_before_auxiliary_and_renumber(tmp_path, capacity):
    """三人同框先保人物、场景和物品主图，剩余容量才给同角色的辅助图。"""
    def asset(asset_id, role):
        path = tmp_path / f"reference-{asset_id}.png"
        content = f"original independent reference {asset_id}".encode()
        path.write_bytes(content)
        return {"id": asset_id, "role": role, "version": 1, "storage_kind": "local_file",
                "local_path": str(path), "mime_type": "image/png", "sha256": hashlib.sha256(content).hexdigest()}

    snapshot = {"characters": [
        {"character_key": key, "outline_character_id": index, "name": key.title(),
         "identity_assets": [asset(index * 10 + 1, "identity_full_body"), asset(index * 10 + 2, "identity_face")],
         "outfit": {"variant_id": None, "assets": []}}
        for index, key in enumerate(["alice", "bob", "carol"], 1)
    ], "scene": {"scene_key": "room", "assets": [asset(90, "scene_master")]},
       "prop_catalog": [{"key": "compass", "name": "Compass", "assets": [asset(91, "prop_reference")]}]}
    plan = {"camera": {"shot_type": "wide"}, "subjects": [
        {"character_key": key, "reference_view": "front", "reference_framing": "full_body", "depth_order": depth}
        for depth, key in enumerate(["bob", "alice", "carol"], 1)
    ], "scene": {"background_visible": True, "visible_prop_keys": ["compass"]}}
    references = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=plan)
    preset = _preset(comfy=True, capacity=capacity)
    workflows = Path(__file__).resolve().parents[2] / "workflows"
    preset.workflow_json = (workflows / "qwen21_reference_api.json").read_text(encoding="utf-8")
    preset.bindings_json = (workflows / "qwen21_reference_bindings.json").read_text(encoding="utf-8")
    spec = {"prompt": {"positive": "Three distinct characters in the room.", "negative": ""},
            "reference_plan": references, "subjects": [], "scene": {},
            "required_capabilities": ["txt2img", "reference_image"]}

    from backend.tests.test_reference_batch_snapshot import FakeComfyClient
    client = FakeComfyClient()
    result = asyncio.run(ComfyUIBackend(preset, client).submit(spec=spec, seed=42, mode=GenerationMode.FINAL))
    expected = [21, 11, 31, 22, 90, 91] if capacity == 6 else [21, 11, 31, 90, 91]
    selected = result.applied_spec["reference_inputs"]["items"]
    assert [item["asset_id"] for item in selected] == expected
    assert [item["label"] for item in selected] == [f"<image{index}>" for index in range(1, capacity + 1)]
    assert [upload["content"] for upload in client.uploads] == [f"original independent reference {asset_id}".encode() for asset_id in expected]
    prompt = result.workflow["4"]["inputs"]["prompt"]
    assert "\n" not in prompt
    assert all(f"<image{index}>:" in prompt for index in range(1, capacity + 1))
    assert f"<image{capacity + 1}>" not in prompt
    assert "same character or object, not extra people or objects" in prompt
    assert prompt.count("owner character:bob") == (2 if capacity == 6 else 1)
    assert prompt.count("owner character:alice") == prompt.count("owner character:carol") == 1
    omitted = result.applied_spec["reference_inputs"]["omitted"]
    assert {item["asset_id"] for item in omitted if item["reason_code"] == "reference.capacity_exceeded"} == ({12, 32} if capacity == 6 else {12, 22, 32})
    assert all(item["is_primary"] for item in selected if item["asset_id"] != 22)
    prepared_again = prepare_renderer_spec(result.applied_spec, preset, GenerationMode.FINAL)
    assert prepared_again["prompt"]["positive"] == prompt
    assert all(str(index + 10) not in result.workflow for index in range(capacity + 1, 7))


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
    assert "<image3>: Room" in prompt


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


@pytest.mark.parametrize("explicit_size", [False, True])
def test_comic_dimensions_use_bound_workflow_defaults_and_survive_resume(tmp_path, explicit_size):
    """漫画页面缺宽高时使用工具默认值，参考图指定尺寸优先，续跑不读取新工具尺寸。"""
    workflows = Path(__file__).resolve().parents[2] / "workflows"
    preset = _preset(comfy=True)
    preset.workflow_json = (workflows / "qwen21_euler_a_beta57_api.json").read_text(encoding="utf-8")
    preset.bindings_json = (workflows / "qwen21_euler_a_beta57_bindings.json").read_text(encoding="utf-8")
    preset.capabilities_json = (workflows / "qwen21_reference_capabilities.json").read_text(encoding="utf-8")
    spec = _spec(tmp_path, count=0)
    if explicit_size:
        spec["render"] = {"width": 512, "height": 768}
    prepared = prepare_renderer_spec(spec, preset, GenerationMode.PREVIEW)
    expected = {"width": 512, "height": 768} if explicit_size else {"width": 1024, "height": 1536}
    assert prepared["render"] == expected
    assert prepared["prompt"] == spec["prompt"]
    validate_renderer_spec(prepared, preset, GenerationMode.PREVIEW)
    workflow = json.loads(preset.workflow_json)
    workflow["8"]["inputs"].update(width=256, height=256)
    preset.workflow_json = json.dumps(workflow)
    resumed = prepare_renderer_spec(prepared, preset, GenerationMode.PREVIEW)
    assert resumed == prepared
    validate_renderer_spec(resumed, preset, GenerationMode.PREVIEW)
    if not explicit_size:
        assert "render" not in spec


@pytest.mark.parametrize("invalid", [None, "1024", True, ["9", 0], 0])
def test_invalid_bound_dimension_is_rejected_before_submission(tmp_path, invalid):
    preset = _preset(comfy=True)
    workflow = json.loads(preset.workflow_json)
    workflow["2"]["inputs"]["width"] = invalid
    preset.workflow_json = json.dumps(workflow)
    bindings = json.loads(preset.bindings_json)
    bindings["bindings"].append({"source": "render.width", "node_id": "2", "input_name": "width"})
    preset.bindings_json = json.dumps(bindings)
    with pytest.raises(AppError) as exc:
        prepare_renderer_spec(_spec(tmp_path), preset, GenerationMode.PREVIEW)
    assert exc.value.code == "reference.input.configuration_invalid"


@pytest.mark.parametrize("expression", ["tag", "natural_language", "hybrid"])
def test_qwen_reference_identity_projection_preserves_action_clothing_and_truth(tmp_path, expression):
    """传图只增强身份；三类表达仍保留固定描述、造型、本页状态和未传人物描述。"""
    spec = _spec(tmp_path)
    spec.update(prompt_type=expression, shot_plan={"render_text": False}, subjects=[
        {"character_key": "alice", "name": "Alice", "identity": {"appearance": "UNIQUE_IDENTITY_DESCRIPTION"},
         "hairstyle": "UNIQUE_HAIR_DESCRIPTION", "outfit": {"garment_components": ["CONFIRMED_RED_COAT"]},
         "shot": {"action": "OPEN_THE_DOOR", "gaze": "LOOK_AT_BOB", "pose": "standing",
                  "visible_state": "SOAKED_COAT_AND_WRIST_WOUND"}},
        {"character_key": "bob", "name": "Bob", "identity": {"appearance": "BOB_TEXT_ONLY_IDENTITY"},
         "shot": {"action": "READ_THE_MAP"}},
    ])
    prepared = prepare_renderer_spec(spec, _preset(capacity=2), GenerationMode.PREVIEW)
    prompt = prepared["prompt"]["positive"]
    assert "UNIQUE_IDENTITY_DESCRIPTION" in prompt
    assert "UNIQUE_HAIR_DESCRIPTION" in prompt
    assert "BOB_TEXT_ONLY_IDENTITY" in prompt
    assert all(value in prompt for value in ["CONFIRMED_RED_COAT", "OPEN_THE_DOOR", "LOOK_AT_BOB", "READ_THE_MAP", "SOAKED_COAT_AND_WRIST_WOUND"])
    assert "alongside the fixed appearance description" in prompt
    assert "<image1>" in prompt and "<image2>" in prompt and "<image3>" not in prompt
    assert "<image1>: Alice" in prompt and "<image2>: Room" in prompt
    assert "UNIQUE_IDENTITY_DESCRIPTION" in prepared["subjects"][0]["identity"]["appearance"]
    assert prepared["reference_inputs"]["prompt_protocol"] == {"name": "qwen_image_2_1", "version": 2}
    assert "reference_instruction" not in spec["subjects"][0]["identity"]
    assert "\n" not in prompt
    if expression == "hybrid":
        parts = prepared["prompt"]
        assert parts["combined_text"] == parts["natural_language_text"] + "\n" + parts["tag_text"]


@pytest.mark.parametrize("expression", ["tag", "natural_language", "hybrid"])
def test_back_reference_preserves_page_state_without_front_identity_description(tmp_path, expression):
    """背面传图同样保留当前湿衣，不能因为有身份图重新要求展示五官。"""
    spec = _spec(tmp_path, count=1)
    spec.update(prompt_type=expression, shot_plan={"render_text": False}, subjects=[
        {"character_key": "alice", "name": "Alice", "identity": {"appearance": "amber eyes and a cheek scar"},
         "hairstyle": "short black bob", "outfit": {"garment_components": ["confirmed navy coat"]},
         "shot": {"action": "walks away", "pose": "upright", "reference_view": "back",
                  "visible_state": "the back of the coat is rain soaked"}},
    ])
    prepared = prepare_renderer_spec(spec, _preset(), GenerationMode.PREVIEW)
    prompt = prepared["prompt"]["positive"]
    assert "amber eyes" not in prompt and "cheek scar" not in prompt
    assert "exact facial identity" not in prompt
    for value in ("requested rear view", "face entirely out of frame", "rain soaked", "short black bob", "confirmed navy coat"):
        assert value in prompt
    assert prepared["subjects"][0]["identity"]["appearance"] == "amber eyes and a cheek scar"


def test_single_reference_no_tags_and_no_reference_prompt_unchanged(tmp_path):
    spec = _spec(tmp_path, count=1)
    prepared = prepare_renderer_spec(spec, _preset(), GenerationMode.FINAL)
    assert prepared["reference_inputs"]["items"][0]["label"] == "the image"
    assert "<image" not in prepared["prompt"]["positive"]
    empty = _spec(tmp_path, count=0)
    assert prepare_renderer_spec(empty, _preset(), GenerationMode.FINAL)["prompt"] == empty["prompt"]


def test_canvas_is_explicit_and_frozen_old_labels_are_preserved(tmp_path):
    spec = _spec(tmp_path, count=2)
    spec["reference_canvas"] = spec["reference_plan"]["items"].pop(0)
    preset = _preset()
    config = json.loads(preset.capabilities_json)
    config["reference_images"]["requires_canvas"] = True
    preset.capabilities_json = json.dumps(config)
    prepared = prepare_renderer_spec(spec, preset, GenerationMode.FINAL)
    assert "<image1> is the editing canvas" in prepared["prompt"]["positive"]
    assert "These are reference sources, not a canvas" not in prepared["prompt"]["positive"]
    prepared["reference_inputs"]["items"][0]["label"] = "Picture 1"
    prepared["prompt"]["positive"] = "Frozen old Picture 1 instruction"
    assert prepare_renderer_spec(prepared, preset, GenerationMode.FINAL) == prepared
