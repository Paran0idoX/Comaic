import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator

from backend.agents.continuity_event_agent import ContinuityEventAgent
from backend.agents.shot_planner_agent import ShotPlannerAgent
from backend.models.comic import (
    ComicPage,
    ContinuityCompilation,
    ImagePromptPreset,
    ImageSpec,
    ModelProfile,
    OutfitVariant,
    PageShotPlan,
    ScriptCharacter,
    ScriptScene,
    StyleProfile,
    VisualAsset,
    VisualStateSnapshot,
)
from backend.models.enums import (
    ApprovalStatus,
    ContinuityEventSource,
    ContinuityEventTiming,
    ContinuityEventType,
    ContinuityTargetType,
    GenerationMode,
    ImagePromptPresetKind,
    ModelFamily,
    ScriptGenerationTaskStatus,
    VisualAssetRole,
    VisualEntityType,
)
from backend.repositories.image_spec_repository import ImageSpecRepository
from backend.services.image_spec_compilers import compiler_for_family
from backend.services.visual_state_reducer import VisualStateReducer
from backend.utils.json_utils import canonical_hash, canonical_json
from backend.utils.prompt_loader import PromptLoader


CONTROL_ROLES = {
    VisualAssetRole.POSE.value: "pose",
    VisualAssetRole.DEPTH.value: "depth",
    VisualAssetRole.CANNY.value: "canny",
    VisualAssetRole.LINEART.value: "lineart",
}


