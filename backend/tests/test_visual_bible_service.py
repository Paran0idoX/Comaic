from types import SimpleNamespace

import pytest

from backend.models.enums import ModelFamily, VisualAssetRole, VisualEntityType
from backend.services.visual_bible_service import VisualBibleService


class FakeRepository:
    def get_project(self, project_id):
        return SimpleNamespace(id=project_id)

    def get_outline_character(self, character_id):
        return SimpleNamespace(
            id=character_id,
            outline_version=SimpleNamespace(project_id=1),
        )


def test_model_profiles_require_a_registered_compiler_family() -> None:
    service = VisualBibleService(FakeRepository())
    with pytest.raises(ValueError, match="Generic model profiles"):
        service.create_model_profile(name="Generic", family=ModelFamily.GENERIC)


def test_asset_role_and_lora_family_are_validated_before_persistence() -> None:
    service = VisualBibleService(FakeRepository())
    with pytest.raises(ValueError, match="not valid for character"):
        service.register_renderer_asset(
            project_id=1,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=10,
            entity_key=None,
            role=VisualAssetRole.SCENE_MASTER,
            model_family=ModelFamily.GENERIC,
            renderer_locator="scene.png",
        )

    with pytest.raises(ValueError, match="explicit model family"):
        service.register_renderer_asset(
            project_id=1,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=10,
            entity_key=None,
            role=VisualAssetRole.LORA,
            model_family=ModelFamily.GENERIC,
            renderer_locator="identity.safetensors",
            sha256="a" * 64,
        )

    with pytest.raises(ValueError, match="require a sha256"):
        service.register_renderer_asset(
            project_id=1,
            entity_type=VisualEntityType.CHARACTER,
            entity_id=10,
            entity_key=None,
            role=VisualAssetRole.LORA,
            model_family=ModelFamily.ANIMA,
            renderer_locator="identity.safetensors",
        )
