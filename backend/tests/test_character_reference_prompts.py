"""验证六类参考图的事实投影、正负语义与三种表达；不调用真实模型。"""

from copy import deepcopy
import re
import pytest
from pydantic import ValidationError
from backend.models.enums import ImagePromptType as T, VisualAssetRole as R
from backend.models.reference_visual import ReferenceVisualData
from backend.services.reference_visual_profile_service import validate_data
from backend.services.character_reference_prompt_service import CharacterReferencePromptService
from backend.tests.reference_visual_fakes import fact, profile, VIEWS

ROLES = tuple(R(value) for value in VIEWS)


def character_profile():
    facts = [fact("appearance", "woman", "A woman in her early thirties.", "identity"),
        fact("appearance", "eyes", "Cool eyes and thin lips.", "face", VIEWS[:2]),
        fact("appearance", "nose", "A straight nose in profile.", "face", ["identity_side"]),
        fact("appearance", "body", "A straight, upright body silhouette.", "body", VIEWS[1:]),
        fact("default_hairstyle", "ponytail or bob", "A neat low ponytail.", "head", options=[
            {"natural": "A neat low ponytail.", "tags": ["neat low ponytail"]},
            {"natural": "A neat short bob.", "tags": ["neat short bob"]}]),
        fact("default_hairstyle", "black or brown", "Black hair.", "head", options=[
            {"natural": "Black hair.", "tags": ["black hair"]}, {"natural": "Cool brown hair.", "tags": ["cool brown hair"]}]),
        fact("default_accessories", "glasses", "Round glasses.", "wearable", VIEWS[:3]),
        fact("default_clothing", "coat", "A navy coat and brown boots.", "clothing", VIEWS[1:]),
        fact("negative_constraints", "never a necklace", "A compass worn as a necklace.", "wearable", VIEWS, "forbidden")]
    for item, attribute in zip(facts, ["age", "frontal_features", "side_nose", "silhouette", "hair_style", "hair_color", "glasses", "garments", "compass_necklace"]):
        item["attribute"] = attribute
    return profile("character", facts)


@pytest.mark.parametrize("role", ROLES)
def test_three_expressions_project_selected_facts_and_keep_hybrid_order(role):
    compiler = CharacterReferencePromptService()
    base = character_profile()
    outfit_fact = fact("garment_components_json", "green coat", "A green raincoat and brown boots.", "clothing", VIEWS[1:])
    outfit_fact["attribute"] = "garments"
    watch = fact("accessories_json", "wristwatch", "A wristwatch worn on the wrist.", "wearable", VIEWS[1:])
    watch["attribute"] = "wristwatch"
    profiles = [base, profile("outfit", [outfit_fact, watch], owner_id=2)]
    pairs = {kind: compiler.compile(profiles=profiles, prompt_type=kind, roles=(role,))[role.value] for kind in T}
    for field in ("positive", "negative"):
        assert pairs[T.HYBRID][field] == pairs[T.NATURAL_LANGUAGE][field] + "\n" + pairs[T.TAG][field]
        assert not re.search(r"[\u3400-\u9fff]", pairs[T.HYBRID][field])
        assert "not specified" not in pairs[T.HYBRID][field]
    positive = pairs[T.NATURAL_LANGUAGE]["positive"]
    assert "low ponytail" in positive and "Black hair" in positive
    assert "short bob" not in positive and "brown hair" not in positive
    assert "compass" not in positive
    assert "compass worn as a necklace" in pairs[T.NATURAL_LANGUAGE]["negative"]
    assert "preserve age" not in pairs[T.NATURAL_LANGUAGE]["negative"]
    if role == R.IDENTITY_FACE:
        assert "green raincoat" not in positive and "wristwatch" not in positive and "body silhouette" not in positive
        assert "head-and-shoulders" in positive and positive.count("upper-chest crop") == 1
        assert "Round glasses" in positive
    else:
        assert "green raincoat" in positive and "navy coat" not in positive
        if role != R.IDENTITY_BACK: assert "Round glasses" in positive  # 新腕表不移除眼镜。
    if role == R.IDENTITY_BACK:
        assert "eyes" not in positive.lower() and "nose" not in positive.lower() and "lips" not in positive.lower()
        assert "head faces away" in positive
    if role == R.IDENTITY_SIDE:
        assert "90-degree" in positive and "both eyes" not in positive
        assert "Cool eyes" not in positive


