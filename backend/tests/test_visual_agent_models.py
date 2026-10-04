import pytest
from pydantic import ValidationError

from backend.agents.visual_agent_models import NormalizedBox


def test_normalized_box_rejects_regions_outside_canvas() -> None:
    with pytest.raises(ValidationError, match="inside the normalized canvas"):
        NormalizedBox(x=0.8, y=0.1, width=0.3, height=0.5)
