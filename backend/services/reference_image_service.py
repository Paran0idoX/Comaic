"""通用参考图任务：冻结分类、主体、提示词和独立输入原图，复用原后台运行链路。"""

import json
import secrets
import hashlib

from sqlalchemy import select

from backend.i18n.errors import AppError
from backend.models.comic import (CharacterReferenceGenerationTask, OutfitVariant, ReferenceSubject,
    SceneVisualVersion, VisualAsset)
from backend.models.enums import (ApprovalStatus, GenerationMode, GenerationRunStatus,
    ImageGenerationProvider, ReferenceImageTransport, ReferencePurpose, ReferenceSourceMode, VisualAssetRole,
    VisualAssetSource, VisualEntityType, WorkflowCapability)
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.character_reference_service import CharacterReferenceService, MAX_PROMPT_LENGTH
from backend.services.reference_catalog import REFERENCE_CATALOG
from backend.services.reference_inputs import prepare_renderer_spec
from backend.services.visual_bible_service import VisualBibleService
from backend.services.workflow_compiler import parse_bindings, parse_capabilities
from backend.utils.prompt_loader import PromptLoader


class ReferenceImageService(CharacterReferenceService):
    """旧人物任务和新目录任务共用存储、心跳与暂停继续，不伪造漫画页面。"""

    @staticmethod
    def _ensure_txt2img_tool(tool):
        """运行兼容图生图工具；新任务创建时另按实际输入检查能力。"""
        if tool.provider == ImageGenerationProvider.COMFYUI and not tool.workflow_json:
            raise AppError("character_reference.tool_invalid", status_code=409)
        if tool.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE and (not tool.api_base_url or not tool.model):
            raise AppError("character_reference.tool_invalid", status_code=409)

    def _owner(self, *, project_id, entity_type, entity_id=None, reference_subject_id=None, outfit_variant_id=None):
        if self.repository.get_project(project_id) is None:
            raise AppError("reference.project_not_found", status_code=404)
        if entity_type not in REFERENCE_CATALOG:
            raise AppError("reference.subject_type_invalid", status_code=422)
        outfit = None
        if entity_type == VisualEntityType.CHARACTER:
            if reference_subject_id is not None:
                raise AppError("reference.owner_invalid", status_code=422)
            character = self._get_character(entity_id or 0)
            if character.outline_version.project_id != project_id:
                raise AppError("reference.owner_invalid", status_code=422)
            if outfit_variant_id is not None:
                outfit = self.repository.session.get(OutfitVariant, outfit_variant_id)
                if (outfit is None or outfit.project_id != project_id or outfit.outline_character_id != character.id
                        or outfit.status == ApprovalStatus.ARCHIVED):
                    raise AppError("reference.outfit_invalid", status_code=422)
            snapshot = {"name": character.name or character.character_key,
                "description": character.appearance, "negative_constraints": character.negative_constraints,
                "character_key": character.character_key,
                "appearance": character.appearance, "visual_anchors": character.visual_anchors,
                "hairstyle": character.default_hairstyle, "clothing": character.default_clothing,
                "accessories": character.default_accessories, "color_palette": character.default_color_palette}
            return character, outfit, snapshot, None
        if outfit_variant_id is not None:
            raise AppError("reference.outfit_invalid", status_code=422)
        if reference_subject_id is not None:
            subject = self.repository.session.get(ReferenceSubject, reference_subject_id)
            if subject is None or subject.project_id != project_id or subject.entity_type != entity_type:
                raise AppError("reference.owner_invalid", status_code=422)
            snapshot = {"name": subject.name, "description": subject.description,
                "negative_constraints": subject.negative_constraints, "key": subject.key}
            if entity_id is not None:
                version = self.repository.session.get(SceneVisualVersion, entity_id) if entity_type == VisualEntityType.SCENE else None
                if (version is None or version.project_id != project_id
                        or version.script_scene.task.project_id != project_id
                        or version.script_scene.reference_subject_id != reference_subject_id):
                    raise AppError("reference.owner_invalid", status_code=422)
                # 通用条目提供稳定命名；版本专用图还必须冻结这次实际版本的布局和光照。
                version_values = {field.removesuffix("_json"): json.loads(getattr(version, field))
                    for field in ("landmarks_json", "spatial_relations_json", "camera_presets_json",
                        "object_states_json", "color_palette_json", "lighting_state_json")}
                snapshot["scene_version"] = {"id": version.id, "version": version.version,
                    "script_scene_id": version.script_scene_id, **version_values}
                version_description = PromptLoader.load("reference_scene_version_description.md").format(
                    **{key: json.dumps(value, ensure_ascii=False, sort_keys=True) for key, value in version_values.items()})
                snapshot["description"] = "\n".join(value for value in (subject.description, version_description) if value)
                snapshot["negative_constraints"] = "\n".join(dict.fromkeys(value for value in (
                    subject.negative_constraints, version.script_scene.negative_constraints) if value))
            return subject, None, snapshot, subject.key
        if entity_type == VisualEntityType.SCENE:
            version = self.repository.session.get(SceneVisualVersion, entity_id or 0)
            if version is not None and version.project_id == project_id:
                scene = version.script_scene
                return version, None, {"name": scene.name or scene.scene_key,
                    "description": "\n".join(value for value in (scene.environment_details, scene.visual_anchors,
                        scene.lighting, scene.color_palette) if value),
                    "negative_constraints": scene.negative_constraints}, None
        raise AppError("reference.owner_invalid", status_code=422)

    def _roles(self, entity_type, roles):
        roles = tuple(roles)
        if not roles or len(set(roles)) != len(roles) or any(role not in REFERENCE_CATALOG[entity_type] for role in roles):
            raise AppError("reference.roles_invalid", status_code=422)
        return roles

    def _source_assets(self, *, project_id, entity_type, entity_id, roles, source_mode, source_asset_ids):
        if source_mode == ReferenceSourceMode.NONE:
            return []
        if source_mode == ReferenceSourceMode.AUTO:
            if entity_type != VisualEntityType.CHARACTER or not any(role != VisualAssetRole.IDENTITY_FACE for role in roles):
                return []
            face = self.repository.session.scalar(select(VisualAsset).where(
                VisualAsset.project_id == project_id, VisualAsset.entity_type == entity_type,
                VisualAsset.entity_id == entity_id, VisualAsset.role == VisualAssetRole.IDENTITY_FACE,
                VisualAsset.status == ApprovalStatus.APPROVED, VisualAsset.local_path.is_not(None),
            ).order_by(VisualAsset.version.desc(), VisualAsset.id.desc()).limit(1))
            return [face] if face is not None else []
        if not source_asset_ids or len(set(source_asset_ids)) != len(source_asset_ids):
            raise AppError("reference.sources_invalid", status_code=422)
        result = []
        for asset_id in source_asset_ids:
            asset = self.repository.session.get(VisualAsset, asset_id)
            if asset is None or asset.project_id != project_id or asset.status != ApprovalStatus.APPROVED:
                raise AppError("reference.sources_invalid", status_code=422)
            result.append(asset)
        return result

    def preview_reference_prompts(self, *, project_id, entity_type, entity_id=None,
            reference_subject_id=None, outfit_variant_id=None, tool_preset_id, roles,
            source_mode=ReferenceSourceMode.AUTO, source_asset_ids=None, canvas_asset_id=None):
        owner, outfit, snapshot, key = self._owner(project_id=project_id, entity_type=entity_type,
            entity_id=entity_id, reference_subject_id=reference_subject_id, outfit_variant_id=outfit_variant_id)
        roles = self._roles(entity_type, roles)
        tool = self._get_tool(tool_preset_id)
        self._ensure_txt2img_tool(tool)
        sources = self._source_assets(project_id=project_id, entity_type=entity_type, entity_id=entity_id,
            roles=roles, source_mode=source_mode, source_asset_ids=source_asset_ids or [])
        capabilities = parse_capabilities(tool.capabilities_json)
        capacity = capabilities.reference_images.max_images
        if tool.provider == ImageGenerationProvider.COMFYUI:
            capacity = min(capacity, len(parse_bindings(tool.bindings_json).reference_slots))
        elif capabilities.reference_images.transport == ReferenceImageTransport.NONE:
            capacity = 0
        warnings = []
        supports_images = bool({WorkflowCapability.REFERENCE_IMAGE, WorkflowCapability.IMG2IMG}.intersection(capabilities.features))
        if source_mode == ReferenceSourceMode.AUTO and sources and (not supports_images or capacity == 0):
            # 默认脸图只是便捷输入；工具未配置有效图片入口时保留文字生成路径。
            sources = []
            warnings.append("reference.auto.text_only_tool")
        elif source_mode == ReferenceSourceMode.AUTO and entity_type == VisualEntityType.CHARACTER and not sources:
            warnings.append("reference.auto.text_only_no_face")
        canvas = None
        if canvas_asset_id is not None:
            canvas = self.repository.session.get(VisualAsset, canvas_asset_id)
            if canvas is None or canvas.project_id != project_id or canvas.status != ApprovalStatus.APPROVED:
                raise AppError("reference.sources_invalid", status_code=422)
        if entity_type == VisualEntityType.CHARACTER:
            prompts = self.prompt_service.compile(character=owner, prompt_type=tool.prompt_type, roles=roles, outfit=outfit)
        else:
            common = {"subject_type": entity_type.value, **snapshot}
            natural = PromptLoader.load("reference_subject_natural_prompt.md").format(**common)
            tags = PromptLoader.load("reference_subject_tag_prompt.md").format(**common)
            negative_natural = PromptLoader.load("reference_subject_natural_negative_prompt.md").format(**common)
            negative_tags = PromptLoader.load("reference_subject_tag_negative_prompt.md").format(**common)
            prompts = {role.value: {"positive": self.prompt_service._combine(tool.prompt_type, natural, tags),
                "negative": self.prompt_service._combine(tool.prompt_type, negative_natural, negative_tags)} for role in roles}
        return {"tool": tool, "owner": owner, "snapshot": snapshot, "key": key,
            "roles": roles, "sources": sources, "prompts": prompts, "canvas": canvas, "warnings": warnings}

    def _reference_item(self, asset, order):
        category = asset.entity_type.value
        name = asset.entity_key or ""
        key = asset.entity_key or str(asset.entity_id or "")
        if asset.entity_type == VisualEntityType.CHARACTER:
            owner = self.repository.get_character(asset.entity_id or 0)
            name = owner.name if owner else name
            key = owner.character_key if owner else key
        elif asset.reference_subject_id:
            owner = self.repository.session.get(ReferenceSubject, asset.reference_subject_id)
            name = owner.name if owner else name
            key = owner.key if owner else key
        elif asset.entity_type == VisualEntityType.SCENE:
            version = self.repository.session.get(SceneVisualVersion, asset.entity_id or 0)
            if version is not None:
                name, key = version.script_scene.name, version.script_scene.scene_key
        purpose = {VisualEntityType.CHARACTER: (ReferencePurpose.IDENTITY if asset.role == VisualAssetRole.IDENTITY_FACE else ReferencePurpose.APPEARANCE),
            VisualEntityType.SCENE: ReferencePurpose.SCENE, VisualEntityType.PROP: ReferencePurpose.PROP}.get(asset.entity_type, ReferencePurpose.APPEARANCE)
        return {"id": asset.id, "asset_id": asset.id, "version": asset.version, "role": asset.role.value,
            "order": order, "local_path": asset.local_path, "renderer_locator": asset.renderer_locator,
            "storage_kind": asset.storage_kind.value, "sha256": asset.sha256, "width": asset.width,
            "height": asset.height, "mime_type": asset.mime_type,
            "entity_id": asset.entity_id, "reference_subject_id": asset.reference_subject_id,
            "outfit_variant_id": asset.outfit_variant_id,
            "owner": {"category": category, "id": asset.reference_subject_id or asset.entity_id,
                "key": key, "name": name},
            "purpose": purpose.value, "reason": "Preserve the approved reference subject",
            "priority": order, "is_primary": True, "is_required": True}

    def create_reference_task(self, *, project_id, candidate_count, prompts, **selection):
        context = self.preview_reference_prompts(project_id=project_id, **selection)
        roles = context["roles"]
        if not 1 <= candidate_count <= 4:
            raise AppError("character_reference.candidate_count_invalid", status_code=422)
        if set(prompts) != {role.value for role in roles}:
            raise AppError("reference.prompts_invalid", status_code=422)
        normalized = {}
        for role in roles:
            pair = prompts[role.value]
            positive, negative = str(pair.get("positive") or ""), str(pair.get("negative") or "")
            if not positive.strip() or len(positive) > MAX_PROMPT_LENGTH or len(negative) > MAX_PROMPT_LENGTH:
                raise AppError("reference.prompts_invalid", status_code=422)
            normalized[role.value] = {"positive": positive, "negative": negative}
        tool = context["tool"]
        capabilities = parse_capabilities(tool.capabilities_json)
        specs = {}
        actual_ids = []
        for role in roles:
            sources = context["sources"]
            if selection.get("source_mode", ReferenceSourceMode.AUTO) == ReferenceSourceMode.AUTO and role == VisualAssetRole.IDENTITY_FACE:
                sources = []
            required_feature = WorkflowCapability.REFERENCE_IMAGE if sources or context["canvas"] else WorkflowCapability.TXT2IMG
            if required_feature not in capabilities.features and not (
                    required_feature == WorkflowCapability.REFERENCE_IMAGE and WorkflowCapability.IMG2IMG in capabilities.features):
                raise AppError("reference.tool_capability_missing", status_code=409)
            items = [self._reference_item(asset, index) for index, asset in enumerate(sources, start=1)]
            spec = {"prompt": normalized[role.value], "render": {}, "subjects": [], "scene": {}, "style": {},
                "required_capabilities": [required_feature.value],
                "reference_plan": {"schema_version": 1, "items": items, "omitted": [], "warnings": context["warnings"]}}
            if context["canvas"] is not None:
                if not capabilities.reference_images.requires_canvas:
                    raise AppError("reference.input.configuration_invalid", status_code=422)
                spec["reference_canvas"] = self._reference_item(context["canvas"], 1)
            spec = prepare_renderer_spec(spec, tool, GenerationMode.FINAL)
            specs[role.value] = spec
            actual_ids.extend(item["asset_id"] for item in spec.get("reference_inputs", {}).get("items", []) if item.get("asset_id"))
        seeds = []
        while len(seeds) < candidate_count:
            seed = secrets.randbelow(2_147_483_647)
            if seed not in seeds:
                seeds.append(seed)
        entity_type = selection["entity_type"]
        return self.repository.create_task(project_id=project_id,
            character_id=selection.get("entity_id") if entity_type == VisualEntityType.CHARACTER else None,
            entity_type=entity_type, entity_id=selection.get("entity_id"), entity_key=context["key"],
            reference_subject_id=selection.get("reference_subject_id"), outfit_variant_id=selection.get("outfit_variant_id"),
            tool=tool, style_profile_id=None, candidate_count=candidate_count, prompts=normalized, seeds=seeds,
            roles=roles, source_asset_ids=list(dict.fromkeys(actual_ids)), subject_snapshot=context["snapshot"], specs=specs)

    def list_project_tasks(self, project_id, *, entity_type=None, entity_id=None, reference_subject_id=None):
        if self.repository.get_project(project_id) is None:
            raise AppError("reference.project_not_found", status_code=404)
        query = select(CharacterReferenceGenerationTask.id).where(CharacterReferenceGenerationTask.project_id == project_id)
        for field, value in (("entity_type", entity_type), ("entity_id", entity_id), ("reference_subject_id", reference_subject_id)):
            if value is not None:
                query = query.where(getattr(CharacterReferenceGenerationTask, field) == value)
        ids = list(self.repository.session.scalars(query.order_by(CharacterReferenceGenerationTask.id.desc()).limit(200)))
        return [self.get_task(task_id) for task_id in ids]

    def approve_image(self, image_id):
        image = self.repository.get_image(image_id)
        if image is None:
            raise AppError("character_reference.image_not_found", status_code=404)
        if image.promoted_asset_id is not None:
            return self.repository.session.get(VisualAsset, image.promoted_asset_id)
        run = image.run
        if run.status != GenerationRunStatus.SUCCEEDED:
            raise AppError("character_reference.candidate_incomplete", status_code=409)
        task = run.task
        path, _ = self.artifact_file(image_id)
        content = path.read_bytes()
        if image.sha256 and hashlib.sha256(content).hexdigest() != image.sha256:
            raise AppError("reference.input.file_changed", status_code=409)
        service = VisualBibleService(VisualBibleRepository(self.repository.session), asset_root=self.asset_root)
        try:
            asset = service.upload_asset(project_id=task.project_id, entity_type=task.entity_type,
                entity_id=task.entity_id if task.entity_id is not None else task.outline_character_id,
                entity_key=task.entity_key, reference_subject_id=task.reference_subject_id,
                outfit_variant_id=task.outfit_variant_id, role=run.role, content=content,
                source=VisualAssetSource.GENERATED_IMAGE, approve=True, commit=False)
            image.promoted_asset_id = asset.id
            run.review_status = ApprovalStatus.APPROVED
            self.repository.session.commit()
            return asset
        except Exception:
            self.repository.session.rollback()
            raise
