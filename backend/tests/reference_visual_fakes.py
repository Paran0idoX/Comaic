"""参考图流程的本地模型替身；只用于测试，禁止调用真实配置模型。"""

import json
from backend.models.reference_visual import ReferenceVisualExtraction

VIEWS = ["identity_face", "identity_full_body", "identity_side", "identity_back"]


def fact(field, excerpt, text, kind="identity", views=None, polarity="required", options=None):
    return {"source_field": field, "source_excerpt": excerpt, "kind": kind, "attribute": kind, "polarity": polarity,
        "views": views or VIEWS, "options": options or [{"natural": text, "tags": [text]}],
        "selected": 0, "default_index": 0, "selection_reason": "First defined appearance."}


class FakeVisualAgent:
    def __init__(self, calls=None, session=None):
        self.calls = calls if calls is not None else []
        self.session = session

    async def extract(self, sources, cached):
        if self.session is not None:
            assert not self.session.in_transaction(), "Model calls must release the DB transaction"
        self.calls.append((sources, cached))
        result = []
        for source in sources:
            fields, kind = source["fields"], source["kind"]
            facts = []
            if kind == "character":
                for field, fact_kind, views in [("appearance", "face", VIEWS[:3]),
                    ("default_hairstyle", "head", VIEWS), ("default_clothing", "clothing", VIEWS[1:]),
                    ("default_accessories", "wearable", VIEWS[1:]), ("default_color_palette", "color", VIEWS[1:])]:
                    text = fields[field]
                    if text:
                        facts.append(fact(field, text, text, fact_kind, views))
                if not fields["default_hairstyle"] and fields["appearance"]:
                    facts[0]["kind"] = "identity"
                    facts[0]["views"] = VIEWS
            elif kind == "outfit":
                for field, fact_kind in [("garment_components_json", "clothing"), ("accessories_json", "wearable"), ("colors_json", "color")]:
                    values = json.loads(fields[field] or "[]")
                    if values:
                        facts.append(fact(field, fields[field], ", ".join(str(value) for value in values), fact_kind, VIEWS[1:]))
            else:
                views = ["prop_reference" if kind == "prop_subject" else "scene_master"]
                exclusions = {"no numerals replaced": "replacement numerals", "no modern screens": "modern screens",
                    "no clock replaced": "altered clock design"}
                negative = fields.get("negative_constraints", "")
                if negative in exclusions:
                    facts.append(fact("negative_constraints", negative, exclusions[negative], "shape" if kind == "prop_subject" else "environment", views, "forbidden"))
                for field, value in fields.items():
                    if value and field not in {"negative_constraints", "reference_subject_id"}:
                        item = fact(field, value, value, {"color_palette_json": "color", "lighting_state_json": "lighting",
                            "object_states_json": "object_state", "camera_presets_json": "layout"}.get(field, "shape" if kind == "prop_subject" else "environment"), views)
                        item["attribute"] = field
                        facts.append(item)
            result.append({"kind": kind, "owner_id": source["owner_id"], "data": {"human": kind == "character", "facts": facts}})
        return ReferenceVisualExtraction.model_validate({"profiles": result})


def profile(kind, facts, *, human=True, owner_id=1):
    return {"id": owner_id, "project_id": 1, "kind": kind, "owner_id": owner_id, "source_hash": "a" * 64,
        "revision": 1, "format_version": 1, "data": {"human": human, "facts": facts}}
