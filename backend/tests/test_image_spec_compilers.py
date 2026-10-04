from copy import deepcopy

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
            "lighting": "warm desk lamp",
            "weather": "rain",
            "assets": [
                {"id": 3, "role": "scene_master", "storage_kind": "local_file"}
            ],
        },
    }


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_retired_visual_anchors_do_not_affect_new_specs(prompt_type) -> None:
    """旧快照中的退役字段不得改变新规格或任何一种 Prompt。"""
    snapshot = _snapshot()
    legacy = deepcopy(snapshot)
    legacy["characters"][0]["visual_anchors"] = "obsolete character marker"
    legacy["characters"][0]["identity"]["visual_anchors"] = "obsolete identity marker"
    legacy["scene"]["visual_anchors"] = "obsolete scene marker"
    compiler = compiler_for_prompt_type(prompt_type)
    kwargs = dict(shot_plan=_shot_plan(), style_profile=None, negative_prompts={},
                  generation_mode=GenerationMode.FINAL, source_hash="retired-field")
    expected = compiler.compile(snapshot=snapshot, **kwargs)
    actual = compiler.compile(snapshot=legacy, **kwargs)
    assert actual == expected
    assert legacy["scene"]["visual_anchors"] == "obsolete scene marker"


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
    assert tag.spec["reference_plan"] == natural.spec["reference_plan"] == hybrid.spec["reference_plan"]
    assert tag.spec["style"] == natural.spec["style"] == hybrid.spec["style"] == {}
    assert "clean anime line art" not in tag.positive_prompt
    assert "photorealistic" not in natural.negative_prompt
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


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
@pytest.mark.parametrize("explicit_view", [False, True])
def test_back_facing_shot_suppresses_face_description_and_duplicate_view(prompt_type, explicit_view) -> None:
    shot_plan = _shot_plan()
    shot_plan["subjects"][0]["orientation"] = "" if explicit_view else "back toward the camera"
    shot_plan["subjects"][0]["pose"] = "leaning forward" if explicit_view else "rear view, leaning forward"
    if explicit_view:
        shot_plan["subjects"][0]["reference_view"] = "back"
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=_snapshot(),
        shot_plan={**shot_plan, "render_text": False},
        style_profile=_style(),
        negative_prompts={"tag": "", "natural_language": ""},
        generation_mode=GenerationMode.FINAL,
        source_hash="back-facing",
    )

    assert "young mechanic with amber eyes" not in compiled.positive_prompt
    if prompt_type != ImagePromptType.TAG:
        assert "shown strictly from behind" in compiled.positive_prompt
        assert "exactly 1 visible person" in compiled.positive_prompt
    if prompt_type != ImagePromptType.NATURAL_LANGUAGE:
        assert "rear view, face out of frame" in compiled.positive_prompt


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


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
@pytest.mark.parametrize("description,action,pose", [
    ("邮包（投递用），内装小盒", "从斜挎邮包中取出小盒托在掌中", "双手托举半开小盒，指尖轻触盒沿"),
    ("round glasses", "adjusts the glasses while holding a compass", "opens the compass box"),
    ("one silver pocket watch", "holds the pocket watch", "opens the pocket watch with one hand"),
    ("one silver pocket watch (hanging on the chest from a neck chain)",
     "the pocket watch hangs on the chest while she opens a compass box", "holds the compass box below the pocket watch"),
    ("一枚颈链上的银色怀表", "怀表挂在胸前，双手打开罗盘盒", "托着罗盘盒，目光落向怀表"),
])
def test_accessory_rewrite_never_invents_chain_or_moves_an_unhandled_object(prompt_type, description, action, pose):
    snapshot, shot = _snapshot(), _shot_plan()
    snapshot["characters"][0]["accessories"]["description"] = description
    shot["subjects"][0].update(action=action, pose=pose)
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
        generation_mode=GenerationMode.FINAL, source_hash="preserve-unhandled-accessory",
    )
    assert action in compiled.positive_prompt
    assert pose in compiled.positive_prompt
    assert "still-attached chain" not in compiled.positive_prompt
    assert "chest resting position is completely empty" not in compiled.positive_prompt
    assert "same attached accessory" not in compiled.positive_prompt
    assert "同一件已连接配饰" not in compiled.positive_prompt
    if "watch" not in description and "怀表" not in description:
        assert "chain" not in compiled.positive_prompt
        assert "pocket watch" not in compiled.negative_prompt


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_handled_chained_watch_does_not_rewrite_other_accessories(prompt_type):
    snapshot, shot = _snapshot(), _shot_plan()
    snapshot["characters"][0]["accessories"]["description"] = "邮包；银色怀表（悬挂在胸前的颈链上）"
    shot["subjects"][0].update(action="从邮包旁托起怀表", pose="一只手打开怀表")
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
        generation_mode=GenerationMode.FINAL, source_hash="one-chained-accessory",
    )
    assert "从邮包旁托起同一件已连接配饰" in compiled.positive_prompt
    assert "still-attached chain" in compiled.positive_prompt
    assert "chest resting position is completely empty" in compiled.positive_prompt
    assert "邮包" in compiled.positive_prompt
    assert "邮包" in compiled.spec["subjects"][0]["accessories"]["description"]


