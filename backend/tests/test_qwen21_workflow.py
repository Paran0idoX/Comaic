"""确保随仓库交付的 Qwen 工作流能正确编译不同数量的原图。"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.models.enums import GenerationMode
from backend.api.schemas.image_generation import ImageGenerationToolPresetRequest
from backend.services.image_generation_service import ImageGenerationService
from backend.services.workflow_compiler import (
    WorkflowBindings,
    WorkflowCapabilities,
    WorkflowCompiler,
)
from workflows import register_qwen21


WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"


@pytest.mark.parametrize("reference_count,size", [(0, (768, 768)), (1, (512, 768)), (3, (640, 960)), (6, (1024, 768))])
def test_fixed_size_workflow_keeps_output_separate_from_reference_ratio(reference_count, size):
    payload = register_qwen21.build_preset(comfy_base_url="http://127.0.0.1:8188", fixed_size=True)
    spec = {"prompt": {"positive": "Character reference", "negative": "watermark"},
        "render": {"width": size[0], "height": size[1]},
        "required_capabilities": ["reference_image"] if reference_count else ["txt2img"],
        "reference_inputs": {"items": [{"renderer_name": f"original_{index}.png"} for index in range(reference_count)]}}
    result = WorkflowCompiler().compile(workflow=json.loads(payload["workflow_json"]), spec=spec, seed=42,
        capabilities=WorkflowCapabilities.model_validate(payload["capabilities"]),
        bindings=WorkflowBindings.model_validate(payload["bindings"]), mode=GenerationMode.FINAL)
    assert result.workflow["8"]["inputs"] == {"width": size[0], "height": size[1], "batch_size": 1}
    assert result.workflow["5"]["inputs"]["latent_image"] == ["8", 0]
    assert result.workflow["2"]["inputs"]["clip_name"] == "qwenImage21_v21_txt_3239856.safetensors"
    for index in range(6):
        assert (str(11 + index) in result.workflow) == (index < reference_count)
    request = ImageGenerationToolPresetRequest.model_validate(payload)
    ImageGenerationService(Mock()).create_tool_preset(**request.model_dump())


@pytest.mark.parametrize("reference_count", [0, 1, 3, 6])
def test_qwen21_compiles_ordered_references_and_removes_unused_loaders(reference_count):
    """空槽必须完全断开，已用槽顺序必须与冻结清单一致。"""
    workflow = json.loads((WORKFLOWS / "qwen21_reference_api.json").read_text(encoding="utf-8"))
    bindings = WorkflowBindings.model_validate_json(
        (WORKFLOWS / "qwen21_reference_bindings.json").read_text(encoding="utf-8")
    )
    capabilities = WorkflowCapabilities.model_validate_json(
        (WORKFLOWS / "qwen21_reference_capabilities.json").read_text(encoding="utf-8")
    )
    spec = {
        "prompt": {"positive": "A comic scene with the supplied references.", "negative": "watermark"},
        "reference_inputs": {"items": [
            {"renderer_name": f"comaic/approved_{index}.png"}
            for index in range(1, reference_count + 1)
        ]},
        "required_capabilities": ["reference_image"] if reference_count else ["txt2img"],
    }
    result = WorkflowCompiler().compile(
        workflow=workflow, spec=spec, seed=42, capabilities=capabilities,
        bindings=bindings, mode=GenerationMode.FINAL,
    )

    assert not result.degradations
    assert result.workflow["4"]["inputs"]["prompt"] == spec["prompt"]["positive"]
    assert result.workflow["4"]["inputs"]["negative_prompt"] == "watermark"
    assert result.workflow["5"]["inputs"]["seed"] == 42
    # 漫画画布独立于参考图比例；ComfyUI 将空 latent 转换为 Qwen 所需格式。
    assert result.workflow["5"]["inputs"]["latent_image"] == ["8", 0]
    assert result.workflow["8"]["inputs"] == {"width": 1024, "height": 1536, "batch_size": 1}
    for index in range(1, 7):
        loader_id = str(index + 10)
        input_name = f"images.image_{index}"
        if index <= reference_count:
            assert result.workflow[loader_id]["inputs"]["image"] == f"comaic/approved_{index}.png"
            assert result.workflow["4"]["inputs"][input_name] == [loader_id, 0]
        else:
            assert loader_id not in result.workflow
            assert input_name not in result.workflow["4"]["inputs"]
    # 所有连接都必须落在仍存在的节点，防止空槽留下失效引用。
    for node in result.workflow.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert str(value[0]) in result.workflow


def test_registration_payload_passes_current_backend_validation_from_any_directory(monkeypatch, tmp_path):
    """复用脚本必须独立于 cwd，并通过当前 API 和业务层校验而不访问真实库。"""
    monkeypatch.chdir(tmp_path)
    payload = register_qwen21.build_preset(comfy_base_url="http://127.0.0.1:18188/")
    request = ImageGenerationToolPresetRequest.model_validate(payload)
    repository = Mock()
    ImageGenerationService(repository).create_tool_preset(**request.model_dump())
    values = repository.create_image_generation_tool_preset.call_args.kwargs

    assert values["comfy_base_url"] == "http://127.0.0.1:18188"
    assert values["positive_input_name"] == "prompt"
    assert values["negative_input_name"] == "negative_prompt"
    assert values["seed_node_id"] == "5"
    assert len(json.loads(values["bindings_json"])["reference_slots"]) == 6
    assert values["is_default"] is False
    assert values["api_key"] is None


def test_registration_posts_only_to_explicit_backend(monkeypatch):
    """注册应只发送一次明确目标请求，中文配置使用 UTF-8 且不需要凭据。"""
    import io

    transport = Mock(return_value=io.BytesIO(b'{"id":42}'))
    monkeypatch.setattr(register_qwen21, "urlopen", transport)
    payload = register_qwen21.build_preset(comfy_base_url="http://127.0.0.1:18188", name="验收工具")
    preset_id = register_qwen21.register_preset(base_url="http://127.0.0.1:18000/", preset=payload)
    transport.assert_called_once()
    request = transport.call_args.args[0]

    assert preset_id == 42
    assert request.full_url == "http://127.0.0.1:18000/api/image-generation/tools"
    assert request.method == "POST"
    assert json.loads(request.data.decode("utf-8")) == payload
    assert not request.has_header("Authorization")