def test_scene_specific_state_overrides_corresponding_attribute_only():
    wall = fact("description", "brick walls", "Brick walls.", "material", ["scene_master"]); wall["attribute"] = "walls"
    daylight = fact("description", "day", "Daylight.", "lighting", ["scene_master"]); daylight["attribute"] = "lighting"
    night = fact("lighting_state_json", "night", "Warm lamps at night.", "lighting", ["scene_master"]); night["attribute"] = "lighting"
    absent = fact("negative_constraints", "no screens", "Modern screens.", "environment", ["scene_master"], "forbidden")
    profiles = [profile("scene_subject", [wall, daylight, absent]), profile("scene_version", [night], owner_id=2)]
    for expression in T:
        result = CharacterReferencePromptService().compile(profiles=profiles, prompt_type=expression, roles=(R.SCENE_MASTER,))["scene_master"]
        assert "Brick walls" in result["positive"] and "Warm lamps at night" in result["positive"]
        assert "Daylight" not in result["positive"] and "Modern screens" not in result["positive"]
        assert "Modern screens" in result["negative"]


def test_single_prop_preserves_exterior_and_does_not_invent_internal_contents():
    exterior = fact("description", "closed bronze case", "A closed bronze watch case.", "shape", ["prop_reference"])
    p = profile("prop_subject", [exterior])
    result = CharacterReferencePromptService().compile(profiles=[p], prompt_type=T.HYBRID, roles=(R.PROP_REFERENCE,))["prop_reference"]
    assert "closed bronze watch case" in result["positive"] and "one object" in result["positive"]
    assert "gears" not in result["positive"] and "people" not in result["positive"]
    assert "invented interior contents" in result["negative"]


@pytest.mark.parametrize("description", ["A silver quadruped robot.", "A fox with orange fur."])
def test_nonhuman_characters_keep_natural_structure(description):
    p = profile("character", [fact("appearance", description, description)], human=False)
    prompts = CharacterReferencePromptService().compile(profiles=[p], prompt_type=T.NATURAL_LANGUAGE, roles=ROLES)
    assert "head-and-shoulders" not in prompts["identity_face"]["positive"]
    for pair in prompts.values():
        assert "standing" not in pair["positive"] and "both feet" not in pair["positive"]
        assert "human" not in pair["positive"] and "coat" not in pair["positive"]


def test_duplicates_and_empty_fields_are_omitted_and_sources_unchanged():
    p = character_profile(); p["data"]["facts"].append(deepcopy(p["data"]["facts"][4])); original = deepcopy(p)
    result = CharacterReferencePromptService().compile(profiles=[p], prompt_type=T.NATURAL_LANGUAGE)["identity_face"]
    assert result["positive"].count("A neat low ponytail.") == 1
    assert "Style:" not in result["positive"] and "not specified" not in result["positive"]
    assert p == original


def test_long_chinese_setting_uses_only_visual_evidence():
    source = {"kind": "character", "fields": {
        "appearance": "三十出头的成年女性，眉眼冷淡，鼻梁挺直，唇形偏薄；身高略高于沈砚或与之接近。第四阶先看表、再整理桌面；第五阶停顿半拍；结尾不再有停顿。",
        "default_hairstyle": "低马尾或利落短发，黑或冷褐发。以上仅为默认，脚本阶段可覆盖。",
        "default_accessories": "深色硬皮记名册；钢笔；金属表带腕表；门卡／钥匙串。"}}
    facts = [fact("appearance", "三十出头的成年女性", "A woman in her early thirties."),
        fact("appearance", "鼻梁挺直，唇形偏薄", "A straight nose and thin lips.", "face", VIEWS[:2]),
        fact("default_hairstyle", "低马尾或利落短发", "A low ponytail.", "head", options=[
            {"natural": "A low ponytail.", "tags": ["low ponytail"]}, {"natural": "A short bob.", "tags": ["short bob"]}]),
        fact("default_hairstyle", "黑或冷褐发", "Black hair.", "head", options=[
            {"natural": "Black hair.", "tags": ["black hair"]}, {"natural": "Cool brown hair.", "tags": ["cool brown hair"]}])]
    facts[2]["attribute"] = "hair_style"; facts[3]["attribute"] = "hair_color"
    data = ReferenceVisualData.model_validate({"human": True, "facts": facts})
    validate_data(data, source, extracted=True)
    result = CharacterReferencePromptService().compile(profiles=[profile("character", facts)], prompt_type=T.HYBRID, roles=ROLES)
    face = result["identity_face"]["positive"]
    assert "woman in her early thirties" in face and "low ponytail" in face and "Black hair" in face
    for forbidden in ("沈砚", "第四阶", "第五阶", "结尾", "名册", "钢笔", "腕表", "门卡", "short bob", "brown hair", "taller", "later", "or "):
        assert forbidden not in face
    assert source["fields"]["default_accessories"].startswith("深色硬皮记名册")