def test_final_needs_only_page_references_and_does_not_require_outfit_or_style() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["outfit"].pop("variant_id")
    snapshot["characters"][0]["outfit"]["assets"] = []
    snapshot["scene"]["assets"] = []
    shot_plan = _shot_plan()
    shot_plan["scene"]["background_visible"] = False
    compiled = NaturalLanguageImageSpecCompiler().compile(
        snapshot=snapshot, shot_plan=shot_plan, style_profile=None,
        negative_prompts={}, generation_mode=GenerationMode.FINAL, source_hash="minimum",
    )
    assert compiled.warnings == []
    assert [item["owner"]["category"] for item in compiled.spec["reference_plan"]["items"]] == ["character"]
    assert "no visible background" in compiled.positive_prompt
    assert "dense shelves" not in compiled.positive_prompt


def test_explicit_visible_props_drive_prompt_and_strict_readiness() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["held_props"] = ["hidden_key"]
    snapshot["prop_catalog"] = [
        {"key": "hidden_key", "name": "Hidden key", "description": "copper key", "assets": []},
        {"key": "red_cube", "name": "Red cube", "description": "red ceramic cube", "negative_constraints": "never add a handle", "assets": []},
    ]
    shot_plan = _shot_plan()
    shot_plan["subjects"][0]["visible_prop_keys"] = []
    shot_plan["scene"]["visible_prop_keys"] = ["red_cube"]
    common = dict(snapshot=snapshot, shot_plan=shot_plan, style_profile=None, negative_prompts={}, source_hash="props")
    preview = NaturalLanguageImageSpecCompiler().compile(**common, generation_mode=GenerationMode.PREVIEW)
    assert "red ceramic cube" in preview.positive_prompt
    assert "Hidden key" not in preview.positive_prompt
    assert "holding hidden_key" not in preview.positive_prompt
    assert "never add a handle" in preview.negative_prompt
    assert [item["code"] for item in preview.warnings] == ["image_spec.prop_asset_missing"]
    with pytest.raises(ValueError, match="image_spec.prop_asset_missing"):
        NaturalLanguageImageSpecCompiler().compile(**common, generation_mode=GenerationMode.FINAL)


def test_multiple_people_do_not_implicitly_require_regional_condition() -> None:
    snapshot = _snapshot()
    second = {**snapshot["characters"][0], "character_key": "bob", "name": "Bob", "identity_assets": [{"id": 10, "role": "identity_face"}]}
    snapshot["characters"].append(second)
    shot_plan = _shot_plan()
    shot_plan["subjects"].append({**shot_plan["subjects"][0], "character_key": "bob"})
    compiled = TagImageSpecCompiler().compile(snapshot=snapshot, shot_plan=shot_plan, style_profile=None, negative_prompts={}, generation_mode=GenerationMode.FINAL, source_hash="two-people")
    assert "regional_condition" not in compiled.required_capabilities


