"""以模型/Renderer 替身验证摘要缓存、并发与收费任务的冻结边界。"""

import asyncio
from copy import deepcopy
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from backend.i18n.errors import AppError
from backend.models.comic import ComicProject, OutfitVariant, ReferenceVisualProfile
from backend.models.enums import (ReferenceProfileKind as K, VisualAssetRole as R, ApprovalStatus,
    GenerationTaskStatus, VisualEntityType)
from backend.models.reference_visual import ReferenceVisualData
from backend.services.reference_visual_profile_service import ReferenceVisualProfileService, validate_data
from backend.tests.test_reference_image_service import catalog_fixture, _selection, _bound_scene_version, _face, _image_tool
from backend.tests.test_character_reference_service import reference_fixture, FakeRenderer
from backend.tests.reference_visual_fakes import FakeVisualAgent
from backend.agents.reference_visual_agent import ReferenceVisualAgent as RealReferenceVisualAgent


def refs(profiles):
    return [{key: item[key] for key in ("id", "revision", "source_hash")} for item in profiles]


def test_cache_reuses_identity_across_views_tools_and_sizes(catalog_fixture):
    f = catalog_fixture
    selection = _selection(f, (R.IDENTITY_FACE,))
    first = f["service"].preview_reference_prompts(**selection)
    for role in (R.IDENTITY_FULL_BODY, R.IDENTITY_SIDE, R.IDENTITY_BACK):
        f["service"].preview_reference_prompts(**_selection(f, (role,), tool_preset_id=f["openai_tool"].id,
            sizes={role.value: {"width": 640, "height": 960}}))
    assert len(f["agent_calls"]) == 1
    assert f["agent_calls"][0][1] == []
    assert first["visual_profiles"][0]["revision"] == 1
    assert f["character"].appearance == "young woman with amber eyes and a small cheek scar"


def test_one_call_extracts_identity_and_outfit_then_only_missing_outfit(catalog_fixture):
    f = catalog_fixture
    outfit = OutfitVariant(project_id=f["project"].id, outline_character_id=f["character"].id,
        key="rain", version=1, name="Rain", garment_components_json='["green raincoat"]')
    f["session"].add(outfit); f["session"].commit()
    selection = _selection(f, (R.IDENTITY_FACE, R.IDENTITY_FULL_BODY), outfit_variant_id=outfit.id)
    preview = f["service"].preview_reference_prompts(**selection)
    assert len(f["agent_calls"]) == 1 and len(f["agent_calls"][0][0]) == 2
    assert "green raincoat" in preview["prompts"]["identity_full_body"]["positive"]
    assert "green raincoat" not in preview["prompts"]["identity_face"]["positive"]
    assert "navy trench coat" not in preview["prompts"]["identity_full_body"]["positive"]
    outfit.garment_components_json = '["blue raincoat"]'; f["session"].commit()
    refreshed = f["service"].preview_reference_prompts(**selection)
    assert len(f["agent_calls"]) == 2
    assert [item["kind"] for item in f["agent_calls"][1][0]] == ["outfit"]
    assert f["agent_calls"][1][1][0]["kind"] == "character"
    assert "reference.profile_rebuilt" in refreshed["warnings"]


def test_source_and_format_invalidation_and_force(catalog_fixture):
    f = catalog_fixture; selection = _selection(f)
    first = f["service"].preview_reference_prompts(**selection)
    record = f["session"].get(ReferenceVisualProfile, first["visual_profiles"][0]["id"])
    record.format_version = 0; f["session"].commit()
    second = f["service"].preview_reference_prompts(**selection)
    assert second["visual_profiles"][0]["revision"] == 2
    f["character"].default_hairstyle = "long black braid"; f["session"].commit()
    third = f["service"].preview_reference_prompts(**selection)
    assert third["visual_profiles"][0]["source_hash"] != second["visual_profiles"][0]["source_hash"]
    fourth = f["service"].preview_reference_prompts(**selection, refresh_visual_profiles=True)
    assert fourth["visual_profiles"][0]["revision"] == 4
    assert len(f["agent_calls"]) == 4


