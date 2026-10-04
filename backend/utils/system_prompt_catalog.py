"""可维护提示词目录；文件名仅来自白名单，不接受用户传入路径。"""

from backend.models.enums import LLMProvider, SystemPromptKey


SYSTEM_PROMPT_FILES = {
    key: f"{key.value}_prompt.md" for key in SystemPromptKey
}
SYSTEM_PROMPT_FILES[SystemPromptKey.SHOT_LANGUAGE] = "image_spec_language_prompt.md"


def model_prompt_overrides(config) -> dict[str, str]:
    """解析当前 API 组的模型覆盖；空文本也表示显式关闭全局提示词。"""
    import json

    return json.loads(config.model_system_prompts_json or "{}")


def model_prompt_default_files(config, model: str | None = None) -> list[str]:
    """默认文件关联属于 API 模型配置，不属于注入策略。"""
    import json

    defaults = json.loads(config.model_system_prompt_defaults_json or "{}")
    return defaults.get(model or config.default_model, [])


def default_model_system_prompt(config, model: str | None = None) -> str:
    """按已保存的默认文件关联组合文本，每份模板只使用一次。"""
    from backend.utils.prompt_loader import PromptLoader

    return "\n\n".join(PromptLoader.load(filename).strip() for filename in model_prompt_default_files(config, model))


def initial_model_prompt_defaults(provider: LLMProvider, models: list[str]) -> str:
    """仅在配置新增或模型列表变化时选择历史默认模板，运行时注入统一处理。"""
    import json

    files = ["deepseek_infinite_gen_4_1_flash.md", "deepseek_creative_system_prompt.md"] if provider == LLMProvider.DEEPSEEK else []
    return json.dumps({model: files for model in models}, ensure_ascii=False)
