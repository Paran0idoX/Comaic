from enum import Enum


class ComicPageStatus(str, Enum):
    """漫画页面在 MVP 流程中的处理状态。"""

    DRAFT = "draft"
    SCRIPT_READY = "script_ready"
    PROMPT_READY = "prompt_ready"
    IMAGE_READY = "image_ready"
    IMAGE_SELECTED = "image_selected"


class PageScriptReviewStatus(str, Enum):
    """分页脚本在脚本生成阶段的逐页审查状态。"""

    UNREVIEWED = "unreviewed"
    REVIEWING = "reviewing"
    PASSED = "passed"
    FAILED = "failed"


class ScriptSectionStatus(str, Enum):
    """分页脚本分段生成状态。"""

    GENERATING = "generating"
    FAILED = "failed"
    COMPLETED = "completed"


class GenerationTaskStatus(str, Enum):
    """ComfyUI 出图任务的生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScriptGenerationTaskStatus(str, Enum):
    """分页脚本生成任务的生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScriptGenerationMode(str, Enum):
    """分页脚本生成模式。"""

    SINGLE = "single"
    BATCH = "batch"


class SessionPurpose(str, Enum):
    """通用会话的业务用途。"""

    OUTLINE = "outline"


class OutlineVersionStatus(str, Enum):
    """大纲版本的生效状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ImagePromptPresetKind(str, Enum):
    """图片 Prompt 配置类型，用于区分脚本转图 Prompt 和负向 Prompt。"""

    SCRIPT_TO_IMAGE_SYSTEM_PROMPT = "script_to_image_system_prompt"
    NEGATIVE_PROMPT = "negative_prompt"


class ImageGenerationToolKind(str, Enum):
    """图片生成工具类型。"""

    COMFYUI = "comfyui"
    OPENAI_IMAGES_COMPATIBLE = "openai_images_compatible"


class LLMProvider(str, Enum):
    """LLM 服务商类型；设置页可选择 LangChain Provider 或 OpenAI 兼容接口。"""

    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    GOOGLE_GENAI = "google_genai"
    MISTRALAI = "mistralai"
    GROQ = "groq"
    COHERE = "cohere"
    OLLAMA = "ollama"
    AWS_BEDROCK = "aws_bedrock"
    XAI = "xai"
