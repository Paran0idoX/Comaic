import pytest

from backend.services.visual_state_reducer import VisualStateReducer


def _reducer() -> VisualStateReducer:
    return VisualStateReducer(
        character_baselines={
            "alice": {
                "character_key": "alice",
                "name": "Alice",
                "identity": {"appearance": "black bob hair"},
                "hairstyle": "bob",
                "outfit": {"description": "blue coat", "garment_states": {}, "conditions": {}},
                "accessories": {"states": {}},
                "conditions": {},
                "held_props": [],
            },
            "bob": {
                "character_key": "bob",
                "name": "Bob",
                "identity": {"appearance": "round glasses"},
                "hairstyle": "short",
                "outfit": {"description": "grey shirt", "garment_states": {}, "conditions": {}},
                "accessories": {"states": {}},
                "conditions": {},
                "held_props": [],
            },
        },
        scene_baselines={
            "hall": {
                "scene_key": "hall",
                "name": "Hall",
                "object_states": {"north_door": "closed"},
                "light_states": {"main": "off"},
            },
            "yard": {
                "scene_key": "yard",
                "name": "Yard",
                "object_states": {},
                "light_states": {},
            },
        },
    )


def test_reducer_applies_before_and_after_and_keeps_scene_state() -> None:
    pages = [
        {"page_id": 11, "page_no": 1, "scene_key": "hall", "character_keys": ["alice"]},
        {"page_id": 12, "page_no": 2, "scene_key": "yard", "character_keys": ["alice", "bob"]},
        {"page_id": 13, "page_no": 3, "scene_key": "hall", "character_keys": ["alice", "bob"]},
    ]
    events = [
        {
            "page_no": 1,
            "sequence_no": 1,
            "event_type": "pick_up_prop",
            "target_type": "character",
            "target_key": "alice",
            "timing": "after_page",
            "payload": {"prop_key": "brass_key"},
        },
        {
            "page_no": 1,
            "sequence_no": 2,
            "event_type": "set_door_state",
            "target_type": "scene",
            "target_key": "hall",
            "timing": "after_page",
            "payload": {"door_key": "north_door", "value": "open"},
        },
        {
            "page_no": 2,
            "sequence_no": 1,
            "event_type": "set_clothing_condition",
            "target_type": "character",
            "target_key": "alice",
            "timing": "before_page",
            "payload": {"condition_key": "wet", "value": True},
        },
        {
            "page_no": 2,
            "sequence_no": 2,
            "event_type": "transfer_prop",
            "target_type": "character",
            "target_key": "alice",
            "timing": "after_page",
            "payload": {"prop_key": "brass_key", "to_character_key": "bob"},
        },
        {
            "page_no": 3,
            "sequence_no": 1,
            "event_type": "set_light_state",
            "target_type": "scene",
            "target_key": "hall",
            "timing": "before_page",
            "payload": {"light_key": "main", "value": "on"},
        },
    ]

    snapshots = _reducer().reduce(pages=pages, events=events)

    assert snapshots[0]["characters"][0]["held_props"] == []
    assert snapshots[1]["characters"][0]["held_props"] == ["brass_key"]
    assert snapshots[1]["characters"][0]["outfit"]["conditions"]["wet"] is True
    assert snapshots[2]["characters"][0]["held_props"] == []
    assert snapshots[2]["characters"][1]["held_props"] == ["brass_key"]
    assert snapshots[2]["scene"]["object_states"]["north_door"] == "open"
    assert snapshots[2]["scene"]["light_states"]["main"] == "on"


def test_reducer_rejects_identity_changes_and_invalid_transfers() -> None:
    pages = [{"page_id": 1, "page_no": 1, "scene_key": "hall", "character_keys": ["alice"]}]
    immutable_event = {
        "page_no": 1,
        "sequence_no": 1,
        "event_type": "set_hairstyle",
        "target_type": "character",
        "target_key": "alice",
        "timing": "before_page",
        "payload": {"appearance": "different identity", "value": "long"},
    }
    with pytest.raises(ValueError, match="immutable"):
        _reducer().reduce(pages=pages, events=[immutable_event])

    invalid_transfer = {
        **immutable_event,
        "event_type": "transfer_prop",
        "timing": "after_page",
        "payload": {"prop_key": "missing", "to_character_key": "bob"},
    }
    with pytest.raises(ValueError, match="does not hold"):
        _reducer().reduce(pages=pages, events=[invalid_transfer])
