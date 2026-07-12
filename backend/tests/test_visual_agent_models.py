import pytest
from pydantic import ValidationError

from backend.agents.visual_agent_models import ContinuityEventItem, NormalizedBox


def test_continuity_event_contract_rejects_wrong_target_and_missing_payload() -> None:
    with pytest.raises(ValidationError, match="requires target_type=character"):
        ContinuityEventItem.model_validate(
            {
                "page_no": 1,
                "sequence_no": 1,
                "event_type": "pick_up_prop",
                "target_type": "prop",
                "target_key": "umbrella",
                "payload": {"prop_key": "umbrella"},
            }
        )

    with pytest.raises(ValidationError, match="to_character_key"):
        ContinuityEventItem.model_validate(
            {
                "page_no": 1,
                "sequence_no": 1,
                "event_type": "transfer_prop",
                "target_type": "character",
                "target_key": "alice",
                "payload": {"prop_key": "umbrella"},
            }
        )


def test_normalized_box_rejects_regions_outside_canvas() -> None:
    with pytest.raises(ValidationError, match="inside the normalized canvas"):
        NormalizedBox(x=0.8, y=0.1, width=0.3, height=0.5)
