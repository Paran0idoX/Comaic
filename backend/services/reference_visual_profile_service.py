"""按来源缓存视觉提炼；外部模型调用前释放数据库事务。"""

import asyncio
import hashlib
import json
import re
from backend.i18n.errors import AppError
from backend.models.comic import OutlineCharacter, OutfitVariant, ReferenceSubject, SceneVisualVersion, ScriptScene
from backend.models.enums import ReferenceProfileKind as K, ReferenceFactKind as F, ReferenceFactPolarity, VisualAssetRole as R, VisualEntityType, ApprovalStatus
from backend.models.reference_visual import PROFILE_FORMAT_VERSION, ReferenceVisualData, ReferenceVisualExtraction
from backend.repositories.reference_visual_profile_repository import ReferenceVisualProfileRepository, profile_response
from backend.utils.json_utils import canonical_json

CHARACTER_VIEWS = {R.IDENTITY_FACE, R.IDENTITY_FULL_BODY, R.IDENTITY_SIDE, R.IDENTITY_BACK}
OUTFIT_KINDS = {F.CLOTHING, F.WEARABLE, F.COLOR}
FIXED_SCENE_KINDS = {F.ENVIRONMENT, F.LAYOUT, F.MATERIAL, F.COLOR}
# 肤色与颈部结构跨脸图/身体图可见，不能与身高、腰臀等完整身形一概拒绝。
FACE_VISIBLE_BODY_ATTRIBUTES = {"skin_tone", "skin_color", "skin_texture", "neck_shape", "neck_length"}


def source_hash(source):
    return hashlib.sha256(canonical_json({"version": PROFILE_FORMAT_VERSION, "source": source}).encode()).hexdigest()


def validate_data(data, source, *, extracted=False):
    """验证来源及可见范围，不靠删词规则猜测自由文本语义。"""
    kind = K(source["kind"])
    if kind == K.SCENE_SUBJECT:
        invalid = [fact for fact in data.facts if fact.kind not in FIXED_SCENE_KINDS]
        if invalid:
            # 一次报告所有分类错误，避免三次重试逐条修复仍耗尽预算；不静默删除固定细节。
            locations = "; ".join(
                f"{fact.kind.value}.{fact.attribute} ({fact.polarity.value}, source_field={fact.source_field}, "
                f"source_excerpt={fact.source_excerpt!r})" for fact in invalid)
            raise ValueError(
                f"scene_subject/{source.get('owner_id', '?')}: invalid fixed-scene facts: {locations}. "
                "Use only environment, layout, material, color for both required and forbidden facts. "
                "Describe permanent fixtures and worn surfaces with those kinds. "
                "Omit time, weather, lighting, atmosphere, occupancy and temporary states, including "
                "definition-scope instructions in negative_constraints; do not turn them into exclusions. "
                "For actual excluded scene elements, use environment/layout/material/color, not identity/object_state.")
    seen = set()
    allowed_views = CHARACTER_VIEWS if kind in {K.CHARACTER, K.OUTFIT} else {
        R.PROP_REFERENCE if kind == K.PROP_SUBJECT else R.SCENE_MASTER}
    for fact in data.facts:
        # 正向事实与同属性的反向排除可以并存，例如成年外观与排除未成年。
        key = (fact.kind, fact.attribute, fact.polarity)
        location = f"{kind.value}/{source.get('owner_id', '?')} {fact.kind.value}.{fact.attribute} ({fact.polarity.value})"
        for view in fact.views:
            if (key, view) in seen:
                raise ValueError(f"{location}: duplicate {view.value}; merge complementary details into one fact, or use separate attributes for distinct details")
            seen.add((key, view))
        original = str(source["fields"].get(fact.source_field, ""))
        if not original or fact.source_excerpt not in original:
            raise ValueError("Visual fact must cite an exact source field and excerpt")
        if not set(fact.views) <= allowed_views:
            raise ValueError(f"{location}: invalid views; use only {', '.join(sorted(view.value for view in allowed_views))}")
        if kind == K.OUTFIT and fact.kind not in OUTFIT_KINDS:
            raise ValueError("Outfit cannot change identity")
        if fact.kind == F.FACE and R.IDENTITY_BACK in fact.views:
            raise ValueError(f"{location}: remove identity_back; facial details are not visible from the back")
        if fact.polarity == ReferenceFactPolarity.REQUIRED and R.IDENTITY_FACE in fact.views:
            if fact.kind == F.CLOTHING or (fact.kind == F.BODY and fact.attribute not in FACE_VISIBLE_BODY_ATTRIBUTES):
                raise ValueError(f"{location}: remove identity_face; full body/clothing is outside the face crop. "
                    "Only body attributes skin_tone, skin_color, skin_texture, neck_shape, neck_length may apply to the face crop")
        if extracted and fact.selected != fact.default_index:
            raise ValueError("Initial selection must use the explicit default or first option")
        for option in fact.options:
            if fact.polarity == ReferenceFactPolarity.FORBIDDEN and re.match(r"^(preserve|keep|maintain|do not (change|alter|remove)|never (change|alter|remove))\b", option.natural.strip(), re.I):
                raise ValueError("Preservation instructions must become required facts, not excluded objects")
            if re.search(r"[\u3400-\u9fff]", option.natural + " ".join(option.tags)) or any(not tag.strip() for tag in option.tags):
                raise ValueError("Generated visual phrases and tags must be nonempty English")
            if option.natural.strip().lower() in {"not specified", "none", "n/a", "unspecified"}:
                raise ValueError("Omit unknown visual facts rather than placeholders")


