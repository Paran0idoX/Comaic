"""在外部请求前冻结图片数组、编号和裁减说明，Provider 只发送该快照。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.models.comic import ImageGenerationToolPreset
from backend.i18n.errors import AppError
from backend.models.enums import GenerationMode, ImageGenerationProvider, ImagePromptType
from backend.services.workflow_compiler import parse_bindings, parse_capabilities
from backend.utils.prompt_loader import PromptLoader


def _label(index: int, format_name: str) -> str:
    return {"image_N": f"image {index}", "picture_N": f"Picture {index}", "bracket_N": f"[{index}]"}[format_name]


def frozen_preset(preset: ImageGenerationToolPreset, spec: dict[str, Any]) -> ImageGenerationToolPreset:
    """恢复运行的工具参数；凭据仍读取本地工具配置，不写入运行快照。"""
    snapshot = spec.get("renderer_config")
    if not isinstance(snapshot, dict):
        return preset
    values = {key: getattr(preset, key, None) for key in _PRESET_FIELDS}
    values.update({key: value for key, value in snapshot.items() if key in _PRESET_FIELDS})
    values["provider"] = ImageGenerationProvider(values["provider"])
    values["prompt_type"] = ImagePromptType(values["prompt_type"])
    values["api_key"] = preset.api_key
    values["id"] = preset.id
    return ImageGenerationToolPreset(**values)


_PRESET_FIELDS = (
    "name", "provider", "prompt_type", "workflow_json", "bindings_json", "capabilities_json",
    "comfy_base_url", "api_base_url", "endpoint_path", "model", "size", "response_format",
    "seed_field_name", "negative_prompt_field_name", "extra_body_json",
)


def prepare_renderer_spec(spec: dict[str, Any], preset: ImageGenerationToolPreset,
                          mode: GenerationMode) -> dict[str, Any]:
    """纯本地预检查；严格失败时还没有上传图片或提交任何生成请求。"""
    result = deepcopy(spec)
    if result.get("reference_inputs"):
        # 继续任务使用已冻结的输入，不能重新按新素材或新工具容量裁减。
        frozen = frozen_preset(preset, result)
        for item in result["reference_inputs"].get("items", []):
            _validate_file(item, require_local=frozen.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE)
        return result
    plan = result.get("reference_plan")
    if not isinstance(plan, dict):
        result["renderer_config"] = {key: (getattr(preset, key).value if hasattr(getattr(preset, key, None), "value") else getattr(preset, key, None)) for key in _PRESET_FIELDS}
        return result  # 历史规格不推测真实输入顺序。
    capabilities = parse_capabilities(preset.capabilities_json)
    config = capabilities.reference_images
    is_comfy = preset.provider == ImageGenerationProvider.COMFYUI
    slots = len(parse_bindings(preset.bindings_json).reference_slots) if is_comfy else config.max_images
    supported = bool({"reference_image", "img2img"}.intersection(item.value for item in capabilities.features))
    if not is_comfy and config.transport == "none":
        supported = False
    capacity = min(config.max_images, slots) if supported else 0
    items = deepcopy(plan.get("items") or [])
    omitted = deepcopy(plan.get("omitted") or [])
    degradations: list[dict[str, str]] = []
    if config.requires_canvas:
        canvas = result.get("reference_canvas")
        if not isinstance(canvas, dict):
            raise AppError("reference.input.canvas_required")
        canvas = deepcopy(canvas)
        canvas.update(purpose="canvas", is_primary=True, is_required=True, priority=-1)
        items.insert(0, canvas)
    valid: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for item in items:
        identity = item.get("asset_id", item.get("id")) or item.get("local_path") or item.get("renderer_locator")
        if identity in seen:
            continue
        seen.add(identity)
        try:
            _validate_file(item, require_local=not is_comfy)
        except AppError:
            if mode == GenerationMode.FINAL or item.get("purpose") == "canvas":
                raise
            omitted.append({**item, "reason_code": "reference.file_unavailable", "reason": "Original image unavailable"})
            degradations.append({"code": "reference.file_unavailable", "message": "Original reference image unavailable"})
            continue
        valid.append(item)
    primaries = [item for item in valid if item.get("is_primary", True)]
    if mode == GenerationMode.FINAL and len(primaries) > capacity:
        raise AppError("reference.input.capacity_exceeded", params={"capacity": capacity, "required": len(primaries)})
    # 先为各对象主参考保留位置，辅助图片不能挤掉场景或普通可见物品。
    ranked = sorted(enumerate(valid), key=lambda pair: (
        not pair[1].get("is_primary", True),
        -1 if pair[1].get("purpose") == "canvas" else {"character": 0, "scene": 1, "prop": 2}.get((pair[1].get("owner") or {}).get("category"), 3),
        pair[1].get("priority", 100), pair[0],
    ))
    selected_indexes = {index for index, _ in ranked[:capacity]}
    selected: list[dict[str, Any]] = []
    for index, item in enumerate(valid):
        if index not in selected_indexes:
            omitted.append({**item, "reason_code": "reference.capacity_exceeded", "reason": "Tool image capacity exceeded"})
            degradations.append({"code": "reference.capacity_exceeded", "message": "Reference image omitted due to tool capacity"})
            continue
        item.update(order=len(selected) + 1, label=_label(len(selected) + 1, config.label_format))
        selected.append(item)
    if config.requires_canvas and (not selected or selected[0].get("purpose") != "canvas"):
        raise AppError("reference.input.capacity_exceeded", params={"capacity": capacity, "required": 1})
    result["reference_inputs"] = {
        "schema_version": 1, "order_known": True, "transport": "comfyui" if is_comfy else config.transport.value,
        "capacity": capacity, "items": selected, "omitted": omitted, "degradations": degradations,
    }
    required = list(result.get("required_capabilities") or [])
    if not selected:
        required = [item for item in required if item != "reference_image"]
    elif "reference_image" not in required:
        required.append("reference_image")
    result["required_capabilities"] = required
    if selected:
        lines = []
        for item in selected:
            owner = item.get("owner") or {}
            lines.append(f"{item['label']}: {owner.get('name') or owner.get('key') or 'editing canvas'} "
                         f"(owner {owner.get('category', 'canvas')}:{owner.get('key') or owner.get('id', '')}); "
                         f"purpose={item.get('purpose')}; view={item.get('role', '')}. {item.get('reason', '')}")
        instructions = PromptLoader.load("reference_image_order_prompt.md").format(references="\n".join(lines))
        prompt = result.setdefault("prompt", {})
        prompt["positive"] = str(prompt.get("positive") or "").rstrip() + "\n\n" + instructions.strip()
    result["renderer_config"] = {key: (getattr(preset, key).value if hasattr(getattr(preset, key, None), "value") else getattr(preset, key, None)) for key in _PRESET_FIELDS}
    return result


def validate_renderer_spec(spec: dict[str, Any], preset: ImageGenerationToolPreset,
                           mode: GenerationMode, seed: int = 0) -> None:
    """整批生成先验证所有页面，保证严格检查失败时零提交。"""
    from backend.services.workflow_compiler import WorkflowCompiler
    preset = frozen_preset(preset, spec)
    if preset.provider == ImageGenerationProvider.COMFYUI:
        bindings = parse_bindings(preset.bindings_json)
        def check_files(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("storage_kind") == "local_file":
                    _validate_file(value, require_local=True)
                for child in value.values():
                    check_files(child)
            elif isinstance(value, list):
                for child in value:
                    check_files(child)
        if spec.get("reference_inputs"):
            check_files(spec["reference_inputs"].get("items", []))
            for binding in bindings.bindings:
                if ".controls." in binding.source:
                    try:
                        check_files(WorkflowCompiler.resolve_value(spec, binding.source))
                    except (KeyError, IndexError, TypeError):
                        pass  # 缺条件由下面的工作流严格/宽松检查处理。
        else:
            check_files(spec)
        checked = deepcopy(spec)
        def mark_upload_names(value: Any) -> None:
            # 旧 binding 可直接指向 .renderer_name；真实上传前用占位值验证同一条路径。
            if isinstance(value, dict):
                if value.get("storage_kind") == "local_file" and value.get("local_path"):
                    value["renderer_name"] = "pending-upload.png"
                elif value.get("storage_kind") == "renderer_locator" and value.get("renderer_locator"):
                    value["renderer_name"] = value["renderer_locator"]
                for child in value.values():
                    mark_upload_names(child)
            elif isinstance(value, list):
                for child in value:
                    mark_upload_names(child)
        mark_upload_names(checked)
        WorkflowCompiler().compile(workflow=json.loads(preset.workflow_json or "{}"), spec=checked,
                                   seed=seed, capabilities=parse_capabilities(preset.capabilities_json),
                                   bindings=bindings, mode=mode)
    elif mode == GenerationMode.FINAL:
        available = {"txt2img"}
        if (spec.get("reference_inputs") or {}).get("items"):
            available.add("reference_image")
            if any(item.get("purpose") == "canvas" for item in spec["reference_inputs"]["items"]):
                available.add("img2img")
        if set(spec.get("required_capabilities") or []) - available:
            raise AppError("workflow.capability_missing")
        if not preset.seed_field_name:
            raise AppError("workflow.capability_missing", debug_message="Image API does not expose a seed field")
        if (spec.get("prompt") or {}).get("negative") and not preset.negative_prompt_field_name:
            raise AppError("workflow.capability_missing", debug_message="Image API does not expose a negative prompt field")


def _validate_file(item: dict[str, Any], *, require_local: bool) -> None:
    path_text = item.get("local_path")
    if not path_text:
        if not require_local and item.get("renderer_locator"):
            return
        raise AppError("reference.input.file_unavailable")
    path = Path(str(path_text))
    if not path.is_file():
        raise AppError("reference.input.file_unavailable")
    if item.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise AppError("reference.input.file_changed")
