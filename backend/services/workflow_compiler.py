from copy import deepcopy
import json
import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.models.enums import GenerationMode, WorkflowCapability, ReferenceImageTransport, ReferenceImageLabelFormat


SOURCE_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[[0-9]+\]))*$"
)
ALLOWED_SOURCE_ROOTS = {"prompt", "render", "subjects", "scene", "style", "reference_inputs"}


class WorkflowBinding(BaseModel):
    """把 ImageSpec 的一个受限字段绑定到 ComfyUI 节点 input。"""

    source: str
    node_id: str
    input_name: str

    @model_validator(mode="after")
    def validate_source(self):
        if not SOURCE_PATH_RE.fullmatch(self.source):
            raise ValueError(f"Unsupported workflow binding source path: {self.source}")
        if self.source.split(".", 1)[0].split("[", 1)[0] not in ALLOWED_SOURCE_ROOTS:
            raise ValueError(f"Unsupported workflow binding source root: {self.source}")
        if ".loras" in self.source:
            raise ValueError(
                "LoRA is configured inside the ComfyUI workflow, not through ImageSpec bindings."
            )
        if not self.node_id.strip() or not self.input_name.strip():
            raise ValueError("Workflow binding node_id and input_name are required")
        return self


class WorkflowInputTarget(BaseModel):
    """显式声明空参考槽需要断开的消费节点，不猜测工作流图结构。"""

    node_id: str = Field(min_length=1)
    input_name: str = Field(min_length=1)


class WorkflowReferenceSlot(WorkflowInputTarget):
    disconnect: list[WorkflowInputTarget] = Field(default_factory=list, min_length=1)


class WorkflowBindings(BaseModel):
    schema_version: int = 1
    bindings: list[WorkflowBinding] = Field(default_factory=list)
    reference_slots: list[WorkflowReferenceSlot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_targets(self):
        targets = [(item.node_id, item.input_name) for item in [*self.bindings, *self.reference_slots]]
        if len(targets) != len(set(targets)):
            raise ValueError("Workflow bindings contain duplicate node input targets")
        if len({item.node_id for item in self.reference_slots}) != len(self.reference_slots):
            raise ValueError("Each ordered reference slot requires its own image loader node")
        disconnected = [(target.node_id, target.input_name) for slot in self.reference_slots for target in slot.disconnect]
        if len(disconnected) != len(set(disconnected)) or set(disconnected).intersection(targets):
            raise ValueError("Reference slots contain overlapping disconnect targets")
        return self


class ReferenceImageConfiguration(BaseModel):
    """工具自身的图片传输约定，与具体图片模型无关。"""

    max_images: int = Field(default=0, ge=0, le=100)
    label_format: ReferenceImageLabelFormat = ReferenceImageLabelFormat.IMAGE_N
    requires_canvas: bool = False
    transport: ReferenceImageTransport = ReferenceImageTransport.NONE
    edit_endpoint_path: str | None = None
    image_field_name: str = "image[]"

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.transport != "none" and (not self.edit_endpoint_path or not self.image_field_name.strip()):
            raise ValueError("Image editing endpoint and image field are required")
        if self.image_field_name in {"model", "prompt", "n", "size", "response_format"}:
            raise ValueError("Image field must not overwrite a generation parameter")
        return self


class WorkflowCapabilities(BaseModel):
    features: list[WorkflowCapability] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)
    reference_images: ReferenceImageConfiguration = Field(default_factory=ReferenceImageConfiguration)

    @model_validator(mode="after")
    def validate_limits(self):
        for key, value in self.limits.items():
            if value < 0:
                raise ValueError(f"Workflow capability limit cannot be negative: {key}")
        return self


class CompiledWorkflow(BaseModel):
    workflow: dict[str, Any]
    applied_spec: dict[str, Any]
    degradations: list[dict[str, str]]


