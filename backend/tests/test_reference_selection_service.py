from copy import deepcopy

import pytest

from backend.services.reference_selection_service import ReferenceSelectionService


def _asset(asset_id: int, role: str, *, version: int = 1, outfit_variant_id=None) -> dict:
    return {"id": asset_id, "role": role, "version": version, "outfit_variant_id": outfit_variant_id, "local_path": f"original-{asset_id}.webp", "mime_type": "image/webp", "width": 400, "height": 600, "sha256": str(asset_id).zfill(64), "storage_kind": "local_file"}


def _character(key="alice", asset_base=0) -> dict:
    return {
        "character_key": key, "outline_character_id": asset_base + 1, "name": key.title(),
        "identity_assets": [_asset(asset_base + index, role) for index, role in enumerate(("identity_face", "identity_half_body", "identity_full_body", "identity_side", "identity_back"), 1)],
        "outfit": {"variant_id": 7, "assets": []}, "held_props": [],
    }


def _snapshot() -> dict:
    return {"characters": [_character()], "scene": {"scene_key": "room", "reference_subject_id": 90, "assets": [_asset(20, "scene_master")], "catalog_assets": [_asset(21, "scene_master", version=9)]}, "prop_catalog": []}


def _plan(view="front", framing="full_body") -> dict:
    return {"camera": {"shot_type": "wide"}, "subjects": [{"character_key": "alice", "reference_view": view, "reference_framing": framing, "depth_order": 1, "visible_prop_keys": []}], "scene": {"visible_prop_keys": [], "background_visible": True}}


@pytest.mark.parametrize("view,framing,roles", [
    ("front", "face", ["identity_face", "identity_half_body", "identity_full_body"]),
    ("front", "half_body", ["identity_half_body", "identity_full_body", "identity_face"]),
    ("front", "full_body", ["identity_full_body", "identity_half_body", "identity_face"]),
    ("side", "full_body", ["identity_side", "identity_full_body", "identity_half_body", "identity_face"]),
    ("back", "full_body", ["identity_back", "identity_full_body", "identity_half_body", "identity_side", "identity_face"]),
])
def test_reference_roles_follow_fixed_fallback_order_before_latest_version(view, framing, roles) -> None:
    snapshot = _snapshot()
    for offset, expected in enumerate(roles):
        remaining = roles[offset:]
        snapshot["characters"][0]["identity_assets"] = [_asset(index + 1, role, version=index + 1) for index, role in enumerate(remaining)]
        selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan(view, framing))
        assert selected["items"][0]["role"] == expected
        assert selected["items"][0]["is_required"] is True
        if offset:
            assert selected["fallbacks"][0]["reason_code"] == "reference.selection.identity_fallback"


def test_unknown_framing_uses_full_body_and_old_camera_view_is_normalized() -> None:
    plan = _plan("unknown", "unknown")
    plan["camera"] = {"shot_type": "unspecified"}
    selected = ReferenceSelectionService.select(snapshot=_snapshot(), shot_plan=plan)
    assert selected["items"][0]["role"] == "identity_full_body"
    plan["subjects"][0]["orientation"] = "背对镜头"
    selected = ReferenceSelectionService.select(snapshot=_snapshot(), shot_plan=plan)
    assert selected["items"][0]["role"] == "identity_back"
    assert not any(item["role"] == "identity_face" for item in selected["items"])


def test_changed_outfit_excludes_marked_old_body_but_unscoped_body_keeps_identity_only_use() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["identity_assets"] = [
        _asset(1, "identity_full_body", version=99, outfit_variant_id=8),
        _asset(2, "identity_full_body", version=2),
        _asset(3, "identity_half_body", outfit_variant_id=7),
        _asset(4, "identity_face"),
    ]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert selected["items"][0]["asset_id"] == 2
    assert selected["items"][0]["purpose"] == "identity"
    assert "confirmed clothing" in selected["items"][0]["reason"]
    assert {item["asset_id"] for item in selected["omitted"] if item["reason_code"] == "reference.selection.outfit_mismatch"} == {1}
    assert selected["fallbacks"][0]["reason_code"] == "reference.selection.outfit_unspecified"


