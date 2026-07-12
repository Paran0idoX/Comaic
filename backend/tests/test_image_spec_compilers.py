import pytest

from backend.models.enums import GenerationMode
from backend.services.image_spec_compilers import (
    AnimaImageSpecCompiler,
    ZImageImageSpecCompiler,
)


def _snapshot() -> dict:
    return {
        "characters": [
            {
                "character_key": "alice",
                "name": "Alice",
                "identity": {
                    "appearance": "young mechanic with amber eyes",
                    "visual_anchors": "small scar under left eyebrow",
                },
                "hairstyle": "short black bob",
                "outfit": {
                    "variant_id": 7,
                    "description": "navy repair coat with brass buttons",
                    "assets": [
                        {"role": "outfit_front", "model_family": "generic", "storage_kind": "local_file"}
                    ],
                },
                "accessories": {"description": "red tool belt"},
                "identity_assets": [
                    {"role": "identity_face", "model_family": "generic", "storage_kind": "local_file"}
                ],
            }
        ],
        "scene": {
            "scene_key": "workshop",
            "name": "Old workshop",
            "visual_version_id": 4,
            "environment_details": "dense shelves and a rusted generator",
            "visual_anchors": "arched window on the east wall",
            "lighting": "warm desk lamp",
            "weather": "rain",
            "assets": [
                {"role": "scene_master", "model_family": "generic", "storage_kind": "local_file"}
            ],
        },
    }


def _shot_plan() -> dict:
    return {
        "camera": {"shot_type": "medium shot", "angle": "eye level", "lens_mm": 50},
        "subjects": [
            {
                "character_key": "alice",
                "action": "reaches for the generator switch",
                "pose": "leaning forward",
                "expression": "focused",
                "identity": "EVIL OVERRIDE",
                "outfit": "EVIL OUTFIT",
                "control_requirements": [],
            }
        ],
        "scene": {"framing_notes": "generator behind Alice", "control_requirements": []},
    }


def _style() -> dict:
    return {
        "id": 3,
        "status": "approved",
        "model_family": "generic",
        "positive_tokens": "clean anime line art",
        "negative_tokens": "photorealistic",
        "lighting": "cinematic warm/cool contrast",
        "render_defaults": {"width": 1024, "height": 1536},
        "assets": [
            {"role": "style_reference", "model_family": "generic", "storage_kind": "local_file"}
        ],
    }


@pytest.mark.parametrize(
    ("compiler", "family"),
    [(AnimaImageSpecCompiler(), "anima"), (ZImageImageSpecCompiler(), "z_image")],
)
def test_compilers_are_deterministic_and_ignore_visual_overrides(compiler, family: str) -> None:
    kwargs = {
        "snapshot": _snapshot(),
        "shot_plan": _shot_plan(),
        "model_profile": {
            "id": 1,
            "family": family,
            "variant": "local",
            "default_render": {"steps": 28},
        },
        "style_profile": _style(),
        "negative_prompt": "text, watermark",
        "generation_mode": GenerationMode.FINAL,
        "source_hash": "source-v1",
    }
    first = compiler.compile(**kwargs)
    second = compiler.compile(**kwargs)

    assert first.spec_hash == second.spec_hash
    assert first.spec == second.spec
    assert "young mechanic with amber eyes" in first.positive_prompt
    assert "navy repair coat" in first.positive_prompt
    assert "EVIL OVERRIDE" not in first.positive_prompt
    assert "EVIL OUTFIT" not in first.positive_prompt


def test_anima_and_z_image_share_truth_but_compile_different_prompts() -> None:
    common = {
        "snapshot": _snapshot(),
        "shot_plan": _shot_plan(),
        "style_profile": _style(),
        "negative_prompt": "text",
        "generation_mode": GenerationMode.FINAL,
        "source_hash": "same-source",
    }
    anima = AnimaImageSpecCompiler().compile(
        **common,
        model_profile={"id": 1, "family": "anima", "default_render": {}},
    )
    z_image = ZImageImageSpecCompiler().compile(
        **common,
        model_profile={"id": 2, "family": "z_image", "default_render": {}},
    )

    assert anima.positive_prompt != z_image.positive_prompt
    assert anima.spec["subjects"][0]["identity"] == z_image.spec["subjects"][0]["identity"]
    assert anima.spec["scene"]["visual_version_id"] == z_image.spec["scene"]["visual_version_id"]


def test_final_rejects_missing_canonical_assets_but_preview_warns() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["identity_assets"] = []
    kwargs = {
        "snapshot": snapshot,
        "shot_plan": _shot_plan(),
        "model_profile": {"id": 1, "family": "anima", "default_render": {}},
        "style_profile": _style(),
        "negative_prompt": "",
        "source_hash": "source",
    }
    preview = AnimaImageSpecCompiler().compile(**kwargs, generation_mode=GenerationMode.PREVIEW)
    assert any(item["code"] == "image_spec.identity_asset_missing" for item in preview.warnings)
    with pytest.raises(ValueError, match="missing canonical conditions"):
        AnimaImageSpecCompiler().compile(**kwargs, generation_mode=GenerationMode.FINAL)