def test_manual_edits_and_choices_persist_and_revision_conflicts(catalog_fixture):
    f = catalog_fixture; preview = f["service"].preview_reference_prompts(**_selection(f))
    original = preview["visual_profiles"][0]
    data = deepcopy(original["data"])
    hair = next(fact for fact in data["facts"] if fact["kind"] == "head")
    hair["options"].append({"natural": "short black hair", "tags": ["short black hair"]})
    hair["selected"] = 1
    service = ReferenceVisualProfileService(f["session"])
    changed = service.update(original["id"], original["revision"], ReferenceVisualData.model_validate(data))
    assert changed.revision == 2
    with pytest.raises(AppError) as conflict:
        service.update(original["id"], 1, ReferenceVisualData.model_validate(data))
    assert conflict.value.code == "reference.profile_conflict"
    new_preview = f["service"].preview_reference_prompts(**_selection(f, (R.IDENTITY_FACE, R.IDENTITY_BACK)))
    assert len(f["agent_calls"]) == 1
    for pair in new_preview["prompts"].values():
        assert "short black hair" in pair["positive"] and "short black bob" not in pair["positive"]
    assert f["character"].default_hairstyle == "short black bob"


def test_model_call_has_no_transaction_and_rechecks_source_and_cached_revision(catalog_fixture):
    f = catalog_fixture; project_id, character_id = f["project"].id, f["character"].id
    normalizer = ReferenceVisualProfileService(f["session"], agent_factory=lambda: FakeVisualAgent([], f["session"]))
    profiles, _ = normalizer.prepare(project_id, [(K.CHARACTER, character_id)])
    assert profiles
    factory = sessionmaker(bind=f["session"].bind)
    class RacingAgent(FakeVisualAgent):
        async def extract(self, sources, cached):
            result = await super().extract(sources, cached)
            with factory() as other:
                from backend.models.comic import OutlineCharacter
                other.get(OutlineCharacter, character_id).default_hairstyle = "red braid"
                other.commit()
            return result
    normalizer.agent_factory = RacingAgent
    with pytest.raises(AppError) as stale:
        normalizer.prepare(project_id, [(K.CHARACTER, character_id)], force=True)
    assert stale.value.code == "reference.profile_stale"
    assert normalizer.repo.get(profiles[0]["id"]).revision == 1


def test_delayed_outfit_extraction_cannot_overwrite_edited_identity(catalog_fixture):
    f = catalog_fixture
    first = f["service"].preview_reference_prompts(**_selection(f))["visual_profiles"][0]
    outfit = OutfitVariant(project_id=f["project"].id, outline_character_id=f["character"].id, key="coat", version=1,
        garment_components_json='["green coat"]')
    f["session"].add(outfit); f["session"].commit()
    factory = sessionmaker(bind=f["session"].bind)
    class RacingAgent(FakeVisualAgent):
        async def extract(self, sources, cached):
            result = await super().extract(sources, cached)
            with factory() as other:
                ReferenceVisualProfileService(other).update(first["id"], 1, ReferenceVisualData.model_validate(first["data"]))
            return result
    service = ReferenceVisualProfileService(f["session"], agent_factory=RacingAgent)
    with pytest.raises(AppError) as conflict:
        service.prepare(f["project"].id, [(K.CHARACTER, f["character"].id), (K.OUTFIT, outfit.id)])
    assert conflict.value.code == "reference.profile_conflict"
    assert service.repo.find(f["project"].id, K.OUTFIT, outfit.id) is None


def test_failed_extraction_preserves_profile_without_raw_fallback(catalog_fixture, monkeypatch):
    f = catalog_fixture; first = f["service"].preview_reference_prompts(**_selection(f))
    import backend.agents.reference_visual_agent as module
    class FailingAgent:
        async def extract(self, sources, cached):
            raise RuntimeError("test extraction failure")
    monkeypatch.setattr(module, "ReferenceVisualAgent", FailingAgent)
    with pytest.raises(AppError) as error:
        f["service"].preview_reference_prompts(**_selection(f), refresh_visual_profiles=True)
    assert error.value.code == "reference.profile_extraction_failed"
    record = ReferenceVisualProfileService(f["session"]).repo.get(first["visual_profiles"][0]["id"])
    assert record.revision == 1
    cached = f["service"].preview_reference_prompts(**_selection(f))
    assert cached["prompts"] == first["prompts"]