def test_order_is_depth_then_key_for_all_primary_images_then_auxiliary_scene_and_props() -> None:
    snapshot = _snapshot()
    snapshot["characters"] = [_character("alice"), _character("bob", 10)]
    snapshot["prop_catalog"] = [{"id": 55, "key": "key", "name": "Brass key", "assets": [_asset(31, "prop_reference")]}]
    plan = _plan()
    plan["subjects"].append({**plan["subjects"][0], "character_key": "bob", "depth_order": 0})
    plan["scene"]["visible_prop_keys"] = ["key"]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=plan)
    assert [(item["owner"]["key"], item["is_primary"]) for item in selected["items"]] == [("bob", True), ("alice", True), ("bob", False), ("alice", False), ("room", True), ("key", True)]
    assert [item["order"] for item in selected["items"]] == list(range(1, 7))
    reordered = deepcopy(snapshot)
    reordered["characters"].reverse()
    for character in reordered["characters"]:
        character["identity_assets"].reverse()
    assert selected["items"] == ReferenceSelectionService.select(snapshot=reordered, shot_plan=plan)["items"]
    assert selected["items"][0]["local_path"] == "original-13.webp"
    assert selected["items"][0]["width"] == 400


def test_scene_selected_version_has_priority_catalog_fallback_and_hidden_background_omits_both() -> None:
    snapshot = _snapshot()
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "scene"] == [20]
    snapshot["scene"]["assets"] = []
    snapshot["scene"]["reference_subject_key"] = "canonical_room"
    snapshot["scene"]["reference_subject_name"] = "Canonical room"
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "scene"] == [21]
    assert next(item for item in selected["items"] if item["purpose"] == "scene")["owner"] == {"category": "scene", "id": 90, "key": "canonical_room", "name": "Canonical room"}
    plan = _plan()
    plan["scene"]["background_visible"] = False
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=plan)
    assert not any(item["purpose"] == "scene" for item in selected["items"])
    assert selected["warnings"] == []
    assert any(item["reason_code"] == "reference.selection.background_not_visible" for item in selected["omitted"])


def test_visible_catalog_props_only_and_latest_confirmed_variant_are_selected() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["held_props"] = ["hidden"]
    snapshot["prop_catalog"] = [
        {"key": "key", "name": "Key", "assets": [_asset(30, "prop_reference", version=2), _asset(31, "prop_reference", version=2)]},
        {"key": "hidden", "name": "Hidden", "assets": [_asset(32, "prop_reference")]},
        {"key": "missing", "name": "Missing", "assets": []},
    ]
    plan = _plan()
    plan["subjects"][0]["visible_prop_keys"] = ["key"]
    plan["scene"]["visible_prop_keys"] = ["missing", "outside_catalog"]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=plan)
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "prop"] == [31]
    assert {item["code"] for item in selected["warnings"]} == {"image_spec.prop_asset_missing", "reference.selection.prop_unknown"}


def test_back_uses_back_auxiliary_outfit_and_never_adds_face_detail() -> None:
    snapshot = _snapshot()
    snapshot["characters"][0]["outfit"]["assets"] = [_asset(40, "outfit_front", version=10), _asset(41, "outfit_back")]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan("back"))
    assert [item["role"] for item in selected["items"] if item["owner"]["category"] == "character"] == ["identity_back", "outfit_back"]


def test_scene_catalog_generic_images_do_not_include_other_version_or_other_subject() -> None:
    snapshot = _snapshot()
    snapshot["scene"].update(visual_version_id=4, assets=[])
    snapshot["scene"]["catalog_assets"] = [
        {**_asset(21, "scene_master"), "reference_subject_id": 90, "entity_id": None},
        {**_asset(22, "scene_master", version=99), "reference_subject_id": 90, "entity_id": 5},
        {**_asset(23, "scene_master", version=99), "reference_subject_id": 91, "entity_id": None},
    ]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "scene"] == [21]
    assert {item["asset_id"] for item in selected["omitted"] if item["reason_code"] == "reference.selection.scene_scope_mismatch"} == {22, 23}


def test_scene_selected_version_uses_matching_subject_and_legacy_images_only() -> None:
    snapshot = _snapshot()
    snapshot["scene"]["visual_version_id"] = 4
    snapshot["scene"]["assets"] = [
        {**_asset(20, "scene_master", version=1), "reference_subject_id": 90, "entity_id": 4},
        {**_asset(24, "scene_master", version=2), "reference_subject_id": None, "entity_id": 4},
        {**_asset(25, "scene_master", version=99), "reference_subject_id": 91, "entity_id": 4},
        {**_asset(26, "scene_master", version=99), "reference_subject_id": 90, "entity_id": 5},
    ]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "scene"] == [24]
    assert {item["asset_id"] for item in selected["omitted"] if item["reason_code"] == "reference.selection.scene_scope_mismatch"} == {25, 26}
    snapshot["scene"]["assets"] = [snapshot["scene"]["assets"][2]]
    selected = ReferenceSelectionService.select(snapshot=snapshot, shot_plan=_plan())
    assert [item["asset_id"] for item in selected["items"] if item["purpose"] == "scene"] == [21]