@pytest.mark.parametrize("change", ["no_source", "chinese", "back_face", "face_body", "outfit_identity", "unknown", "default"])
def test_invalid_extraction_rejected_instead_of_raw_fallback(change):
    data = character_profile()["data"]
    source = {"kind": "character", "fields": {"appearance": "woman eyes nose body", "default_hairstyle": "ponytail or bob; black or brown",
        "default_clothing": "coat", "default_accessories": "glasses", "negative_constraints": "never a necklace"}}
    if change == "no_source": data["facts"][0]["source_excerpt"] = "fabrication"
    if change == "chinese": data["facts"][0]["options"][0]["natural"] = "成年女性"
    if change == "back_face": data["facts"][1]["views"].append("identity_back")
    if change == "face_body": data["facts"][3]["views"].append("identity_face")
    if change == "outfit_identity": source["kind"] = "outfit"
    if change == "unknown": data["facts"][0]["options"][0]["natural"] = "not specified"
    if change == "default": data["facts"][4]["default_index"] = 1
    with pytest.raises((ValueError, ValidationError)):
        validate_data(ReferenceVisualData.model_validate(data), source, extracted=True)


def test_explicit_default_is_allowed_and_selected_once():
    data = character_profile()["data"]
    hair = data["facts"][4]; hair.update(default_is_explicit=True, default_index=1, selected=1)
    p = profile("character", data["facts"])
    prompts = CharacterReferencePromptService().compile(profiles=[p], prompt_type=T.TAG, roles=ROLES)
    assert all("short bob" in pair["positive"] and "low ponytail" not in pair["positive"] for pair in prompts.values())


def test_same_attribute_can_have_required_and_forbidden_facts():
    """真实失败中的成年要求与未成年排除应分别进入正负 Prompt。"""
    required = fact("appearance", "adult man", "An adult man.")
    forbidden = fact("negative_constraints", "no minors", "Underage appearance.", polarity="forbidden")
    required["attribute"] = forbidden["attribute"] = "age_presentation"
    data = ReferenceVisualData.model_validate({"human": True, "facts": [required, forbidden]})
    validate_data(data, {"kind": "character", "owner_id": 51,
        "fields": {"appearance": "adult man", "negative_constraints": "no minors"}}, extracted=True)
    pairs = CharacterReferencePromptService().compile(profiles=[profile("character", [required, forbidden])],
        prompt_type=T.NATURAL_LANGUAGE, roles=ROLES)
    for pair in pairs.values():
        assert "An adult man." in pair["positive"]
        assert "Underage appearance." not in pair["positive"]
        assert "Underage appearance." in pair["negative"]


@pytest.mark.parametrize("attribute", ["skin_tone", "skin_color", "skin_texture", "neck_shape", "neck_length"])
def test_visible_skin_and_neck_body_facts_are_allowed_in_face_crop(attribute):
    item = fact("appearance", "cool skin and long neck", "Cool-toned skin and a long neck.", "body", VIEWS[:3])
    item["attribute"] = attribute
    validate_data(ReferenceVisualData.model_validate({"facts": [item]}),
        {"kind": "character", "fields": {"appearance": "cool skin and long neck"}}, extracted=True)
    pair = CharacterReferencePromptService().compile(profiles=[profile("character", [item])],
        prompt_type=T.NATURAL_LANGUAGE, roles=(R.IDENTITY_FACE,))["identity_face"]
    assert "Cool-toned skin" in pair["positive"]


def test_same_polarity_overlap_still_rejected_with_actionable_location():
    item = fact("appearance", "adult man", "An adult man.")
    item["attribute"] = "age_presentation"
    with pytest.raises(ValueError, match=r"character/51 identity.age_presentation.*merge complementary"):
        validate_data(ReferenceVisualData.model_validate({"facts": [item, deepcopy(item)]}),
            {"kind": "character", "owner_id": 51, "fields": {"appearance": "adult man"}}, extracted=True)


@pytest.mark.parametrize("view", ["identity_half_body", "outfit_front", "outfit_back", "outfit_detail", "style_reference"])
def test_visual_schema_does_not_offer_historical_asset_roles(view):
    item = fact("appearance", "adult man", "An adult man.", views=[view])
    with pytest.raises(ValidationError):
        ReferenceVisualData.model_validate({"facts": [item]})
    schema = ReferenceVisualData.model_json_schema()
    assert set(schema["$defs"]["ReferenceProfileView"]["enum"]) == {*VIEWS, "scene_master", "prop_reference"}


def test_outfit_positive_override_preserves_same_attribute_negative_constraint():
    base_coat = fact("default_clothing", "blue coat", "A blue coat.", "clothing", VIEWS[1:])
    absent = fact("negative_constraints", "no torn coat", "A torn coat.", "clothing", VIEWS[1:], "forbidden")
    replacement = fact("garment_components_json", "green coat", "A green coat.", "clothing", VIEWS[1:])
    for item in (base_coat, absent, replacement): item["attribute"] = "torso_garment"
    pair = CharacterReferencePromptService().compile(profiles=[profile("character", [base_coat, absent]),
        profile("outfit", [replacement], owner_id=2)], prompt_type=T.NATURAL_LANGUAGE,
        roles=(R.IDENTITY_FULL_BODY,))["identity_full_body"]
    assert "A green coat." in pair["positive"] and "A blue coat." not in pair["positive"]
    assert "A torn coat." in pair["negative"]