def _scene_projection_inputs():
    """混合固定环境与可移动目录物，验证实际 Prompt 而非只检查选图列表。"""

    snapshot, shot = _snapshot(), _shot_plan()
    snapshot["prop_catalog"] = [{
        "key": "violet_beacon", "name": "Violet beacon", "description": "a glass violet beacon",
        "assets": [{"id": 21, "role": "prop_reference", "storage_kind": "local_file"}],
    }]
    scene = snapshot["scene"]
    for key in ("name", "display_name", "environment_details", "reference_description", "lighting", "weather", "time"):
        scene[key] = "Room with a visible violet beacon beside an arched window and an oak table"
    scene.update(
        landmarks=["violet beacon", "arched window"],
        color_palette=["violet beacon glow"],
        spatial_relations={"violet_beacon": "on oak table"},
        object_states={"violet_beacon": "on display"},
        light_states={"lighting": "warm light illuminates the violet beacon"},
    )
    shot["subjects"][0].update(action="passes a sealed opaque case", pose="both hands support the shut lid", visible_prop_keys=[])
    shot["scene"].update(
        framing_notes="The arched window is on the east stone wall; an oak table fills the foreground. Warm amber lamplight falls from the left; rain is visible outside. A plain paintbrush lies beside the sealed opaque case; its contents remain concealed.",
        background_visible=True, visible_prop_keys=[],
    )
    return snapshot, shot


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_current_scene_projection_blocks_static_prop_leaks_but_keeps_environment(prompt_type):
    snapshot, shot = _scene_projection_inputs()
    original = deepcopy(snapshot)
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
        generation_mode=GenerationMode.FINAL, source_hash="scene-projection",
    )
    assert "violet beacon" not in compiled.positive_prompt.lower()
    for retained in ("arched window", "east stone wall", "oak table", "Warm amber lamplight", "rain", "paintbrush", "sealed opaque case"):
        assert retained in compiled.positive_prompt
    assert snapshot == original
    assert compiled.spec["scene"]["name"] == original["scene"]["name"]
    assert compiled.spec["scene"]["light_states"] == original["scene"]["light_states"]
    assert compiled.spec["scene"]["props"] == []
    assert all(item["owner"]["category"] != "prop" for item in compiled.spec["reference_plan"]["items"])


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_current_scene_projection_renders_visible_catalog_and_ordinary_props(prompt_type):
    snapshot, shot = _scene_projection_inputs()
    shot["scene"].update(
        visible_prop_keys=["violet_beacon"],
        framing_notes="The arched window and oak table remain under warm amber light. A violet beacon and an ordinary paintbrush rest on the table.",
    )
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
        generation_mode=GenerationMode.FINAL, source_hash="visible-projection",
    )
    assert "a glass violet beacon" in compiled.positive_prompt
    assert "ordinary paintbrush" in compiled.positive_prompt
    assert "warm amber light" in compiled.positive_prompt
    assert [prop["prop_key"] for prop in compiled.spec["scene"]["props"]] == ["violet_beacon"]
    assert [item["asset_id"] for item in compiled.spec["reference_plan"]["items"] if item["owner"]["category"] == "prop"] == [21]


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_hidden_background_does_not_leak_static_lighting_or_scene_objects(prompt_type):
    snapshot, shot = _scene_projection_inputs()
    shot["scene"].update(background_visible=False, framing_notes="Face fills the frame under soft sidelight")
    compiled = compiler_for_prompt_type(prompt_type).compile(
        snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
        generation_mode=GenerationMode.FINAL, source_hash="background-hidden",
    )
    assert "violet beacon" not in compiled.positive_prompt.lower()
    assert "arched window" not in compiled.positive_prompt
    assert "soft sidelight" in compiled.positive_prompt