def validate_extraction(response, sources):
    expected = {(K(item["kind"]), item["owner_id"]): item for item in sources}
    actual = [(item.kind, item.owner_id) for item in response.profiles]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("Extraction must return exactly the missing source profiles")
    for profile in response.profiles:
        validate_data(profile.data, expected[(profile.kind, profile.owner_id)], extracted=True)


class ReferenceVisualProfileService:
    def __init__(self, session, *, agent_factory=None):
        self.session = session
        self.repo = ReferenceVisualProfileRepository(session)
        self.agent_factory = agent_factory

    def source(self, project_id, kind, owner_id):
        """读取最小视觉来源；版本内容与绑定关系都进入 Hash。"""
        kind = K(kind)
        model = {K.CHARACTER: OutlineCharacter, K.OUTFIT: OutfitVariant,
            K.SCENE_SUBJECT: ReferenceSubject, K.PROP_SUBJECT: ReferenceSubject,
            K.SCENE_VERSION: SceneVisualVersion}[kind]
        owner = self.session.get(model, owner_id, populate_existing=True)
        valid = owner is not None
        if valid:
            owner_project = owner.outline_version.project_id if kind == K.CHARACTER else owner.project_id
            valid = owner_project == project_id
        if valid and kind in {K.SCENE_SUBJECT, K.PROP_SUBJECT}:
            valid = owner.entity_type == (VisualEntityType.SCENE if kind == K.SCENE_SUBJECT else VisualEntityType.PROP)
        if valid and kind in {K.OUTFIT, K.SCENE_VERSION}:
            valid = owner.status not in {ApprovalStatus.ARCHIVED, ApprovalStatus.DELETED}
        if not valid:
            raise AppError("reference.owner_invalid", status_code=422)
        if kind == K.CHARACTER:
            fields = {key: getattr(owner, key) or "" for key in ("appearance", "negative_constraints", "default_hairstyle",
                "default_clothing", "default_accessories", "default_color_palette")}
        elif kind == K.OUTFIT:
            fields = {key: getattr(owner, key) or "" for key in ("garment_components_json", "accessories_json", "colors_json",
                "materials_json", "patterns_json", "layer_order_json", "negative_constraints")}
        elif kind == K.SCENE_VERSION:
            fields = {key: getattr(owner, key) or "" for key in ("landmarks_json", "spatial_relations_json", "camera_presets_json",
                "object_states_json", "color_palette_json", "lighting_state_json")}
            scene = self.session.get(ScriptScene, owner.script_scene_id, populate_existing=True)
            fields.update(environment_details=scene.environment_details or "", negative_constraints=scene.negative_constraints or "",
                base_lighting=scene.lighting or "", base_color_palette=scene.color_palette or "",
                base_weather=scene.weather or "", base_time_of_day=scene.time_of_day or "", location_type=scene.location_type or "")
        else:
            fields = {key: getattr(owner, key) or "" for key in ("name", "description", "negative_constraints")}
        bindings = {"character_id": owner.outline_character_id} if kind == K.OUTFIT else {
            "reference_subject_id": scene.reference_subject_id} if kind == K.SCENE_VERSION else {}
        result = {"kind": kind.value, "owner_id": owner_id, "fields": fields, "bindings": bindings}
        if kind == K.SCENE_SUBJECT and owner.scene_definition_version >= 2:
            result["scene_definition_version"] = owner.scene_definition_version
        return result

    def identities(self, *, entity_type, entity_id=None, reference_subject_id=None, outfit_variant_id=None, **_):
        if entity_type == VisualEntityType.CHARACTER:
            return [(K.CHARACTER, entity_id)] + ([(K.OUTFIT, outfit_variant_id)] if outfit_variant_id else [])
        if entity_type == VisualEntityType.PROP:
            return [(K.PROP_SUBJECT, reference_subject_id)]
        return ([(K.SCENE_SUBJECT, reference_subject_id)] if reference_subject_id else []) + ([(K.SCENE_VERSION, entity_id)] if entity_id else [])

    def prepare(self, project_id, identities, *, force=False):
        """只在缓存缺失/失效时创建 Agent；读取快照后 rollback，调用结束再校验保存。"""
        sources, cached, missing, revisions, warnings = [], [], [], {}, []
        for kind, owner_id in identities:
            source = self.source(project_id, kind, owner_id)
            sources.append(source)
            record = self.repo.find(project_id, kind, owner_id)
            if record is not None and not force and record.source_hash == source_hash(source) and record.format_version == PROFILE_FORMAT_VERSION:
                cached.append(profile_response(record).model_dump(mode="json"))
            else:
                if record is not None:
                    warnings.append("reference.profile_rebuilt")
                missing.append(source)
                revisions[(kind, owner_id)] = record.revision if record is not None else None
        if not missing:
            return cached, warnings
        # 此方法只用于准备预览；创建任务不能调用它，以免回滚半批任务。
        self.session.rollback()
        if self.agent_factory is None:
            from backend.agents.reference_visual_agent import ReferenceVisualAgent
            factory = ReferenceVisualAgent
        else:
            factory = self.agent_factory
        try:
            result = asyncio.run(factory().extract(missing, cached))
            if not isinstance(result, ReferenceVisualExtraction):
                result = ReferenceVisualExtraction.model_validate(result)
            validate_extraction(result, missing)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("reference.profile_extraction_failed", status_code=422) from exc
        try:
            self.session.expire_all()
            # 也检查缓存基准修订，防止提炼新造型时依据了旧身份或旧场景。
            for profile in cached:
                current = self.repo.get(profile["id"])
                if current is None or current.revision != profile["revision"]:
                    raise AppError("reference.profile_conflict", status_code=409)
            for source in sources:
                current = self.source(project_id, K(source["kind"]), source["owner_id"])
                if source_hash(current) != source_hash(source):
                    raise AppError("reference.profile_stale", status_code=409)
            for profile in result.profiles:
                source = next(item for item in missing if item["kind"] == profile.kind.value and item["owner_id"] == profile.owner_id)
                self.repo.save(project_id=project_id, kind=profile.kind, owner_id=profile.owner_id,
                    source_hash=source_hash(source), data=profile.data.model_dump(mode="json"),
                    expected_revision=revisions[(profile.kind, profile.owner_id)])
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return [profile_response(self.repo.find(project_id, kind, owner_id)).model_dump(mode="json") for kind, owner_id in identities], warnings

    def check_refs(self, project_id, identities, refs):
        """新界面必须使用准确摘要修订，旧手写 Prompt 客户端可不传引用。"""
        if refs is None:
            return []
        expected = set(identities)
        profiles = []
        for ref in refs:
            record = self.repo.get(ref["id"])
            if record is None or record.project_id != project_id or (record.kind, record.owner_id) not in expected:
                raise AppError("reference.profile_stale", status_code=409)
            source = self.source(project_id, record.kind, record.owner_id)
            if record.format_version != PROFILE_FORMAT_VERSION or record.revision != ref["revision"] or record.source_hash != ref["source_hash"] or record.source_hash != source_hash(source):
                raise AppError("reference.profile_stale", status_code=409)
            profiles.append(profile_response(record).model_dump(mode="json"))
        if len(profiles) != len(expected) or len({item["id"] for item in profiles}) != len(expected):
            raise AppError("reference.profile_stale", status_code=409)
        return profiles

    def update(self, profile_id, expected_revision, data):
        record = self.repo.get(profile_id)
        if record is None:
            raise AppError("reference.profile_not_found", status_code=404)
        source = self.source(record.project_id, record.kind, record.owner_id)
        if record.source_hash != source_hash(source):
            raise AppError("reference.profile_stale", status_code=409)
        try:
            validate_data(data, source)
        except ValueError as exc:
            raise AppError("reference.profile_invalid", status_code=422) from exc
        try:
            saved = self.repo.save(project_id=record.project_id, kind=record.kind, owner_id=record.owner_id,
                source_hash=record.source_hash, data=data.model_dump(mode="json"), expected_revision=expected_revision)
            self.session.commit()
            return profile_response(saved)
        except Exception:
            self.session.rollback()
            raise