class ImageSpecService:
    """编排连续性事件、确定性状态、ShotPlan 和模型专用 ImageSpec。"""

    PROMPT_VERSION = "1"

    def __init__(self, repository: ImageSpecRepository):
        self.repository = repository

    def ensure_default_presets(self) -> None:
        """为新结构初始化 ShotPlanner Prompt，同时复用现有 Negative Prompt。"""

        if self.repository.get_default_prompt_preset(
            ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT
        ) is None:
            self.repository.session.add(
                ImagePromptPreset(
                    name="Default shot planner",
                    description="Plan camera, subject regions and controls without rewriting visual identity.",
                    kind=ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT,
                    content=PromptLoader.load("shot_planner_prompt.md"),
                    is_default=True,
                )
            )
            self.repository.session.commit()
        if self.repository.get_default_prompt_preset(ImagePromptPresetKind.NEGATIVE_PROMPT) is None:
            self.repository.session.add(
                ImagePromptPreset(
                    name="Default negative prompt",
                    description="Generic negative prompt for structured comic image generation.",
                    kind=ImagePromptPresetKind.NEGATIVE_PROMPT,
                    content="low quality, blurry, bad anatomy, extra fingers, text, watermark",
                    is_default=True,
                )
            )
            self.repository.session.commit()

    async def stream_compile_task(
        self,
        *,
        task_id: int,
        model_profile_ids: list[int],
        primary_model_profile_id: int,
        style_profile_id: int | None,
        shot_planner_preset_id: int | None,
        negative_prompt_preset_id: int | None,
        generation_mode: GenerationMode,
        concurrency: int = 8,
        regenerate_continuity: bool = False,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """流式编译完整任务；视觉真值只计算一次，再为多个模型生成规格。"""

        context = self._prepare_context(
            task_id=task_id,
            model_profile_ids=model_profile_ids,
            primary_model_profile_id=primary_model_profile_id,
            style_profile_id=style_profile_id,
            shot_planner_preset_id=shot_planner_preset_id,
            negative_prompt_preset_id=negative_prompt_preset_id,
        )
        pages: list[ComicPage] = context["pages"]
        yield "start", {
            "task_id": task_id,
            "total_pages": len(pages),
            "model_profile_ids": model_profile_ids,
            "generation_mode": generation_mode.value,
        }

        compilation, reused = await self._compile_continuity(
            context=context,
            regenerate=regenerate_continuity,
        )
        yield "continuity", {
            "compilation_id": compilation.id,
            "source_hash": compilation.source_hash,
            "reused": reused,
            "event_count": len(compilation.events),
            "snapshot_count": len(compilation.snapshots),
        }
        snapshots_by_page = {item.page_id: item for item in compilation.snapshots}
        for page in pages:
            snapshot = snapshots_by_page[page.id]
            yield "snapshot", self._snapshot_payload(snapshot, page)

        normalized_concurrency = max(1, min(concurrency, 20))
        semaphore = asyncio.Semaphore(normalized_concurrency)
        planner = ShotPlannerAgent(system_prompt=context["planner_preset"].content)

        async def plan_page(page: ComicPage) -> tuple[ComicPage, dict[str, Any]]:
            async with semaphore:
                snapshot = snapshots_by_page[page.id]
                snapshot_data = self._loads_object(snapshot.state_json)
                page_data = self._page_payload(page)
                controls = self._available_controls(snapshot_data)
                plan = await planner.plan(
                    page=page_data,
                    snapshot=snapshot_data,
                    available_controls=controls,
                )
                return page, plan

        planned = await asyncio.gather(*(plan_page(page) for page in pages))
        completed_specs = 0
        total_specs = len(pages) * len(context["profiles"])
        for page, plan_data in sorted(planned, key=lambda item: item[0].page_no):
            snapshot = snapshots_by_page[page.id]
            plan_json = canonical_json(plan_data)
            shot_plan = self.repository.add_shot_plan(
                page_id=page.id,
                snapshot_id=snapshot.id,
                planner_preset_id=context["planner_preset"].id,
                plan_json=plan_json,
                plan_hash=self._shot_plan_source_hash(
                    plan=plan_data,
                    planner_preset=context["planner_preset"],
                    planner_model=context["llm_model"],
                ),
                planner_model=context["llm_model"],
                prompt_version=self.PROMPT_VERSION,
            )
            yield "shot_plan", self._shot_plan_payload(shot_plan, page)

            for profile in context["profiles"]:
                spec = self._compile_model_spec(
                    page=page,
                    snapshot=snapshot,
                    shot_plan=shot_plan,
                    model_profile=profile,
                    style_profile=context["style"],
                    style_assets=context["style_assets"],
                    negative_preset=context["negative_preset"],
                    generation_mode=generation_mode,
                )
                if profile.id == primary_model_profile_id:
                    self.repository.update_legacy_prompt_cache(page.id, spec.positive_prompt)
                completed_specs += 1
                yield "image_spec", self._spec_payload(spec, page)
                yield "progress", {
                    "task_id": task_id,
                    "completed": completed_specs,
                    "total": total_specs,
                }
        yield "done", {
            "task_id": task_id,
            "compilation_id": compilation.id,
            "total_pages": len(pages),
            "total_specs": total_specs,
        }

    def list_task_specs(
        self,
        *,
        task_id: int,
        model_profile_id: int | None = None,
    ) -> list[dict[str, Any]]:
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        pages = {page.id: page for page in self.repository.list_task_pages(task_id)}
        return [
            self._spec_payload(spec, pages[spec.page_id])
            for spec in self.repository.list_latest_specs(
                task_id=task_id,
                model_profile_id=model_profile_id,
            )
        ]

    def current_continuity_source_hash(self, task_id: int) -> str:
        """计算当前脚本与获批视觉资产的 hash，生成前用它拒绝过期规格。"""

        context = self._prepare_context(
            task_id=task_id,
            model_profile_ids=[],
            primary_model_profile_id=None,
            style_profile_id=None,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            require_profiles=False,
        )
        return canonical_hash(self._continuity_source_payload(context))

    def current_image_spec_source_hash(self, spec: ImageSpec) -> str:
        """按当前模型/风格/Prompt/编译器配置重算规格来源，用于生成前判定 stale。"""

        profile = self.repository.session.get(ModelProfile, spec.model_profile_id)
        if profile is None:
            raise ValueError(f"ModelProfile not found: {spec.model_profile_id}")
        compiler = compiler_for_family(profile.family)
        if (
            profile.compiler_key != compiler.compiler_key
            or profile.compiler_version != compiler.compiler_version
        ):
            raise ValueError(
                f"ModelProfile compiler does not match family {profile.family.value}."
            )
        style = self.repository.get_style_profile(spec.style_profile_id)
        style_assets: list[dict[str, Any]] = []
        if style is not None:
            style_assets = [
                self._asset_payload(asset)
                for asset in self.repository.list_project_assets(style.project_id, approved_only=True)
                if asset.entity_type == VisualEntityType.STYLE and asset.entity_id == style.id
            ]
        negative_preset = (
            self.repository.session.get(ImagePromptPreset, spec.negative_prompt_preset_id)
            if spec.negative_prompt_preset_id is not None
            else None
        )
        planner_preset = (
            self.repository.session.get(ImagePromptPreset, spec.shot_plan.planner_preset_id)
            if spec.shot_plan.planner_preset_id is not None
            else None
        )
        current_plan_hash = self._shot_plan_source_hash(
            plan=self._loads_object(spec.shot_plan.plan_json),
            planner_preset=planner_preset,
            planner_model=spec.shot_plan.planner_model,
        )
        return self._image_spec_source_hash(
            snapshot_hash=spec.snapshot.state_hash,
            plan_hash=current_plan_hash,
            model_profile=profile,
            style_profile=style,
            style_assets=style_assets,
            negative_preset=negative_preset,
        )

    async def replace_events(
        self,
        *,
        compilation_id: int,
        events: list[dict[str, Any]],
    ) -> ContinuityCompilation:
        """人工校正创建新编译版本；保留系统事件并替换非系统事件。"""

        original = self.repository.get_compilation(compilation_id)
        if original is None:
            raise ValueError(f"ContinuityCompilation not found: {compilation_id}")
        context = self._prepare_context(
            task_id=original.script_task_id,
            model_profile_ids=[],
            primary_model_profile_id=None,
            style_profile_id=None,
            shot_planner_preset_id=None,
            negative_prompt_preset_id=None,
            require_profiles=False,
        )
        # 系统事件来自当前脚本分段和当前获批版本，不能沿用旧 compilation 的快照。
        system_events = self._section_boundary_events(context)
        manual_events = [
            {**event, "source": ContinuityEventSource.MANUAL.value}
            for event in events
        ]
        combined = self._normalize_events(
            system_events + manual_events,
            context=context,
        )
        return self._persist_reduced_compilation(
            context=context,
            source_hash=canonical_hash(self._continuity_source_payload(context)),
            events=combined,
        )

    # Context and continuity -------------------------------------------
    def _prepare_context(
        self,
        *,
        task_id: int,
        model_profile_ids: list[int],
        primary_model_profile_id: int | None,
        style_profile_id: int | None,
        shot_planner_preset_id: int | None,
        negative_prompt_preset_id: int | None,
        require_profiles: bool = True,
    ) -> dict[str, Any]:
        self.ensure_default_presets()
        task = self.repository.get_script_task(task_id)
        if task is None:
            raise ValueError(f"ScriptGenerationTask not found: {task_id}")
        if task.status != ScriptGenerationTaskStatus.SUCCEEDED:
            raise ValueError("ScriptGenerationTask must be succeeded before compiling image specs.")
        pages = [page for page in self.repository.list_task_pages(task_id) if page.summary]
        if not pages:
            raise ValueError(f"Script pages not found for task: {task_id}")
        profiles = self.repository.get_model_profiles(model_profile_ids)
        if require_profiles:
            if len(profiles) != len(model_profile_ids):
                raise ValueError("One or more ModelProfile records were not found.")
            if primary_model_profile_id not in model_profile_ids:
                raise ValueError("primary_model_profile_id must be included in model_profile_ids.")
            disabled = [profile.id for profile in profiles if not profile.is_enabled]
            if disabled:
                raise ValueError(f"ModelProfile must be enabled before compilation: {disabled}")
        style = self.repository.get_style_profile(style_profile_id)
        if style_profile_id is not None and (
            style is None or style.project_id != task.project_id
        ):
            raise ValueError(f"StyleProfile not found for project: {style_profile_id}")
        planner_preset = (
            self.repository.get_prompt_preset(
                shot_planner_preset_id,
                ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT,
            )
            if shot_planner_preset_id is not None
            else self.repository.get_default_prompt_preset(
                ImagePromptPresetKind.SHOT_PLANNER_SYSTEM_PROMPT
            )
        )
        negative_preset = (
            self.repository.get_prompt_preset(
                negative_prompt_preset_id,
                ImagePromptPresetKind.NEGATIVE_PROMPT,
            )
            if negative_prompt_preset_id is not None
            else self.repository.get_default_prompt_preset(
                ImagePromptPresetKind.NEGATIVE_PROMPT
            )
        )
        if planner_preset is None:
            raise ValueError("ShotPlanner prompt preset is required.")
        assets = self.repository.list_project_assets(task.project_id, approved_only=True)
        asset_payloads = [self._asset_payload(asset) for asset in assets]
        assets_by_owner: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for asset in asset_payloads:
            if asset["entity_id"] is not None:
                assets_by_owner[(asset["entity_type"], int(asset["entity_id"]))].append(asset)
        style_assets = (
            assets_by_owner.get((VisualEntityType.STYLE.value, style.id), [])
            if style is not None
            else []
        )
        active_llm = self.repository.get_active_llm_config()
        return {
            "task": task,
            "pages": pages,
            "profiles": profiles,
            "style": style,
            "style_assets": style_assets,
            "planner_preset": planner_preset,
            "negative_preset": negative_preset,
            "assets": assets,
            "asset_payloads": asset_payloads,
            "assets_by_owner": assets_by_owner,
            "outfits": self.repository.list_project_outfits(
                task.project_id, approved_only=True
            ),
            "scenes": self.repository.list_task_scenes(task_id),
            "llm_config_id": active_llm.id if active_llm else None,
            "llm_model": active_llm.default_model if active_llm else None,
        }

    async def _compile_continuity(
        self,
        *,
        context: dict[str, Any],
        regenerate: bool,
    ) -> tuple[ContinuityCompilation, bool]:
        source_payload = self._continuity_source_payload(context)
        source_hash = canonical_hash(source_payload)
        if not regenerate:
            reusable = self.repository.find_reusable_compilation(
                task_id=context["task"].id,
                source_hash=source_hash,
            )
            if reusable is not None:
                return reusable, True
        compilation = self.repository.create_compilation(
            task_id=context["task"].id,
            source_hash=source_hash,
            llm_config_id=context["llm_config_id"],
            llm_model=context["llm_model"],
            prompt_version=self.PROMPT_VERSION,
            reducer_version=VisualStateReducer.VERSION,
        )
        try:
            llm_events = await ContinuityEventAgent().extract(
                pages=[self._page_payload(page) for page in context["pages"]],
                characters=self._character_agent_payloads(context["pages"]),
                scenes=[self._scene_text_payload(scene) for scene in context["scenes"]],
                outfits=[self._outfit_payload(item, []) for item in context["outfits"]],
            )
            system_events = self._section_boundary_events(context)
            events = self._normalize_events(system_events + llm_events, context=context)
            completed = self._persist_reduced_compilation(
                context=context,
                source_hash=source_hash,
                events=events,
                existing_compilation=compilation,
            )
            return completed, False
        except Exception as exc:
            self.repository.fail_compilation(
                compilation,
                error_code="image_spec.continuity_failed",
                error_message=str(exc),
            )
            raise

    def _persist_reduced_compilation(
        self,
        *,
        context: dict[str, Any],
        source_hash: str,
        events: list[dict[str, Any]],
        existing_compilation: ContinuityCompilation | None = None,
    ) -> ContinuityCompilation:
        compilation = existing_compilation or self.repository.create_compilation(
            task_id=context["task"].id,
            source_hash=source_hash,
            llm_config_id=context["llm_config_id"],
            llm_model=context["llm_model"],
            prompt_version=self.PROMPT_VERSION,
            reducer_version=VisualStateReducer.VERSION,
        )
        character_baselines = self._character_baselines(context)
        scene_baselines = self._scene_baselines(context)
        reduced = VisualStateReducer(
            character_baselines=character_baselines,
            scene_baselines=scene_baselines,
        ).reduce(
            pages=[self._reducer_page_payload(page) for page in context["pages"]],
            events=events,
        )
        prop_assets_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for asset in context["asset_payloads"]:
            if (
                asset["entity_type"] == VisualEntityType.PROP.value
                and asset.get("entity_key")
            ):
                prop_assets_by_key[str(asset["entity_key"])].append(asset)
        for page_state in reduced:
            for character_state in page_state["characters"]:
                character_state["held_prop_assets"] = [
                    {
                        "prop_key": prop_key,
                        "assets": prop_assets_by_key.get(prop_key, []),
                    }
                    for prop_key in character_state.get("held_props", [])
                ]
        scene_version_by_key = {
            scene.scene_key: (
                scene.selected_visual_version.id
                if scene.selected_visual_version is not None
                and scene.selected_visual_version.status == ApprovalStatus.APPROVED
                else None
            )
            for scene in context["scenes"]
        }
        snapshots = []
        for value in reduced:
            state_json = canonical_json(value)
            snapshots.append(
                {
                    "page_id": value["page_id"],
                    "page_no": value["page_no"],
                    "scene_visual_version_id": scene_version_by_key.get(
                        value["scene"]["scene_key"]
                    ),
                    "state_json": state_json,
                    "state_hash": canonical_hash(value),
                    "warnings_json": "[]",
                }
            )
        stored_events = [
            {
                **event,
                "payload_json": canonical_json(event.get("payload") or {}),
            }
            for event in events
        ]
        self.repository.complete_compilation(
            compilation=compilation,
            events=stored_events,
            snapshots=snapshots,
        )
        result = self.repository.get_compilation(compilation.id)
        if result is None:
            raise RuntimeError("Continuity compilation disappeared after commit.")
        return result

    # Baselines and events ---------------------------------------------
    def _character_baselines(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        assets_by_owner = context["assets_by_owner"]
        baselines: dict[str, dict[str, Any]] = {}
        for page in context["pages"]:
            for character in page.visual_characters:
                key = character.character_key
                if key in baselines:
                    continue
                outline = character.outline_character
                if outline is None:
                    raise ValueError(f"ScriptCharacter has no outline baseline: {key}")
                baselines[key] = {
                    "character_key": key,
                    "outline_character_id": outline.id,
                    "name": character.name or outline.name,
                    "identity": {
                        "role": outline.role,
                        "background": outline.background,
                        "appearance": outline.appearance,
                        "visual_anchors": outline.visual_anchors,
                        "negative_constraints": outline.negative_constraints,
                    },
                    "hairstyle": outline.default_hairstyle,
                    "outfit": {
                        "variant_id": None,
                        "key": "",
                        "name": "",
                        "description": outline.default_clothing,
                        "garment_components": [],
                        "layer_order": [],
                        "colors": [],
                        "materials": [],
                        "patterns": [],
                        "accessories": [],
                        "trigger_tokens": [],
                        "negative_constraints": "",
                        "garment_states": {},
                        "conditions": {},
                        "assets": [],
                    },
                    "accessories": {
                        "description": outline.default_accessories,
                        "states": {},
                    },
                    "conditions": {},
                    "held_props": [],
                    "visual_anchors": character.visual_anchors,
                    "negative_constraints": character.negative_constraints,
                    "identity_assets": assets_by_owner.get(
                        (VisualEntityType.CHARACTER.value, outline.id), []
                    ),
                }
        return baselines

    def _scene_baselines(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        assets_by_owner = context["assets_by_owner"]
        result: dict[str, dict[str, Any]] = {}
        for scene in context["scenes"]:
            version = scene.selected_visual_version
            approved_version = (
                version if version is not None and version.status == ApprovalStatus.APPROVED else None
            )
            result[scene.scene_key] = {
                "scene_key": scene.scene_key,
                "script_scene_id": scene.id,
                "name": scene.name,
                "location_type": scene.location_type,
                "time": scene.time_of_day,
                "lighting": scene.lighting,
                "weather": scene.weather,
                "environment_details": scene.environment_details,
                "color_palette": self._loads_list(approved_version.color_palette_json)
                if approved_version
                else scene.color_palette,
                "visual_anchors": scene.visual_anchors,
                "negative_constraints": scene.negative_constraints,
                "visual_version_id": approved_version.id if approved_version else None,
                "landmarks": self._loads_list(approved_version.landmarks_json)
                if approved_version
                else [],
                "spatial_relations": self._loads_object(approved_version.spatial_relations_json)
                if approved_version
                else {},
                "object_states": self._loads_object(approved_version.object_states_json)
                if approved_version
                else {},
                "light_states": self._loads_object(approved_version.lighting_state_json)
                if approved_version
                else {},
                "camera_presets": self._loads_list(approved_version.camera_presets_json)
                if approved_version
                else [],
                "assets": assets_by_owner.get(
                    (VisualEntityType.SCENE.value, approved_version.id), []
                )
                if approved_version
                else [],
            }
        return result

    def _section_boundary_events(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        last_signature: dict[str, tuple[Any, ...]] = {}
        outfit_assets = context["assets_by_owner"]
        for page in context["pages"]:
            for character in sorted(page.visual_characters, key=lambda item: item.character_key):
                outfit = (
                    character.outfit_variant
                    if character.outfit_variant is not None
                    and character.outfit_variant.status == ApprovalStatus.APPROVED
                    else None
                )
                outline = character.outline_character
                effective_hairstyle = character.current_hairstyle or (
                    outline.default_hairstyle if outline else ""
                )
                effective_clothing = character.current_clothing or (
                    outline.default_clothing if outline else ""
                )
                effective_accessories = character.current_accessories or (
                    outline.default_accessories if outline else ""
                )
                signature = (
                    effective_hairstyle,
                    outfit.id if outfit else None,
                    effective_clothing,
                    effective_accessories,
                    character.current_state,
                    character.visual_anchors,
                    character.negative_constraints,
                )
                if last_signature.get(character.character_key) == signature:
                    continue
                last_signature[character.character_key] = signature
                if effective_hairstyle:
                    events.append(
                        self._system_event(
                            page.page_no,
                            ContinuityEventType.SET_HAIRSTYLE,
                            character.character_key,
                            {"value": effective_hairstyle},
                        )
                    )
                outfit_payload = (
                    self._outfit_state_payload(
                        outfit,
                        outfit_assets.get(
                            (VisualEntityType.OUTFIT.value, outfit.id), []
                        ),
                    )
                    if outfit
                    else {
                        "outfit_variant_id": None,
                        "outfit_key": "",
                        "name": "",
                        "description": effective_clothing,
                        "garment_components": [],
                        "layer_order": [],
                        "colors": [],
                        "materials": [],
                        "patterns": [],
                        "accessories": [],
                        "trigger_tokens": [],
                        "negative_constraints": "",
                        "assets": [],
                    }
                )
                outfit_payload["character_negative_constraints"] = (
                    character.negative_constraints
                )
                outfit_payload["character_visual_anchors"] = character.visual_anchors
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_OUTFIT,
                        character.character_key,
                        outfit_payload,
                    )
                )
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_ACCESSORY,
                        character.character_key,
                        {
                            "accessory_key": "__description__",
                            "value": effective_accessories,
                        },
                    )
                )
                events.append(
                    self._system_event(
                        page.page_no,
                        ContinuityEventType.SET_CHARACTER_CONDITION,
                        character.character_key,
                        {
                            "condition_key": "section_state",
                            "value": character.current_state,
                        },
                    )
                )
        return events

    @staticmethod
    def _system_event(
        page_no: int,
        event_type: ContinuityEventType,
        target_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "page_no": page_no,
            "sequence_no": 0,
            "event_type": event_type.value,
            "target_type": ContinuityTargetType.CHARACTER.value,
            "target_key": target_key,
            "timing": ContinuityEventTiming.BEFORE_PAGE.value,
            "payload": payload,
            "source": ContinuityEventSource.SYSTEM.value,
        }

    def _normalize_events(
        self,
        events: list[dict[str, Any]],
        *,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        pages_by_no = {page.page_no: page for page in context["pages"]}
        character_keys = {
            character.character_key
            for page in context["pages"]
            for character in page.visual_characters
        }
        scene_keys = {scene.scene_key for scene in context["scenes"]}
        outfits_by_id = {item.id: item for item in context["outfits"]}
        assets_by_owner = context["assets_by_owner"]
        normalized: list[dict[str, Any]] = []
        for raw in events:
            page_no = int(raw.get("page_no", 0))
            if page_no not in pages_by_no:
                raise ValueError(f"Continuity event page_no not found: {page_no}")
            event_type = ContinuityEventType(raw["event_type"])
            target_type = ContinuityTargetType(raw["target_type"])
            target_key = str(raw.get("target_key", "")).strip()
            if target_type == ContinuityTargetType.CHARACTER and target_key not in character_keys:
                raise ValueError(f"Continuity character target not found: {target_key}")
            if target_type == ContinuityTargetType.SCENE and target_key not in scene_keys:
                raise ValueError(f"Continuity scene target not found: {target_key}")
            source = ContinuityEventSource(
                raw.get("source", ContinuityEventSource.LLM.value)
            )
            payload = dict(raw.get("payload") or {})
            if event_type == ContinuityEventType.SET_OUTFIT and payload.get("outfit_variant_id"):
                variant_id = int(payload["outfit_variant_id"])
                variant = outfits_by_id.get(variant_id)
                if variant is None:
                    raise ValueError(f"Continuity outfit variant not found: {variant_id}")
                payload.update(
                    self._outfit_state_payload(
                        variant,
                        assets_by_owner.get(
                            (VisualEntityType.OUTFIT.value, variant.id), []
                        ),
                    )
                )
            elif (
                event_type == ContinuityEventType.SET_OUTFIT
                and source != ContinuityEventSource.SYSTEM
            ):
                # LLM/人工事件不能注入资产或角色锚点；无获批 variant 时只保留文字变化。
                payload = {
                    "outfit_variant_id": None,
                    "outfit_key": str(payload.get("outfit_key", "")).strip(),
                    "description": str(payload.get("description", "")).strip(),
                    "assets": [],
                }
            if source != ContinuityEventSource.SYSTEM:
                payload.pop("character_visual_anchors", None)
                payload.pop("character_negative_constraints", None)
            normalized.append(
                {
                    "page_no": page_no,
                    "sequence_no": int(raw.get("sequence_no", 0)),
                    "event_type": event_type.value,
                    "target_type": target_type.value,
                    "target_key": target_key,
                    "timing": ContinuityEventTiming(
                        raw.get("timing", ContinuityEventTiming.AFTER_PAGE.value)
                    ).value,
                    "payload": payload,
                    "source": source.value,
                }
            )
        source_order = {"system": 0, "manual": 1, "llm": 2}
        timing_order = {"before_page": 0, "after_page": 1}
        normalized.sort(
            key=lambda item: (
                item["page_no"],
                timing_order[item["timing"]],
                source_order[item["source"]],
                item["sequence_no"],
                item["event_type"],
            )
        )
        counters: dict[int, int] = defaultdict(int)
        for item in normalized:
            counters[item["page_no"]] += 1
            item["sequence_no"] = counters[item["page_no"]]
        return normalized

    # Model specs -------------------------------------------------------
    def _compile_model_spec(
        self,
        *,
        page: ComicPage,
        snapshot: VisualStateSnapshot,
        shot_plan: PageShotPlan,
        model_profile: ModelProfile,
        style_profile: StyleProfile | None,
        style_assets: list[dict[str, Any]],
        negative_preset: ImagePromptPreset | None,
        generation_mode: GenerationMode,
    ) -> ImageSpec:
        snapshot_data = self._loads_object(snapshot.state_json)
        plan_data = self._loads_object(shot_plan.plan_json)
        profile_data = self._model_profile_payload(model_profile)
        style_data = (
            self._style_payload(style_profile, style_assets)
            if style_profile is not None
            else None
        )
        combined_source_hash = self._image_spec_source_hash(
            snapshot_hash=snapshot.state_hash,
            plan_hash=shot_plan.plan_hash,
            model_profile=model_profile,
            style_profile=style_profile,
            style_assets=style_assets,
            negative_preset=negative_preset,
        )
        compiler = compiler_for_family(model_profile.family)
        if (
            model_profile.compiler_key != compiler.compiler_key
            or model_profile.compiler_version != compiler.compiler_version
        ):
            raise ValueError(
                f"ModelProfile compiler does not match family {model_profile.family.value}."
            )
        compiled = compiler.compile(
            snapshot=snapshot_data,
            shot_plan=plan_data,
            model_profile=profile_data,
            style_profile=style_data,
            negative_prompt=negative_preset.content if negative_preset else "",
            generation_mode=generation_mode,
            source_hash=combined_source_hash,
        )
        return self.repository.add_image_spec(
            page_id=page.id,
            snapshot_id=snapshot.id,
            shot_plan_id=shot_plan.id,
            model_profile_id=model_profile.id,
            style_profile_id=style_profile.id if style_profile else None,
            negative_prompt_preset_id=negative_preset.id if negative_preset else None,
            generation_mode=generation_mode,
            spec_json=canonical_json(compiled.spec),
            positive_prompt=compiled.positive_prompt,
            negative_prompt=compiled.negative_prompt,
            required_capabilities_json=canonical_json(compiled.required_capabilities),
            warnings_json=canonical_json(compiled.warnings),
            source_hash=combined_source_hash,
            spec_hash=compiled.spec_hash,
            compiler_key=compiler.compiler_key,
            compiler_version=compiler.compiler_version,
        )

    # Payload helpers ---------------------------------------------------
    def _image_spec_source_hash(
        self,
        *,
        snapshot_hash: str,
        plan_hash: str,
        model_profile: ModelProfile,
        style_profile: StyleProfile | None,
        style_assets: list[dict[str, Any]],
        negative_preset: ImagePromptPreset | None,
    ) -> str:
        """完整来源 Hash 包含模型配置、编译器、风格资产和负向 Prompt 版本。"""

        compiler = compiler_for_family(model_profile.family)
        return canonical_hash(
            {
                "snapshot_hash": snapshot_hash,
                "plan_hash": plan_hash,
                "model_profile": self._model_profile_payload(model_profile),
                "compiler": {
                    "key": compiler.compiler_key,
                    "version": compiler.compiler_version,
                },
                "style": (
                    self._style_payload(style_profile, style_assets)
                    if style_profile is not None
                    else None
                ),
                "negative_prompt_preset": (
                    {
                        "id": negative_preset.id,
                        "kind": negative_preset.kind.value,
                        "content_hash": canonical_hash(negative_preset.content),
                    }
                    if negative_preset is not None
                    else None
                ),
            }
        )

    def _shot_plan_source_hash(
        self,
        *,
        plan: dict[str, Any],
        planner_preset: ImagePromptPreset | None,
        planner_model: str | None,
    ) -> str:
        """镜头计划 Hash 同时锁定计划内容和产生它的 Agent/Prompt/模型。"""

        return canonical_hash(
            {
                "plan": plan,
                "planner_preset": (
                    {
                        "id": planner_preset.id,
                        "kind": planner_preset.kind.value,
                        "content_hash": canonical_hash(planner_preset.content),
                    }
                    if planner_preset is not None
                    else None
                ),
                "agent": {
                    "key": "shot_planner_agent",
                    "version": ShotPlannerAgent.VERSION,
                    "prompt_version": self.PROMPT_VERSION,
                    "llm_model": planner_model,
                },
            }
        )

    def _continuity_source_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "task_id": context["task"].id,
            "pages": [self._page_payload(page) for page in context["pages"]],
            "characters": self._character_agent_payloads(context["pages"]),
            "scenes": [self._scene_source_payload(scene) for scene in context["scenes"]],
            "outfits": [
                self._outfit_payload(
                    item,
                    context["assets_by_owner"].get(
                        (VisualEntityType.OUTFIT.value, item.id), []
                    ),
                )
                for item in context["outfits"]
            ],
            "assets": context["asset_payloads"],
            "agent": {
                "key": "continuity_event_agent",
                "version": ContinuityEventAgent.VERSION,
                "prompt_hash": canonical_hash(
                    PromptLoader.load("continuity_event_prompt.md")
                ),
                "llm_config_id": context["llm_config_id"],
                "llm_model": context["llm_model"],
            },
            "prompt_version": self.PROMPT_VERSION,
            "reducer_version": VisualStateReducer.VERSION,
        }

    @staticmethod
    def _page_payload(page: ComicPage) -> dict[str, Any]:
        return {
            "page_id": page.id,
            "page_no": page.page_no,
            "section_no": page.section.section_no if page.section else None,
            "scene_key": page.script_scene.scene_key if page.script_scene else "",
            "character_keys": sorted(
                character.character_key for character in page.visual_characters
            ),
            "summary": page.summary or "",
            "characters": page.characters or "",
            "clothing": page.clothing or "",
            "scene": page.scene or "",
            "composition": page.composition or "",
            "character_action": page.character_action or "",
            # dialogue 仅作为 ShotPlanner 理解剧情的上下文，编译器不会写进 Prompt。
            "dialogue": page.dialogue or "无",
        }

    @staticmethod
    def _reducer_page_payload(page: ComicPage) -> dict[str, Any]:
        return {
            "page_id": page.id,
            "page_no": page.page_no,
            "scene_key": page.script_scene.scene_key if page.script_scene else "",
            "character_keys": sorted(
                character.character_key for character in page.visual_characters
            ),
        }

    @staticmethod
    def _character_agent_payloads(pages: list[ComicPage]) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        for page in pages:
            for character in page.visual_characters:
                if character.id in seen:
                    continue
                seen[character.id] = {
                    "character_key": character.character_key,
                    "name": character.name,
                    "section_no": character.section.section_no,
                    "current_hairstyle": character.current_hairstyle,
                    "current_clothing": character.current_clothing,
                    "current_accessories": character.current_accessories,
                    "current_state": character.current_state,
                    "temporary_changes": character.temporary_changes,
                    "outfit_variant_id": character.outfit_variant_id,
                }
        return list(seen.values())

    @staticmethod
    def _scene_text_payload(scene: ScriptScene) -> dict[str, Any]:
        return {
            "scene_key": scene.scene_key,
            "name": scene.name,
            "time": scene.time_of_day,
            "weather": scene.weather,
            "visual_anchors": scene.visual_anchors,
        }

    def _scene_source_payload(self, scene: ScriptScene) -> dict[str, Any]:
        payload = self._scene_text_payload(scene)
        payload.update(
            {
                "lighting": scene.lighting,
                "environment_details": scene.environment_details,
                "color_palette": scene.color_palette,
                "negative_constraints": scene.negative_constraints,
                "selected_visual_version": (
                    {
                        "id": scene.selected_visual_version.id,
                        "version": scene.selected_visual_version.version,
                        "status": scene.selected_visual_version.status.value,
                        "landmarks": self._loads_list(
                            scene.selected_visual_version.landmarks_json
                        ),
                        "spatial_relations": self._loads_object(
                            scene.selected_visual_version.spatial_relations_json
                        ),
                        "camera_presets": self._loads_list(
                            scene.selected_visual_version.camera_presets_json
                        ),
                        "object_states": self._loads_object(
                            scene.selected_visual_version.object_states_json
                        ),
                        "color_palette": self._loads_list(
                            scene.selected_visual_version.color_palette_json
                        ),
                        "lighting_state": self._loads_object(
                            scene.selected_visual_version.lighting_state_json
                        ),
                    }
                    if scene.selected_visual_version
                    else None
                ),
            }
        )
        return payload

    def _outfit_payload(
        self,
        item: OutfitVariant,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "outline_character_id": item.outline_character_id,
            "key": item.key,
            "version": item.version,
            "name": item.name,
            "status": item.status.value,
            "garment_components": self._loads_list(item.garment_components_json),
            "layer_order": self._loads_list(item.layer_order_json),
            "colors": self._loads_list(item.colors_json),
            "materials": self._loads_list(item.materials_json),
            "patterns": self._loads_list(item.patterns_json),
            "accessories": self._loads_list(item.accessories_json),
            "trigger_tokens": self._loads_list(item.trigger_tokens_json),
            "negative_constraints": item.negative_constraints,
            "assets": assets,
        }

    def _outfit_description(self, item: OutfitVariant) -> str:
        values = (
            self._loads_list(item.garment_components_json)
            + self._loads_list(item.colors_json)
            + self._loads_list(item.materials_json)
            + self._loads_list(item.patterns_json)
            + self._loads_list(item.accessories_json)
        )
        return ", ".join(str(value) for value in values if str(value).strip()) or item.name

    def _outfit_state_payload(
        self,
        item: OutfitVariant,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把获批服装版本展开为 reducer 可锁定的完整结构。"""

        payload = self._outfit_payload(item, assets)
        return {
            "outfit_variant_id": item.id,
            "outfit_key": item.key,
            "name": item.name,
            "description": self._outfit_description(item),
            "garment_components": payload["garment_components"],
            "layer_order": payload["layer_order"],
            "colors": payload["colors"],
            "materials": payload["materials"],
            "patterns": payload["patterns"],
            "accessories": payload["accessories"],
            "trigger_tokens": payload["trigger_tokens"],
            "negative_constraints": item.negative_constraints,
            "assets": assets,
        }

    @staticmethod
    def _asset_payload(asset: VisualAsset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "entity_type": asset.entity_type.value,
            "entity_id": asset.entity_id,
            "entity_key": asset.entity_key,
            "role": asset.role.value,
            "model_family": asset.model_family.value,
            "storage_kind": asset.storage_kind.value,
            "local_path": asset.local_path,
            "renderer_locator": asset.renderer_locator,
            "sha256": asset.sha256,
            "version": asset.version,
        }

    def _style_payload(
        self,
        item: StyleProfile,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "key": item.key,
            "version": item.version,
            "name": item.name,
            "model_family": item.model_family.value,
            "positive_tokens": item.positive_tokens,
            "negative_tokens": item.negative_tokens,
            "color_palette": self._loads_list(item.color_palette_json),
            "lighting": item.lighting,
            "render_defaults": self._loads_object(item.render_defaults_json),
            "status": item.status.value,
            "assets": assets,
        }

    def _model_profile_payload(self, item: ModelProfile) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "family": item.family.value,
            "variant": item.variant,
            "checkpoint_name": item.checkpoint_name,
            "checkpoint_hash": item.checkpoint_hash,
            "component_manifest": self._loads_object(item.component_manifest_json),
            "default_render": self._loads_object(item.default_render_json),
            "compiler_key": item.compiler_key,
            "compiler_version": item.compiler_version,
        }

    @staticmethod
    def _available_controls(snapshot: dict[str, Any]) -> list[str]:
        roles = {
            asset.get("role")
            for asset in (snapshot.get("scene") or {}).get("assets", [])
        }
        for character in snapshot.get("characters", []):
            roles.update(asset.get("role") for asset in character.get("identity_assets", []))
            roles.update(
                asset.get("role") for asset in (character.get("outfit") or {}).get("assets", [])
            )
        controls = {CONTROL_ROLES[role] for role in roles if role in CONTROL_ROLES}
        if len(snapshot.get("characters", [])) > 1:
            controls.add("regional_condition")
        return sorted(controls)

    @staticmethod
    def _snapshot_payload(snapshot: VisualStateSnapshot, page: ComicPage) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "state": ImageSpecService._loads_object(snapshot.state_json),
            "state_hash": snapshot.state_hash,
            "warnings": ImageSpecService._loads_list(snapshot.warnings_json),
            "created_at": snapshot.created_at.isoformat(),
        }

    @staticmethod
    def _shot_plan_payload(plan: PageShotPlan, page: ComicPage) -> dict[str, Any]:
        return {
            "id": plan.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "plan": ImageSpecService._loads_object(plan.plan_json),
            "plan_hash": plan.plan_hash,
            "created_at": plan.created_at.isoformat(),
        }

    @staticmethod
    def _spec_payload(spec: ImageSpec, page: ComicPage) -> dict[str, Any]:
        return {
            "id": spec.id,
            "page_id": page.id,
            "page_no": page.page_no,
            "snapshot_id": spec.snapshot_id,
            "shot_plan_id": spec.shot_plan_id,
            "model_profile_id": spec.model_profile_id,
            "model_family": spec.model_profile.family.value,
            "generation_mode": spec.generation_mode.value,
            "spec": ImageSpecService._loads_object(spec.spec_json),
            "positive_prompt": spec.positive_prompt,
            "negative_prompt": spec.negative_prompt,
            "required_capabilities": ImageSpecService._loads_list(
                spec.required_capabilities_json
            ),
            "warnings": ImageSpecService._loads_list(spec.warnings_json),
            "source_hash": spec.source_hash,
            "spec_hash": spec.spec_hash,
            "compiler_key": spec.compiler_key,
            "compiler_version": spec.compiler_version,
            "created_at": spec.created_at.isoformat(),
        }

    @staticmethod
    def _event_from_orm(item) -> dict[str, Any]:
        return {
            "page_no": item.page.page_no,
            "sequence_no": item.sequence_no,
            "event_type": item.event_type.value,
            "target_type": item.target_type.value,
            "target_key": item.target_key,
            "timing": item.timing.value,
            "payload": ImageSpecService._loads_object(item.payload_json),
            "source": item.source.value,
        }

    @staticmethod
    def _loads_object(value: str) -> dict[str, Any]:
        import json

        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Stored visual JSON must be an object.")
        return parsed

    @staticmethod
    def _loads_list(value: str) -> list[Any]:
        import json

        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("Stored visual JSON must be an array.")
        return parsed
