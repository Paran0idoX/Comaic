"""保留旧编译器名称，全部参考图共用视觉摘要编译。"""

from backend.services.reference_catalog import DEFAULT_CHARACTER_REFERENCE_ROLES
from backend.services.reference_visual_prompt_compiler import ReferenceVisualPromptCompiler

REFERENCE_ROLES = DEFAULT_CHARACTER_REFERENCE_ROLES


class CharacterReferencePromptService(ReferenceVisualPromptCompiler):
    def compile(self, *, profiles, prompt_type, roles=None, **kwargs):
        return super().compile(profiles=profiles, prompt_type=prompt_type,
            roles=roles or REFERENCE_ROLES, **kwargs)