def test_create_and_resume_freeze_edits_profiles_and_actual_prompt_without_llm(catalog_fixture, monkeypatch):
    f = catalog_fixture; face = _face(f); tool = _image_tool(f)
    selection = _selection(f, (R.IDENTITY_BACK,), tool_preset_id=tool.id)
    preview = f["service"].preview_reference_prompts(**selection)
    prompts = {"identity_back": {"positive": "  手工背面描述\nkeep whitespace  ", "negative": "手工排除"}}
    import backend.agents.reference_visual_agent as agent_module
    monkeypatch.setattr(agent_module, "ReferenceVisualAgent", lambda: pytest.fail("Tasks must not construct a visual agent"))
    task = f["service"].create_reference_task(**selection, candidate_count=2, prompts=prompts,
        visual_profile_refs=refs(preview["visual_profiles"]))
    snapshot = task.subject_snapshot_json
    assert json.loads(snapshot)["visual_profiles"] == preview["visual_profiles"]
    assert json.loads(task.prompt_snapshot_json) == prompts
    spec = json.loads(task.runs[0].applied_spec_json)
    assert spec["prompt"]["positive"].endswith(prompts["identity_back"]["positive"])
    assert spec["reference_inputs"]["prompt_protocol"]["name"] == "reference_generation"
    assert "rear head shape" in spec["prompt"]["positive"]
    assert "this page" not in spec["prompt"]["positive"]
    assert "actions, expressions" not in spec["prompt"]["positive"]
    assert spec["prompt"]["positive"].count("owner character:hero") == 1
    import backend.services.character_reference_service as runtime_module
    renderer = FakeRenderer(on_wait=lambda call: f["service"].suspend_task(task.id) if call == 1 else None)
    monkeypatch.setattr(runtime_module, "backend_for_preset", lambda *a, **k: renderer)
    asyncio.run(f["service"].run_task(task.id))
    assert task.status == GenerationTaskStatus.SUSPENDED
    f["character"].default_hairstyle = "later appearance"; f["session"].commit()
    f["service"].prepare_continue(task.id)
    asyncio.run(f["service"].run_task(task.id))
    assert task.status == GenerationTaskStatus.SUCCEEDED and task.subject_snapshot_json == snapshot
    assert all(s["prompt"] == spec["prompt"] for s, _, _ in renderer.submissions)


def test_stale_source_revision_wrong_owner_and_project_are_rejected(catalog_fixture):
    f = catalog_fixture; selection = _selection(f)
    first = f["service"].preview_reference_prompts(**selection)
    old_refs = refs(first["visual_profiles"])
    args = {**selection, "candidate_count": 1, "prompts": first["prompts"], "visual_profile_refs": old_refs}
    f["character"].appearance += ", older"; f["session"].commit()
    with pytest.raises(AppError) as stale:
        f["service"].create_reference_task(**args)
    assert stale.value.code == "reference.profile_stale"
    fresh = f["service"].preview_reference_prompts(**selection)
    with pytest.raises(AppError): f["service"].create_reference_task(**args)
    args["entity_id"] = f["unused_character"].id
    args["visual_profile_refs"] = refs(fresh["visual_profiles"])
    with pytest.raises(AppError): f["service"].create_reference_task(**args)
    other = ComicProject(title="Other"); f["session"].add(other); f["session"].commit()
    with pytest.raises(AppError): ReferenceVisualProfileService(f["session"]).check_refs(other.id, [(K.CHARACTER, f["character"].id)], old_refs)
    assert f["service"].list_project_tasks(f["project"].id) == []


def test_foreign_changes_are_seen_even_with_existing_orm_identity_cache(catalog_fixture):
    f = catalog_fixture; selection = _selection(f)
    preview = f["service"].preview_reference_prompts(**selection)
    factory = sessionmaker(bind=f["session"].bind)
    with factory() as other:
        from backend.models.comic import OutlineCharacter
        other.get(OutlineCharacter, f["character"].id).appearance = "changed remotely"
        other.commit()
    with pytest.raises(AppError) as stale:
        f["service"].create_reference_task(**selection, candidate_count=1, prompts=preview["prompts"], visual_profile_refs=refs(preview["visual_profiles"]))
    assert stale.value.code == "reference.profile_stale"


def test_batch_stale_last_item_rolls_back_entire_batch(catalog_fixture):
    f = catalog_fixture
    requests = []
    for character in (f["character"], f["unused_character"]):
        selection = _selection(f, entity_id=character.id)
        preview = f["service"].preview_reference_prompts(**selection)
        requests.append({key: value for key, value in {**selection, "candidate_count": 1,
            "prompts": preview["prompts"], "visual_profile_refs": refs(preview["visual_profiles"])}.items() if key != "project_id"})
    f["unused_character"].appearance = "changed"; f["session"].commit()
    with pytest.raises(AppError): f["service"].create_reference_tasks(project_id=f["project"].id, items=requests)
    assert f["service"].list_project_tasks(f["project"].id) == []


