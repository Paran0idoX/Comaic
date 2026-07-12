from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.models.enums import GenerationMode
from backend.services.workflow_compiler import (
    WorkflowBindings,
    WorkflowCapabilities,
    WorkflowCompiler,
)


def _workflow() -> dict:
    return {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "original"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": 0}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
    }


def _bindings() -> WorkflowBindings:
    return WorkflowBindings.model_validate(
        {
            "schema_version": 1,
            "bindings": [
                {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                {"source": "render.seed", "node_id": "2", "input_name": "seed"},
                {
                    "source": "subjects[0].identity.references[0]",
                    "node_id": "3",
                    "input_name": "image",
                },
            ],
        }
    )


def _spec(required: list[str] | None = None) -> dict:
    return {
        "prompt": {"positive": "stable prompt", "negative": ""},
        "render": {},
        "subjects": [{"identity": {"references": [{"renderer_name": "alice.png"}]}}],
        "scene": {},
        "style": {},
        "model_profile": {"family": "anima"},
        "required_capabilities": required or ["txt2img", "reference_image"],
    }


def test_compiler_deep_copies_and_applies_restricted_bindings() -> None:
    original = _workflow()
    before = deepcopy(original)
    compiled = WorkflowCompiler().compile(
        workflow=original,
        spec=_spec(),
        seed=1234,
        capabilities=WorkflowCapabilities.model_validate(
            {"features": ["txt2img", "reference_image"], "limits": {"max_subjects": 2}}
        ),
        bindings=_bindings(),
        mode=GenerationMode.FINAL,
    )

    assert original == before
    assert compiled.workflow["1"]["inputs"]["text"] == "stable prompt"
    assert compiled.workflow["2"]["inputs"]["seed"] == 1234
    assert compiled.workflow["3"]["inputs"]["image"] == "alice.png"
    assert compiled.applied_spec["render"]["seed"] == 1234


def test_preview_records_missing_capability_and_final_rejects() -> None:
    capabilities = WorkflowCapabilities.model_validate({"features": ["txt2img"], "limits": {}})
    prompt_bindings = WorkflowBindings.model_validate(
        {
            "bindings": [
                {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                {"source": "render.seed", "node_id": "2", "input_name": "seed"},
            ]
        }
    )
    preview = WorkflowCompiler().compile(
        workflow=_workflow(),
        spec=_spec(),
        seed=1,
        capabilities=capabilities,
        bindings=prompt_bindings,
        mode=GenerationMode.PREVIEW,
    )
    assert preview.degradations[0]["code"] == "workflow.capability_missing"
    with pytest.raises(ValueError, match="Final workflow cannot satisfy"):
        WorkflowCompiler().compile(
            workflow=_workflow(),
            spec=_spec(),
            seed=1,
            capabilities=capabilities,
            bindings=prompt_bindings,
            mode=GenerationMode.FINAL,
        )


def test_preview_records_missing_seed_binding_and_final_rejects() -> None:
    bindings = WorkflowBindings.model_validate(
        {
            "bindings": [
                {"source": "prompt.positive", "node_id": "1", "input_name": "text"}
            ]
        }
    )
    capabilities = WorkflowCapabilities.model_validate(
        {"features": ["txt2img", "reference_image"], "limits": {}}
    )
    preview = WorkflowCompiler().compile(
        workflow=_workflow(),
        spec=_spec(required=["txt2img"]),
        seed=1,
        capabilities=capabilities,
        bindings=bindings,
        mode=GenerationMode.PREVIEW,
    )
    assert any(item["code"] == "workflow.seed_not_applied" for item in preview.degradations)
    with pytest.raises(ValueError, match="requested render seed"):
        WorkflowCompiler().compile(
            workflow=_workflow(),
            spec=_spec(required=["txt2img"]),
            seed=1,
            capabilities=capabilities,
            bindings=bindings,
            mode=GenerationMode.FINAL,
        )


def test_final_rejects_declared_but_unbound_reference_capability() -> None:
    bindings = WorkflowBindings.model_validate(
        {
            "bindings": [
                {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                {"source": "render.seed", "node_id": "2", "input_name": "seed"},
            ]
        }
    )
    capabilities = WorkflowCapabilities.model_validate(
        {"features": ["txt2img", "reference_image"], "limits": {}}
    )
    with pytest.raises(ValueError, match="does not bind ImageSpec capability"):
        WorkflowCompiler().compile(
            workflow=_workflow(),
            spec=_spec(),
            seed=1,
            capabilities=capabilities,
            bindings=bindings,
            mode=GenerationMode.FINAL,
        )


def test_binding_rejects_jsonpath_and_duplicate_targets() -> None:
    with pytest.raises(ValidationError):
        WorkflowBindings.model_validate(
            {"bindings": [{"source": "$.prompt.positive", "node_id": "1", "input_name": "text"}]}
        )
    with pytest.raises(ValidationError):
        WorkflowBindings.model_validate(
            {
                "bindings": [
                    {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                    {"source": "render.seed", "node_id": "1", "input_name": "text"},
                ]
            }
        )


def test_configuration_rejects_binding_capability_and_subject_slot_mismatch() -> None:
    with pytest.raises(ValueError, match="requires capability reference_image"):
        WorkflowCompiler().validate_configuration(
            workflow=_workflow(),
            capabilities=WorkflowCapabilities.model_validate(
                {"features": ["txt2img"], "limits": {"max_subjects": 1}}
            ),
            bindings=_bindings(),
        )
    with pytest.raises(ValueError, match="exceeds max_subjects"):
        WorkflowCompiler().validate_configuration(
            workflow=_workflow(),
            capabilities=WorkflowCapabilities.model_validate(
                {
                    "features": ["txt2img", "reference_image"],
                    "limits": {"max_subjects": 1},
                }
            ),
            bindings=WorkflowBindings.model_validate(
                {
                    "bindings": [
                        {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                        {
                            "source": "subjects[1].identity.references[0]",
                            "node_id": "3",
                            "input_name": "image",
                        },
                    ]
                }
            ),
        )