class WorkflowCompiler:
    """按声明式 binding 编译 workflow；不执行任意路径表达式或 Python 代码。"""

    def validate_configuration(
        self,
        *,
        workflow: dict[str, Any],
        capabilities: WorkflowCapabilities,
        bindings: WorkflowBindings,
    ) -> None:
        for binding in bindings.bindings:
            node = workflow.get(binding.node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                raise ValueError(
                    f"Workflow node input not found: {binding.node_id}.{binding.input_name}"
                )
            if binding.input_name not in node["inputs"]:
                raise ValueError(f"Workflow node input not found: {binding.node_id}.{binding.input_name}")
        for slot in bindings.reference_slots:
            for target in [slot, *slot.disconnect]:
                node = workflow.get(target.node_id)
                if not isinstance(node, dict) or target.input_name not in node.get("inputs", {}):
                    raise ValueError(f"Reference slot target not found: {target.node_id}.{target.input_name}")
                if target is not slot:
                    connection = node["inputs"][target.input_name]
                    if not isinstance(connection, list) or len(connection) != 2 or str(connection[0]) != slot.node_id:
                        raise ValueError("Workflow binding reference slot consumer does not connect to its declared image loader")
            if not {WorkflowCapability.REFERENCE_IMAGE, WorkflowCapability.IMG2IMG}.intersection(capabilities.features):
                raise ValueError("Reference slots require capability reference_image")
        sources = {binding.source for binding in bindings.bindings}
        if "prompt.positive" not in sources:
            raise ValueError("Workflow binding prompt.positive is required.")
        if WorkflowCapability.TXT2IMG not in capabilities.features:
            raise ValueError("Workflow capabilities must include txt2img.")
        max_subjects = capabilities.limits.get("max_subjects")
        if max_subjects is not None and max_subjects < 1:
            raise ValueError("max_subjects must be at least 1 when declared.")
        for source in sources:
            subject_match = re.match(r"^subjects\[([0-9]+)\]", source)
            if subject_match and max_subjects is not None:
                subject_index = int(subject_match.group(1))
                if subject_index >= max_subjects:
                    raise ValueError(
                        f"Workflow binding subject slot {subject_index} exceeds max_subjects={max_subjects}."
                    )
            required_capability = self._binding_capability(source)
            if required_capability is not None and required_capability not in capabilities.features:
                raise ValueError(
                    f"Workflow binding {source} requires capability {required_capability.value}."
                )

    def compile(
        self,
        *,
        workflow: dict[str, Any],
        spec: dict[str, Any],
        seed: int,
        capabilities: WorkflowCapabilities,
        bindings: WorkflowBindings,
        mode: GenerationMode,
    ) -> CompiledWorkflow:
        self.validate_configuration(
            workflow=workflow,
            capabilities=capabilities,
            bindings=bindings,
        )
        applied_spec = deepcopy(spec)
        applied_spec.setdefault("render", {})["seed"] = seed
        required = set(applied_spec.get("required_capabilities", []))
        available = {item.value for item in capabilities.features}
        if bindings.reference_slots and "img2img" in available:
            available.add("reference_image")
        missing = sorted(required - available)
        degradations = [
            {
                "code": "workflow.capability_missing",
                "message": f"Workflow does not declare capability: {capability}",
            }
            for capability in missing
        ]
        bound_capabilities = {WorkflowCapability.TXT2IMG.value}
        bound_capabilities.update(
            capability.value
            for binding in bindings.bindings
            if (capability := self._binding_capability(binding.source)) is not None
        )
        if bindings.reference_slots:
            bound_capabilities.add(WorkflowCapability.REFERENCE_IMAGE.value)
            if "img2img" in available:
                bound_capabilities.add(WorkflowCapability.IMG2IMG.value)
        unbound = sorted(required - bound_capabilities)
        degradations.extend(
            {
                "code": "workflow.capability_unbound",
                "message": f"Workflow does not bind ImageSpec capability: {capability}",
            }
            for capability in unbound
        )
        binding_sources = {binding.source for binding in bindings.bindings}

        def require_prefix(prefix: str, label: str) -> None:
            # 历史工作流可将整个 references 数组绑定为 JSON；该绑定覆盖数组内每一项。
            collection = re.sub(r"\[\d+\]$", "", prefix)
            if not any(
                source == prefix or source.startswith(f"{prefix}[") or source.startswith(f"{prefix}.")
                or (collection != prefix and source == collection)
                for source in binding_sources
            ):
                degradations.append(
                    {
                        "code": "workflow.condition_unbound",
                        "message": f"Workflow does not bind ImageSpec condition: {label}",
                    }
                )

        if (applied_spec.get("prompt") or {}).get("negative"):
            require_prefix("prompt.negative", "negative prompt")
        subjects = applied_spec.get("subjects", [])
        for index, subject in enumerate(subjects):
            identity = subject.get("identity") or {}
            outfit = subject.get("outfit") or {}
            for field_name, values in (
                ("identity.references", identity.get("references", [])),
                ("outfit.references", outfit.get("references", [])),
            ):
                if values and not applied_spec.get("reference_inputs"):
                    for reference_index in range(len(values)):
                        require_prefix(f"subjects[{index}].{field_name}[{reference_index}]", f"subject {index} {field_name}[{reference_index}]")
            for control_name in (subject.get("controls") or {}):
                require_prefix(
                    f"subjects[{index}].controls.{control_name}",
                    f"subject {index} {control_name} control",
                )
            for prop_index, prop in enumerate(subject.get("props", [])):
                if prop.get("references") and not applied_spec.get("reference_inputs"):
                    require_prefix(
                        f"subjects[{index}].props[{prop_index}].references",
                        f"subject {index} prop {prop.get('prop_key', prop_index)} references",
                    )
            if "regional_condition" in required:
                require_prefix(
                    f"subjects[{index}].shot.region",
                    f"subject {index} region",
                )
        for owner_name in ("scene", "style"):
            owner = applied_spec.get(owner_name) or {}
            for field_name in ("references",):
                if owner.get(field_name) and not applied_spec.get("reference_inputs"):
                    for reference_index in range(len(owner[field_name])):
                        require_prefix(f"{owner_name}.{field_name}[{reference_index}]", f"{owner_name} {field_name}[{reference_index}]")
            for control_name in (owner.get("controls") or {}):
                require_prefix(
                    f"{owner_name}.controls.{control_name}",
                    f"{owner_name} {control_name} control",
                )
        if not any(binding.source == "render.seed" for binding in bindings.bindings):
            degradations.append(
                {
                    "code": "workflow.seed_not_applied",
                    "message": "Workflow does not bind the requested render seed.",
                }
            )
        subject_limit = capabilities.limits.get("max_subjects")
        if subject_limit is not None and len(applied_spec.get("subjects", [])) > subject_limit:
            degradations.append(
                {
                    "code": "workflow.subject_limit_exceeded",
                    "message": (
                        f"ImageSpec has {len(applied_spec.get('subjects', []))} subjects; "
                        f"workflow supports {subject_limit}."
                    ),
                }
            )
        if mode == GenerationMode.FINAL and degradations:
            raise ValueError(
                "Final workflow cannot satisfy ImageSpec: "
                + ", ".join(item["message"] for item in degradations)
            )

        compiled = deepcopy(workflow)
        for binding in bindings.bindings:
            try:
                value = self.resolve_source(applied_spec, binding.source)
            except (KeyError, IndexError, TypeError) as exc:
                degradation = {
                    "code": "workflow.binding_source_missing",
                    "message": f"ImageSpec source is missing: {binding.source}",
                }
                if mode == GenerationMode.FINAL:
                    raise ValueError(degradation["message"]) from exc
                degradations.append(degradation)
                # 缺项必须清掉示例输入；保留样例图会悄悄改变真正发送的条件。
                compiled[binding.node_id]["inputs"].pop(binding.input_name, None)
                continue
            compiled[binding.node_id]["inputs"][binding.input_name] = value
        references = (applied_spec.get("reference_inputs") or {}).get("items", [])
        if len(references) > len(bindings.reference_slots) and applied_spec.get("reference_inputs"):
            raise ValueError("Ordered reference inputs exceed configured workflow slots")
        for index, slot in enumerate(bindings.reference_slots):
            if index < len(references):
                image_name = references[index].get("renderer_name")
                if not image_name:
                    raise ValueError(f"Reference input {index + 1} has not been resolved")
                compiled[slot.node_id]["inputs"][slot.input_name] = image_name
            else:
                for target in [slot, *slot.disconnect]:
                    compiled[target.node_id]["inputs"].pop(target.input_name, None)
                # 槽的loader只用于此槽，空槽移除它，避免执行残留示例图片。
                compiled.pop(slot.node_id, None)
        return CompiledWorkflow(
            workflow=compiled,
            applied_spec=applied_spec,
            degradations=degradations,
        )

    @staticmethod
    def resolve_source(value: Any, path: str) -> Any:
        """解析经过正则约束的点号/数组路径；明确禁止 eval 和完整 JSONPath。"""
        current = WorkflowCompiler.resolve_value(value, path)
        if isinstance(current, dict) and current.get("renderer_name"):
            return current["renderer_name"]
        if isinstance(current, (dict, list)):
            return json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return current

    @staticmethod
    def resolve_value(value: Any, path: str) -> Any:
        """同一受限路径的原始值，供提交前校验本地控制图使用。"""
        if not SOURCE_PATH_RE.fullmatch(path):
            raise ValueError(f"Unsupported workflow binding source path: {path}")
        current = value
        for name, index in re.findall(r"(?:^|\.)([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]", path):
            if name:
                if not isinstance(current, dict):
                    raise TypeError(path)
                current = current[name]
            else:
                if not isinstance(current, list):
                    raise TypeError(path)
                current = current[int(index)]
        return current

    @staticmethod
    def _binding_capability(source: str) -> WorkflowCapability | None:
        """从受限源路径推导显式能力，保存 preset 时即可发现声明/绑定矛盾。"""

        if ".references" in source:
            return WorkflowCapability.REFERENCE_IMAGE
        if ".shot.region" in source:
            return WorkflowCapability.REGIONAL_CONDITION
        for name, capability in (
            ("pose", WorkflowCapability.POSE),
            ("depth", WorkflowCapability.DEPTH),
            ("canny", WorkflowCapability.CANNY),
            ("lineart", WorkflowCapability.LINEART),
        ):
            if f".controls.{name}" in source:
                return capability
        return None


def parse_capabilities(value: str) -> WorkflowCapabilities:
    try:
        return WorkflowCapabilities.model_validate_json(value)
    except Exception as exc:
        raise ValueError(f"Workflow capabilities JSON is invalid: {exc}") from exc


def parse_bindings(value: str) -> WorkflowBindings:
    try:
        return WorkflowBindings.model_validate_json(value)
    except Exception as exc:
        raise ValueError(f"Workflow bindings JSON is invalid: {exc}") from exc