def test_scene_cache_is_separate_and_rebinding_invalidates_version(catalog_fixture):
    f = catalog_fixture; subject, scene, version = _bound_scene_version(f)
    selection = _selection(f, (R.SCENE_MASTER,), entity_type=VisualEntityType.SCENE,
        reference_subject_id=subject.id, entity_id=version.id)
    preview = f["service"].preview_reference_prompts(**selection)
    assert [item["kind"] for item in preview["visual_profiles"]] == ["scene_subject", "scene_version"]
    assert len(f["agent_calls"]) == 1 and len(f["agent_calls"][0][0]) == 2
    another = f["subjects"].create(project_id=f["project"].id, entity_type=VisualEntityType.SCENE, name="Other room", description="brick walls", scene_definition_version=1)
    f["subjects"].assign_scene(scene.id, another.id)
    selection["reference_subject_id"] = another.id
    refreshed = f["service"].preview_reference_prompts(**selection)
    assert refreshed["visual_profiles"][1]["revision"] == 2


def test_visual_profile_update_api_cas_and_invalid_evidence(catalog_fixture, monkeypatch):
    f = catalog_fixture
    import backend.api.reference_images as api
    monkeypatch.setattr(api, "SessionLocal", sessionmaker(bind=f["session"].bind))
    app = FastAPI(); app.include_router(api.router); client = TestClient(app)
    payload = {key: value for key, value in _selection(f).items() if key != "project_id"}
    payload["roles"] = ["identity_side"]
    result = client.post(f'/api/reference-images/projects/{f["project"].id}/prompt-preview', json=payload)
    assert result.status_code == 200
    profile = result.json()["visual_profiles"][0]
    update = {"expected_revision": profile["revision"], "data": profile["data"]}
    url = f'/api/reference-images/visual-profiles/{profile["id"]}'
    saved = client.put(url, json=update)
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    conflict = client.put(url, json=update)
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "reference.profile_conflict"
    update["expected_revision"] = 2; update["data"]["facts"][0]["source_excerpt"] = "fabricated evidence"
    invalid = client.put(url, json=update)
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "reference.profile_invalid"


def test_structured_agent_retries_invalid_output_without_text_json_fallback(catalog_fixture):
    f = catalog_fixture
    service = ReferenceVisualProfileService(f["session"])
    source = service.source(f["project"].id, K.CHARACTER, f["character"].id)
    valid = asyncio.run(FakeVisualAgent().extract([source], []))
    invalid = deepcopy(valid.model_dump())
    invalid["profiles"][0]["data"]["facts"][0]["options"][0]["natural"] = "中文未翻译"
    class StructuredStub:
        calls = 0
        async def ainvoke(self, state, config=None):
            self.calls += 1
            if self.calls == 1:
                return {"messages": [{"content": json.dumps(valid.model_dump())}]}
            return {"structured_response": invalid if self.calls == 2 else valid}
    agent = RealReferenceVisualAgent.__new__(RealReferenceVisualAgent)
    agent.agent = StructuredStub()
    assert asyncio.run(agent.extract([source], [])).profiles[0].owner_id == f["character"].id
    assert agent.agent.calls == 3


def test_missing_model_config_returns_explicit_business_error(monkeypatch):
    import backend.llm_clients.factory as factory
    from backend.agents.reference_visual_agent import ReferenceVisualAgent
    def missing(): raise ValueError("LLMConfig API key is missing.")
    monkeypatch.setattr(factory, "get_tool_chat_model", missing)
    with pytest.raises(AppError) as error: ReferenceVisualAgent()
    assert error.value.code == "reference.profile_model_missing"


def test_concurrent_first_extraction_does_not_replace_new_profile(catalog_fixture):
    f = catalog_fixture; factory = sessionmaker(bind=f["session"].bind)
    project_id, character_id = f["project"].id, f["character"].id
    class RacingAgent(FakeVisualAgent):
        async def extract(self, sources, cached):
            result = await super().extract(sources, cached)
            with factory() as other:
                competitor = ReferenceVisualProfileService(other)
                source = competitor.source(project_id, K.CHARACTER, character_id)
                from backend.services.reference_visual_profile_service import source_hash
                competitor.repo.save(project_id=project_id, kind=K.CHARACTER, owner_id=character_id,
                    source_hash=source_hash(source), data=result.profiles[0].data.model_dump(mode="json"), expected_revision=None)
                other.commit()
            return result
    service = ReferenceVisualProfileService(f["session"], agent_factory=RacingAgent)
    with pytest.raises(AppError) as conflict: service.prepare(project_id, [(K.CHARACTER, character_id)])
    assert conflict.value.code == "reference.profile_conflict"
    assert service.repo.find(project_id, K.CHARACTER, character_id).revision == 1