def test_scene_projection_preserves_shared_forms_and_legacy_compatibility():
    snapshot, shot = _scene_projection_inputs()
    kwargs = dict(snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={}, generation_mode=GenerationMode.FINAL, source_hash="shared-projection")
    tag, natural, hybrid = [compiler_for_prompt_type(kind).compile(**kwargs) for kind in (ImagePromptType.TAG, ImagePromptType.NATURAL_LANGUAGE, ImagePromptType.HYBRID)]
    assert hybrid.positive_prompt == natural.positive_prompt + "\n" + tag.positive_prompt
    assert tag.spec["scene"] == natural.spec["scene"] == hybrid.spec["scene"]
    assert tag.spec["reference_plan"] == natural.spec["reference_plan"] == hybrid.spec["reference_plan"]
    legacy = _shot_plan()  # 历史结构没有显式 visible_prop_keys，维持原有环境渲染。
    compiled = NaturalLanguageImageSpecCompiler().compile(**{**kwargs, "shot_plan": legacy})
    assert "violet beacon" in compiled.positive_prompt.lower()


def test_current_scene_projection_rejects_empty_environment_without_static_fallback():
    snapshot, shot = _scene_projection_inputs()
    shot["scene"]["framing_notes"] = " "
    with pytest.raises(ValueError, match="nonempty framing_notes"):
        NaturalLanguageImageSpecCompiler().compile(
            snapshot=snapshot, shot_plan=shot, style_profile=None, negative_prompts={},
            generation_mode=GenerationMode.FINAL, source_hash="empty-projection",
        )


@pytest.mark.parametrize("prompt_type", list(ImagePromptType))
def test_page_local_states_reach_each_prompt_without_changing_stable_descriptions(prompt_type):
    """同一基准可逐页独立编译；人物、衣物与门窗状态不会污染基准或下一页。"""
    snapshot, first_shot = _snapshot(), _shot_plan()
    # 分段剧情可能在以后才发生，不应被直接拼进本页 Prompt。
    snapshot["characters"][0]["section_context"] = {
        "current_state": "FUTURE_INJURY",
        "temporary_changes": "FUTURE_TORN_SLEEVE",
    }
    original = deepcopy(snapshot)
    first_shot["subjects"][0].update(
        visible_state="rain-soaked coat, rolled sleeves and a fresh scratch on the wrist",
        visible_prop_keys=[],
    )
    first_shot["scene"].update(
        visible_prop_keys=[],
        framing_notes="Workshop with dense shelves under warm lamplight; the wooden door is open",
    )
    second_shot = deepcopy(first_shot)
    second_shot["subjects"][0]["visible_state"] = ""
    second_shot["scene"]["framing_notes"] = "Workshop with dense shelves under warm lamplight; the wooden door is closed"
    compiler = compiler_for_prompt_type(prompt_type)
    kwargs = dict(snapshot=snapshot, style_profile=None, negative_prompts={}, generation_mode=GenerationMode.FINAL)
    first = compiler.compile(**kwargs, shot_plan=first_shot, source_hash="page-one")
    second = compiler.compile(**kwargs, shot_plan=second_shot, source_hash="page-two")

    for compiled in (first, second):
        assert "young mechanic with amber eyes" in compiled.positive_prompt
        assert "short black bob" in compiled.positive_prompt
        assert "navy repair coat with brass buttons" in compiled.positive_prompt
        assert "FUTURE_INJURY" not in compiled.positive_prompt
        assert "FUTURE_TORN_SLEEVE" not in compiled.positive_prompt
        assert compiled.spec["subjects"][0]["identity"]["appearance"] == original["characters"][0]["identity"]["appearance"]
    for component in ("tag_text", "natural_language_text"):
        assert "rain-soaked coat" in first.spec["prompt"][component]
        assert "fresh scratch on the wrist" in first.spec["prompt"][component]
        assert "the wooden door is open" in first.spec["prompt"][component]
        assert "rain-soaked coat" not in second.spec["prompt"][component]
        assert "the wooden door is closed" in second.spec["prompt"][component]
    assert snapshot == original
