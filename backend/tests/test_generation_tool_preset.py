import json
from types import SimpleNamespace

from backend.models.enums import ImageGenerationToolKind
from backend.services.image_generation_service import ImageGenerationService


class CapturingRepository:
    def __init__(self):
        self.session = SimpleNamespace(get=lambda *_args, **_kwargs: None)
        self.values = None

    def create_image_generation_tool_preset(self, **values):
        self.values = values
        return SimpleNamespace(**values)


def test_explicit_bindings_are_the_truth_for_legacy_node_columns() -> None:
    repository = CapturingRepository()
    service = ImageGenerationService(repository)
    workflow = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": 0}},
    }

    service.create_tool_preset(
        name="Structured",
        kind=ImageGenerationToolKind.COMFYUI,
        workflow_json=json.dumps(workflow),
        capabilities={"features": ["txt2img"], "limits": {}},
        bindings={
            "schema_version": 1,
            "bindings": [
                {"source": "prompt.positive", "node_id": "1", "input_name": "text"},
                {"source": "render.seed", "node_id": "2", "input_name": "seed"},
            ],
        },
        positive_node_id=None,
        positive_input_name=None,
    )

    assert repository.values["positive_node_id"] == "1"
    assert repository.values["positive_input_name"] == "text"
    assert repository.values["seed_node_id"] == "2"
    assert repository.values["seed_input_name"] == "seed"
