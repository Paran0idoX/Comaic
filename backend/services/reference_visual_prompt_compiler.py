"""只消费已提炼、已选定的视觉事实；用途切换不调用模型。"""

import json
from backend.i18n.errors import AppError
from backend.models.enums import (ReferenceProfileKind as K, ReferenceFactKind as F,
    ReferenceFactPolarity as P, VisualAssetRole as R, ImagePromptType)
from backend.models.reference_visual import ReferenceProfileResponse
from backend.utils.prompt_loader import PromptLoader


class ReferenceVisualPromptCompiler:
    def __init__(self):
        self.frames = json.loads(PromptLoader.load("reference_visual_framing.json"))

    @staticmethod
    def _unique(values):
        seen, result = set(), []
        for value in values:
            text = value.strip().strip(",")
            key = text.casefold().rstrip(".")
            if key and key not in seen:
                result.append(text)
                seen.add(key)
        return result

    @staticmethod
    def _combine(prompt_type, natural, tags):
        if prompt_type == ImagePromptType.TAG:
            return tags
        if prompt_type == ImagePromptType.NATURAL_LANGUAGE:
            return natural
        return natural + "\n" + tags

    def compile(self, *, profiles, prompt_type, roles, identity_from_reference_roles=None):
        """先筛选当前视角，再按具体属性覆盖版本差异；脸图只取人物基准。"""
        profiles = [ReferenceProfileResponse.model_validate(item) for item in profiles]
        human = next((item.data.human for item in profiles if item.kind == K.CHARACTER), False)
        result = {}
        for role in roles:
            if role.value not in self.frames:
                raise AppError("reference.roles_invalid", status_code=422)
            facts = []
            for profile in profiles:
                if role == R.IDENTITY_FACE and profile.kind == K.OUTFIT:
                    continue
                incoming = [fact for fact in profile.data.facts if role in fact.views]
                if profile.kind in {K.OUTFIT, K.SCENE_VERSION}:
                    keys = {(fact.kind, fact.attribute, fact.polarity) for fact in incoming}
                    facts = [fact for fact in facts if (fact.kind, fact.attribute, fact.polarity) not in keys]
                facts.extend(incoming)
            required = [fact.options[fact.selected] for fact in facts if fact.polarity == P.REQUIRED]
            if role in (identity_from_reference_roles or set()):
                required = [fact.options[fact.selected] for fact in facts if fact.polarity == P.REQUIRED and fact.kind != F.FACE]
            forbidden = [fact.options[fact.selected] for fact in facts if fact.polarity == P.FORBIDDEN]
            if not required and role not in (identity_from_reference_roles or set()):
                raise AppError("reference.profile_empty", status_code=422)
            framing = self.frames[role.value]
            prefix = "human_" if human and role in {R.IDENTITY_FACE, R.IDENTITY_FULL_BODY, R.IDENTITY_SIDE, R.IDENTITY_BACK} else ""
            natural = "\n".join(self._unique([framing.get(prefix + "positive", framing["positive"]),
                *[phrase.natural for phrase in required]]))
            tags = ", ".join(self._unique([*framing.get(prefix + "tags", framing["tags"]),
                *[tag for phrase in required for tag in phrase.tags]]))
            negative = "\n".join(self._unique([framing["negative"], *[phrase.natural for phrase in forbidden]]))
            negative_tags = ", ".join(self._unique([*framing["negative_tags"], *[tag for phrase in forbidden for tag in phrase.tags]]))
            # 身份图负责脸部细节，其余已选事实和构图仍使用同一用途模板。
            result[role.value] = {"positive": self._combine(prompt_type, natural, tags),
                "negative": self._combine(prompt_type, negative, negative_tags)}
        return result
