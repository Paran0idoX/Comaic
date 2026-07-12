import pytest

from backend.i18n.errors import AppError
from backend.models.comic import ImageGenerationToolPreset
from backend.services.renderer_backends import ComfyUIBackend, RendererSubmission


class FakeComfyClient:
    def __init__(self, history):
        self.history = history

    def get_history(self, _prompt_id):
        return self.history

    @staticmethod
    def extract_output_images(history, prompt_id):
        from backend.tools.comfyui_client import ComfyUIClient

        return ComfyUIClient.extract_output_images(history, prompt_id)

    @staticmethod
    def extract_execution_error(history, prompt_id):
        from backend.tools.comfyui_client import ComfyUIClient

        return ComfyUIClient.extract_execution_error(history, prompt_id)


def _submission() -> RendererSubmission:
    return RendererSubmission(
        external_id="prompt-1",
        applied_spec={},
        workflow={},
        workflow_hash="hash",
        degradations=[],
        seed_applied=True,
    )


@pytest.mark.asyncio
async def test_comfy_wait_raises_immediately_for_execution_error() -> None:
    client = FakeComfyClient(
        {
            "prompt-1": {
                "outputs": {},
                "status": {
                    "status_str": "error",
                    "messages": [
                        [
                            "execution_error",
                            {
                                "node_id": "47",
                                "node_type": "KSampler",
                                "exception_type": "RuntimeError",
                                "exception_message": "out of memory",
                            },
                        ]
                    ],
                },
            }
        }
    )
    backend = ComfyUIBackend(ImageGenerationToolPreset(), client)

    with pytest.raises(AppError) as captured:
        await backend.wait(
            _submission(),
            poll_interval_seconds=0.001,
            timeout_seconds=1,
        )

    assert captured.value.code == "image_generation.comfyui_execution_failed"
    assert "node 47" in str(captured.value)


@pytest.mark.asyncio
async def test_comfy_wait_has_external_timeout() -> None:
    backend = ComfyUIBackend(ImageGenerationToolPreset(), FakeComfyClient({}))

    with pytest.raises(AppError) as captured:
        await backend.wait(
            _submission(),
            poll_interval_seconds=0.001,
            timeout_seconds=0.01,
        )

    assert captured.value.code == "image_generation.comfyui_timeout"
