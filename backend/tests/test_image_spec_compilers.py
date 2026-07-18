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
                "orientation": "three-quarter view toward camera",
                "gaze": "toward the generator",
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


def test_render_text_false_masks_literal_copy_and_enforces_single_frame() -> None:
    snapshot = _snapshot()
    snapshot["scene"]["environment_details"] = (
        "A note says 'SECRET 12345' beside coordinates 121.123, 31.456 on a signboard."
    )
    shot_plan = _shot_plan()
    shot_plan["subjects"][0]["action"] = "reading a label that says 'OPEN 6789'"
    compiled = NaturalLanguageImageSpecCompiler().compile(
        snapshot=snapshot,
        shot_plan={**shot_plan, "render_text": False},
        style_profile=_style(),
        negative_prompts={"tag": "", "natural_language": ""},
        generation_mode=GenerationMode.FINAL,
        source_hash="render-text-false",
    )

    assert "SECRET 12345" not in compiled.positive_prompt
    assert "OPEN 6789" not in compiled.positive_prompt
    assert "abstract illegible" not in compiled.positive_prompt
    assert "illegible digits" not in compiled.positive_prompt
    assert "121.123" not in compiled.positive_prompt
    assert "on a signboard" not in compiled.positive_prompt.lower()
    assert "plain folded paper shown from its blank back" in compiled.positive_prompt
    assert "examine the blank surface" in compiled.positive_prompt
    assert "standalone borderless cinematic splash illustration" in compiled.positive_prompt
    assert "completely unmarked" in compiled.positive_prompt
    assert "multiple panels" in compiled.negative_prompt
    assert "pseudo-text" in compiled.negative_prompt
    assert "Treat this camera and composition as mandatory" in compiled.positive_prompt
    assert "three-quarter view toward camera" in compiled.positive_prompt
    assert "SECRET 12345" in compiled.spec["scene"]["environment_details"]


def test_render_prompt_mentions_accessory_once_and_uses_only_garment_components() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["identity"]["visual_anchors"] += "; red tool belt"
    snapshot["characters"][0]["visual_anchors"] = "red tool belt"
    snapshot["characters"][0]["outfit"].update(
        {
            "description": "navy repair coat, red tool belt",
            "garment_components": ["navy repair coat with brass buttons"],
        }
    )
    compiled = NaturalLanguageImageSpecCompiler().compile(
        snapshot=snapshot,
        shot_plan={**_shot_plan(), "render_text": False},
        style_profile=_style(),
        negative_prompts={"tag": "", "natural_language": ""},
        generation_mode=GenerationMode.FINAL,
        source_hash="single-accessory",
    )

    assert compiled.positive_prompt.count("red tool belt") == 1
    assert "navy repair coat with brass buttons" in compiled.positive_prompt
    assert "never add a second copy" in compiled.negative_prompt


def test_back_facing_shot_suppresses_face_description_and_duplicate_view() -> None:
    shot_plan = _shot_plan()
    shot_plan["subjects"][0]["orientation"] = "back toward the camera"
    shot_plan["subjects"][0]["pose"] = "rear view, leaning forward"
    compiled = NaturalLanguageImageSpecCompiler().compile(
        snapshot=_snapshot(),
        shot_plan={**shot_plan, "render_text": False},
        style_profile=_style(),
        negative_prompts={"tag": "", "natural_language": ""},
        generation_mode=GenerationMode.FINAL,
        source_hash="back-facing",
    )

    assert "young mechanic with amber eyes" not in compiled.positive_prompt
    assert "shown strictly from behind" in compiled.positive_prompt
    assert "exactly 1 visible person" in compiled.positive_prompt


def test_accessory_is_named_once_when_shot_references_same_object_repeatedly() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["accessories"]["description"] = (
        "one silver pocket watch (scratched, hanging on the chest from a neck chain)"
    )
    shot_plan = _shot_plan()
    shot_plan["subjects"][0]["action"] = "holds the pocket watch at chest height"
    shot_plan["subjects"][0]["pose"] = "opens the pocket watch with one hand"
    shot_plan["scene"]["framing_notes"] = "the pocket watch catches the lamp light"
    compiled = NaturalLanguageImageSpecCompiler().compile(
        snapshot=snapshot,
        shot_plan={**shot_plan, "render_text": False},
        style_profile=_style(),
        negative_prompts={"tag": "", "natural_language": ""},
        generation_mode=GenerationMode.FINAL,
        source_hash="one-accessory-entity",
    )

    assert compiled.positive_prompt.lower().count("pocket watch") == 1
    assert "same attached accessory" in compiled.positive_prompt
    assert "appears only in that hand" in compiled.positive_prompt
    assert "chest resting position is completely empty" in compiled.positive_prompt
    assert "hanging on the chest" not in compiled.positive_prompt
    assert "pocket watch" in compiled.spec["shot_plan"]["subjects"][0]["action"]
