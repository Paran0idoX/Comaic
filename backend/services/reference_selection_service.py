"""依据已锁定页面、镜头和素材归属选图；不调用视觉模型或修改原图。"""

from copy import deepcopy
from typing import Any

from backend.models.enums import (
    ReferencePurpose,
    SubjectReferenceFraming,
    SubjectReferenceView,
    VisualAssetRole,
    VisualEntityType,
)


IDENTITY_ROLES = {
    VisualAssetRole.IDENTITY_FACE.value,
    VisualAssetRole.IDENTITY_HALF_BODY.value,
    VisualAssetRole.IDENTITY_FULL_BODY.value,
    VisualAssetRole.IDENTITY_SIDE.value,
    VisualAssetRole.IDENTITY_BACK.value,
}
OUTFIT_ROLES = {
    VisualAssetRole.OUTFIT_FRONT.value,
    VisualAssetRole.OUTFIT_BACK.value,
    VisualAssetRole.OUTFIT_DETAIL.value,
}
ROLE_FALLBACKS = {
    VisualAssetRole.IDENTITY_FACE.value: [VisualAssetRole.IDENTITY_FACE.value, VisualAssetRole.IDENTITY_HALF_BODY.value, VisualAssetRole.IDENTITY_FULL_BODY.value],
    VisualAssetRole.IDENTITY_HALF_BODY.value: [VisualAssetRole.IDENTITY_HALF_BODY.value, VisualAssetRole.IDENTITY_FULL_BODY.value, VisualAssetRole.IDENTITY_FACE.value],
    VisualAssetRole.IDENTITY_FULL_BODY.value: [VisualAssetRole.IDENTITY_FULL_BODY.value, VisualAssetRole.IDENTITY_HALF_BODY.value, VisualAssetRole.IDENTITY_FACE.value],
    VisualAssetRole.IDENTITY_SIDE.value: [VisualAssetRole.IDENTITY_SIDE.value, VisualAssetRole.IDENTITY_FULL_BODY.value, VisualAssetRole.IDENTITY_HALF_BODY.value, VisualAssetRole.IDENTITY_FACE.value],
    VisualAssetRole.IDENTITY_BACK.value: [VisualAssetRole.IDENTITY_BACK.value, VisualAssetRole.IDENTITY_FULL_BODY.value, VisualAssetRole.IDENTITY_HALF_BODY.value, VisualAssetRole.IDENTITY_SIDE.value, VisualAssetRole.IDENTITY_FACE.value],
}


