import pytest

from backend.models.enums import GenerationMode, ImagePromptType
from backend.services.image_spec_compilers import (
    HybridImageSpecCompiler,
    NaturalLanguageImageSpecCompiler,
    TagImageSpecCompiler,
    compiler_for_prompt_type,
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
                    "negative_constraints": "never change eye color",
                },
                "hairstyle": "short black bob",
                "outfit": {
                    "variant_id": 7,
                    "description": "navy repair coat with brass buttons",
                    "assets": [
                        {"id": 2, "role": "outfit_front", "storage_kind": "local_file"}
                    ],
                },
                "accessories": {"description": "red tool belt"},
                "identity_assets": [
                    {"id": 1, "role": "identity_face", "storage_kind": "local_file"},
                    {"id": 99, "role": "lora", "storage_kind": "renderer_locator"},
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
                {"id": 3, "role": "scene_master", "storage_kind": "local_file"}
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
        "positive_tag": "clean anime line art",
        "negative_tag": "photorealistic",
        "positive_natural_language": "Use clean graphic line art.",
        "negative_natural_language": "Do not use photorealistic rendering.",
        "lighting": "cinematic warm/cool contrast",
        "assets": [
            {"id": 4, "role": "style_reference", "storage_kind": "local_file"}
        ],
    }


@pytest.mark.parametrize(
    "prompt_type",
    [ImagePromptType.TAG, ImagePromptType.NATURAL_LANGUAGE, ImagePromptType.HYBRID],
)
def test_compilers_are_deterministic_and_ignore_visual_overrides(
    prompt_type: ImagePromptType,
) -> None:
    compiler = compiler_for_prompt_type(prompt_type)
    kwargs = {
        "snapshot": _snapshot(),
        "shot_plan": _shot_plan(),
        "style_profile": _style(),
        "negative_prompts": {
            "tag": "text, watermark",
            "natural_language": "Avoid text and watermarks.",
        },
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
    assert all(
        asset["role"] != "lora"
        for asset in first.spec["subjects"][0]["identity_assets"]
    )
    assert "lora" not in first.required_capabilities


def test_three_prompt_types_share_truth_and_hybrid_preserves_both_forms() -> None:
    common = {
        "snapshot": _snapshot(),
        "shot_plan": _shot_plan(),
        "style_profile": _style(),
        "negative_prompts": {
            "tag": "text",
            "natural_language": "Avoid text.",
        },
        "generation_mode": GenerationMode.FINAL,
        "source_hash": "same-source",
    }
    tag = TagImageSpecCompiler().compile(**common)
    natural = NaturalLanguageImageSpecCompiler().compile(**common)
    hybrid = HybridImageSpecCompiler().compile(**common)

    assert tag.positive_prompt != natural.positive_prompt
    assert tag.spec["subjects"] == natural.spec["subjects"] == hybrid.spec["subjects"]
    assert hybrid.spec["prompt"]["tag_text"] == tag.positive_prompt
    assert hybrid.spec["prompt"]["natural_language_text"] == natural.positive_prompt
    assert hybrid.positive_prompt == f"{natural.positive_prompt}\n{tag.positive_prompt}"
    assert hybrid.negative_prompt.startswith(natural.negative_prompt)
    assert "\n" in hybrid.negative_prompt


def test_final_rejects_missing_canonical_assets_but_preview_warns() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["identity_assets"] = []
    kwargs = {
        "snapshot": snapshot,
        "shot_plan": _shot_plan(),
        "style_profile": _style(),
        "negative_prompts": {"tag": "", "natural_language": ""},
        "source_hash": "source",
    }
    preview = TagImageSpecCompiler().compile(
        **kwargs,
        generation_mode=GenerationMode.PREVIEW,
    )
    assert any(item["code"] == "image_spec.identity_asset_missing" for item in preview.warnings)
    with pytest.raises(ValueError, match="missing canonical conditions"):
        TagImageSpecCompiler().compile(
            **kwargs,
            generation_mode=GenerationMode.FINAL,
        )