class ReferenceSelectionService:
    """确定性挑选本页相关原图，并冻结可被 Provider 直接消费的顺序和说明。"""

    VERSION = "2"

    @staticmethod
    def normalize_view(subject: dict[str, Any]) -> SubjectReferenceView:
        explicit = subject.get("reference_view", SubjectReferenceView.UNKNOWN.value)
        if explicit != SubjectReferenceView.UNKNOWN.value:
            return SubjectReferenceView(explicit)
        text = " ".join(str(subject.get(key, "")) for key in ("orientation", "pose")).casefold()
        for markers, value in (
            (("back to camera", "back toward", "rear view", "back view", "face away", "背对", "背影", "后视", "后脑"), SubjectReferenceView.BACK),
            (("side view", "profile view", "in profile", "侧面", "侧身", "侧视"), SubjectReferenceView.SIDE),
            (("three-quarter", "three quarter", "3/4", "四分之三"), SubjectReferenceView.THREE_QUARTER),
            (("front", "toward camera", "正面", "面对镜头"), SubjectReferenceView.FRONT),
        ):
            if any(marker in text for marker in markers):
                return value
        return SubjectReferenceView.UNKNOWN

    @staticmethod
    def normalize_framing(subject: dict[str, Any], camera: dict[str, Any]) -> SubjectReferenceFraming:
        explicit = subject.get("reference_framing", SubjectReferenceFraming.UNKNOWN.value)
        if explicit != SubjectReferenceFraming.UNKNOWN.value:
            return SubjectReferenceFraming(explicit)
        text = str(camera.get("shot_type", "")).casefold()
        for markers, value in (
            (("close", "headshot", "portrait", "特写", "脸部", "大头"), SubjectReferenceFraming.FACE),
            (("wide", "long", "full", "establish", "全身", "远景", "大全景"), SubjectReferenceFraming.FULL_BODY),
            (("medium", "waist", "half", "半身", "中景"), SubjectReferenceFraming.HALF_BODY),
        ):
            if any(marker in text for marker in markers):
                return value
        return SubjectReferenceFraming.UNKNOWN

    @classmethod
    def select(cls, *, snapshot: dict[str, Any], shot_plan: dict[str, Any]) -> dict[str, Any]:
        """每个人物最多一张主图和一张辅助图，场景/可见物品各取一张；容量由工具处理。"""
        result: dict[str, Any] = {
            "schema_version": 1, "selector_version": cls.VERSION,
            "items": [], "omitted": [], "fallbacks": [], "warnings": [],
        }
        plans = {item["character_key"]: item for item in shot_plan.get("subjects", [])}
        def character_order(key: str) -> tuple[int, str]:
            return int(plans.get(key, {}).get("depth_order") or 0), key

        for character in sorted(snapshot.get("characters", []), key=lambda value: character_order(value["character_key"])):
            owner = {
                "category": VisualEntityType.CHARACTER.value, "id": character.get("outline_character_id"),
                "key": character["character_key"], "name": character.get("name") or character["character_key"],
            }
            subject = plans.get(character["character_key"], {})
            view = cls.normalize_view(subject)
            framing = cls.normalize_framing(subject, shot_plan.get("camera") or {})
            framing_role = {
                SubjectReferenceFraming.FACE: VisualAssetRole.IDENTITY_FACE.value,
                SubjectReferenceFraming.HALF_BODY: VisualAssetRole.IDENTITY_HALF_BODY.value,
                SubjectReferenceFraming.FULL_BODY: VisualAssetRole.IDENTITY_FULL_BODY.value,
                SubjectReferenceFraming.UNKNOWN: VisualAssetRole.IDENTITY_FULL_BODY.value,
            }[framing]
            wanted = {
                SubjectReferenceView.SIDE: VisualAssetRole.IDENTITY_SIDE.value,
                SubjectReferenceView.BACK: VisualAssetRole.IDENTITY_BACK.value,
            }.get(view, framing_role)
            outfit = character.get("outfit") or {}
            current_outfit = outfit.get("variant_id")
            identity_assets = [asset for asset in character.get("identity_assets", []) if asset.get("role") in IDENTITY_ROLES]
            usable: list[dict[str, Any]] = []
            for asset in identity_assets:
                if asset.get("outfit_variant_id") is not None and asset.get("outfit_variant_id") != current_outfit and asset.get("role") != VisualAssetRole.IDENTITY_FACE.value:
                    cls._omit(result, asset, owner, "reference.selection.outfit_mismatch")
                else:
                    usable.append(asset)
            # 先按已约定视角回退表匹配，再按确认版本/id取最新；衣服归属不明确不会改变回退表。
            def rank(asset: dict[str, Any]) -> tuple[int, int, int]:
                role = asset["role"]
                score = ROLE_FALLBACKS[wanted].index(role)
                return score, -int(asset.get("version") or 1), -int(asset.get("id") or asset.get("asset_id") or 0)

            primary_candidates = [asset for asset in usable if asset["role"] in ROLE_FALLBACKS[wanted]]
            primary = min(primary_candidates, key=rank) if primary_candidates else None
            selected: set[int] = set()
            if primary is None:
                cls._warning(result, "image_spec.identity_asset_missing", owner)
            else:
                cls._append(result, primary, owner, ReferencePurpose.IDENTITY, 100, True, "reference.selection.view_match" if primary["role"] == wanted else "reference.selection.identity_fallback")
                selected.add(int(primary.get("id") or primary["asset_id"]))
                if primary["role"] != wanted:
                    result["fallbacks"].append({"owner": owner, "requested_role": wanted, "selected_role": primary["role"], "reason": cls._reason("reference.selection.identity_fallback"), "reason_code": "reference.selection.identity_fallback"})
                if current_outfit is not None and primary["role"] != VisualAssetRole.IDENTITY_FACE.value and primary.get("outfit_variant_id") is None:
                    result["fallbacks"].append({"owner": owner, "requested_role": wanted, "selected_role": primary["role"], "reason": cls._reason("reference.selection.outfit_unspecified"), "reason_code": "reference.selection.outfit_unspecified"})

                outfit_assets = [asset for asset in outfit.get("assets", []) if asset.get("role") in OUTFIT_ROLES]
                preferred_outfit = VisualAssetRole.OUTFIT_BACK.value if view == SubjectReferenceView.BACK else VisualAssetRole.OUTFIT_FRONT.value
                if outfit_assets and (primary.get("outfit_variant_id") != current_outfit or primary["role"] == VisualAssetRole.IDENTITY_FACE.value):
                    auxiliary = min(outfit_assets, key=lambda asset: (asset["role"] != preferred_outfit, -int(asset.get("version") or 1), -int(asset.get("id") or 0)))
                    cls._append(result, auxiliary, owner, ReferencePurpose.APPEARANCE, 70, False, "reference.selection.current_outfit")
                    selected.add(int(auxiliary.get("id") or auxiliary["asset_id"]))
                elif primary["role"] != VisualAssetRole.IDENTITY_FACE.value and view != SubjectReferenceView.BACK:
                    faces = [asset for asset in usable if asset["role"] == VisualAssetRole.IDENTITY_FACE.value]
                    if faces:
                        auxiliary = cls._latest(faces)
                        cls._append(result, auxiliary, owner, ReferencePurpose.IDENTITY, 60, False, "reference.selection.face_detail")
                        selected.add(int(auxiliary.get("id") or auxiliary["asset_id"]))
            for asset in usable + list(outfit.get("assets", [])):
                asset_id = int(asset.get("id") or asset.get("asset_id") or 0)
                if asset.get("role") in IDENTITY_ROLES | OUTFIT_ROLES and asset_id not in selected:
                    cls._omit(result, asset, owner, "reference.selection.not_needed")

        scene = snapshot.get("scene") or {}
        owner = {
            "category": VisualEntityType.SCENE.value, "id": scene.get("reference_subject_id") or scene.get("script_scene_id"),
            "key": scene.get("reference_subject_key") or scene.get("scene_key", ""), "name": scene.get("reference_subject_name") or scene.get("name") or scene.get("scene_key", ""),
        }
        version_assets = []
        catalog_assets = []
        for asset in scene.get("assets", []):
            if asset.get("role") != VisualAssetRole.SCENE_MASTER.value:
                continue
            if asset.get("reference_subject_id") not in (None, scene.get("reference_subject_id")) or asset.get("entity_id") not in (None, scene.get("visual_version_id")):
                cls._omit(result, asset, owner, "reference.selection.scene_scope_mismatch")
            else:
                version_assets.append(asset)
        for asset in scene.get("catalog_assets", []):
            if asset.get("role") != VisualAssetRole.SCENE_MASTER.value:
                continue
            if asset.get("entity_id") is not None or asset.get("reference_subject_id") not in (None, scene.get("reference_subject_id")):
                cls._omit(result, asset, owner, "reference.selection.scene_scope_mismatch")
            else:
                catalog_assets.append(asset)
        scene_assets = version_assets or catalog_assets
        background_visible = (shot_plan.get("scene") or {}).get("background_visible", True)
        if not background_visible:
            for asset in version_assets + catalog_assets:
                cls._omit(result, asset, owner, "reference.selection.background_not_visible")
        elif scene_assets:
            primary = cls._latest(scene_assets)
            cls._append(result, primary, owner, ReferencePurpose.SCENE, 90, True, "reference.selection.scene_version" if version_assets else "reference.selection.scene_subject")
            for asset in version_assets + catalog_assets:
                if asset.get("id") != primary.get("id"):
                    cls._omit(result, asset, owner, "reference.selection.not_needed")
        elif scene.get("scene_key"):
            cls._warning(result, "image_spec.scene_asset_missing", owner)

        props = {item["key"]: item for item in snapshot.get("prop_catalog", [])}
        visible = set((shot_plan.get("scene") or {}).get("visible_prop_keys", []))
        for subject in shot_plan.get("subjects", []):
            visible.update(subject.get("visible_prop_keys", []))
        # 旧 ShotPlan 没有显式可见列表，只对确实存在于目录的持有物做兼容回退。
        if "visible_prop_keys" not in (shot_plan.get("scene") or {}) and not any("visible_prop_keys" in item for item in shot_plan.get("subjects", [])):
            visible.update(key for character in snapshot.get("characters", []) for key in character.get("held_props", []) if key in props)
        for key in sorted(visible):
            prop = props.get(key)
            if prop is None:
                cls._warning(result, "reference.selection.prop_unknown", {"category": VisualEntityType.PROP.value, "id": None, "key": key, "name": key})
                continue
            owner = {"category": VisualEntityType.PROP.value, "id": prop.get("id"), "key": key, "name": prop.get("name") or key}
            assets = [asset for asset in prop.get("assets", []) if asset.get("role") == VisualAssetRole.PROP_REFERENCE.value]
            if assets:
                primary = cls._latest(assets)
                cls._append(result, primary, owner, ReferencePurpose.PROP, 85, True, "reference.selection.visible_prop")
                for asset in assets:
                    if asset.get("id") != primary.get("id"):
                        cls._omit(result, asset, owner, "reference.selection.not_needed")
            else:
                cls._warning(result, "image_spec.prop_asset_missing", owner)
        # 所有主人物图先于辅助图，使容量有限时仍有机会覆盖本页每个人物。
        def input_order(item: dict[str, Any]) -> tuple[Any, ...]:
            category = item["owner"]["category"]
            if category == VisualEntityType.CHARACTER.value:
                return (0 if item["is_primary"] else 1, *character_order(item["owner"]["key"]), item["asset_id"])
            return (2 if category == VisualEntityType.SCENE.value else 3, item["owner"]["key"], item["asset_id"])

        result["items"].sort(key=input_order)
        for index, item in enumerate(result["items"], start=1):
            item["order"] = index
        return result

    @staticmethod
    def _latest(assets: list[dict[str, Any]]) -> dict[str, Any]:
        return max(assets, key=lambda asset: (int(asset.get("version") or 1), int(asset.get("id") or asset.get("asset_id") or 0)))

    @staticmethod
    def _append(result: dict[str, Any], asset: dict[str, Any], owner: dict[str, Any], purpose: ReferencePurpose, priority: int, primary: bool, reason: str) -> None:
        asset_id = int(asset.get("id") or asset["asset_id"])
        if any(item["asset_id"] == asset_id for item in result["items"]):
            return
        item = deepcopy(asset)
        text = ReferenceSelectionService._reason(reason)
        if purpose == ReferencePurpose.IDENTITY and asset.get("outfit_variant_id") is None and asset.get("role") != VisualAssetRole.IDENTITY_FACE.value:
            text += " Use it for identity and viewpoint only; use the page's confirmed clothing instead of copying unspecified clothing from this image."
        item.update({"id": asset_id, "asset_id": asset_id, "version": int(asset.get("version") or 1), "owner": deepcopy(owner), "purpose": purpose.value, "reason": text, "reason_code": reason, "priority": priority, "is_primary": primary, "is_required": primary})
        result["items"].append(item)

    @staticmethod
    def _omit(result: dict[str, Any], asset: dict[str, Any], owner: dict[str, Any], reason: str) -> None:
        result["omitted"].append({"asset_id": asset.get("id") or asset.get("asset_id"), "role": asset.get("role"), "owner": deepcopy(owner), "reason": ReferenceSelectionService._reason(reason), "reason_code": reason})

    @staticmethod
    def _reason(code: str) -> str:
        """对用户用稳定翻译键，对 Provider 用具体自然语言描述用途。"""
        return {
            "reference.selection.view_match": "Use this reference for the character's identity at the requested viewpoint and framing.",
            "reference.selection.identity_fallback": "The requested reference view is unavailable; use the closest allowed identity reference and follow the requested camera view in the prompt.",
            "reference.selection.outfit_unspecified": "This image has no confirmed clothing association; use it for identity only and preserve the page's confirmed clothing.",
            "reference.selection.current_outfit": "Use this auxiliary reference for the character's confirmed current clothing and accessories.",
            "reference.selection.face_detail": "Use this auxiliary reference to preserve the same character's facial identity; do not add another person or viewpoint.",
            "reference.selection.scene_version": "Use this reference for the scene's selected confirmed visual version.",
            "reference.selection.scene_subject": "Use this reference for the page's bound scene and its persistent landmarks.",
            "reference.selection.visible_prop": "Use this reference for the catalog object visible in this page; preserve its shape and appearance.",
            "reference.selection.outfit_mismatch": "Omitted because this body reference belongs to a different confirmed clothing version.",
            "reference.selection.not_needed": "Omitted because another reference already covers this page's requested use.",
            "reference.selection.background_not_visible": "Omitted because the shot plan does not show the background.",
            "reference.selection.scene_scope_mismatch": "Omitted because this image belongs to another scene entry or visual version.",
        }[code]

    @staticmethod
    def _warning(result: dict[str, Any], code: str, owner: dict[str, Any]) -> None:
        result["warnings"].append({"code": code, "message": f"{code}: {owner['name']}", "owner": deepcopy(owner)})
