from enum import Enum


class ComicPageStatus(str, Enum):
    """漫画页面在 MVP 流程中的处理状态。"""

    DRAFT = "draft"
    SCRIPT_READY = "script_ready"
    SPEC_READY = "spec_ready"
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
    """视觉规格配置类型。"""

    SHOT_PLANNER_SYSTEM_PROMPT = "shot_planner_system_prompt"
    NEGATIVE_PROMPT = "negative_prompt"


class ImageGenerationProvider(str, Enum):
    """图片生成执行端类型；只描述调用协议，不描述具体底模。"""

    COMFYUI = "comfyui"
    OPENAI_IMAGES_COMPATIBLE = "openai_images_compatible"


class ImagePromptType(str, Enum):
    """ImageSpec 的 Prompt 表达类型。"""

    TAG = "tag"
    NATURAL_LANGUAGE = "natural_language"
    HYBRID = "hybrid"


class WorkflowCapability(str, Enum):
    """Renderer workflow 可声明并由 ImageSpec 请求的固定能力。"""

    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    REFERENCE_IMAGE = "reference_image"
    LORA = "lora"
    POSE = "pose"
    DEPTH = "depth"
    CANNY = "canny"
    LINEART = "lineart"
    REGIONAL_CONDITION = "regional_condition"
    INPAINT = "inpaint"


class VisualEntityType(str, Enum):
    """视觉资产归属的业务实体类型。"""

    CHARACTER = "character"
    OUTFIT = "outfit"
    SCENE = "scene"
    STYLE = "style"
    PROP = "prop"
    CONTROL = "control"


class VisualAssetRole(str, Enum):
    """视觉资产在生图条件中的固定用途。"""

    IDENTITY_FACE = "identity_face"
    IDENTITY_HALF_BODY = "identity_half_body"
    IDENTITY_FULL_BODY = "identity_full_body"
    OUTFIT_FRONT = "outfit_front"
    OUTFIT_BACK = "outfit_back"
    OUTFIT_DETAIL = "outfit_detail"
    SCENE_MASTER = "scene_master"
    STYLE_REFERENCE = "style_reference"
    PROP_REFERENCE = "prop_reference"
    POSE = "pose"
    DEPTH = "depth"
    CANNY = "canny"
    LINEART = "lineart"
    SEGMENTATION = "segmentation"
    MASK = "mask"
    LORA = "lora"


class VisualAssetSource(str, Enum):
    """视觉资产的来源。"""

    UPLOAD = "upload"
    GENERATED_IMAGE = "generated_image"
    RENDERER_LOCATOR = "renderer_locator"


class VisualAssetStorageKind(str, Enum):
    """视觉资产的存储方式。"""

    LOCAL_FILE = "local_file"
    RENDERER_LOCATOR = "renderer_locator"


class ApprovalStatus(str, Enum):
    """需要人工确认的视觉配置通用状态。"""

    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class CompilationStatus(str, Enum):
    """连续性或视觉规格编译状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ContinuityEventType(str, Enum):
    """允许连续性状态机修改的受控事件类型。"""

    SET_HAIRSTYLE = "set_hairstyle"
    SET_OUTFIT = "set_outfit"
    SET_ACCESSORY = "set_accessory"
    SET_GARMENT_STATE = "set_garment_state"
    SET_CLOTHING_CONDITION = "set_clothing_condition"
    SET_CHARACTER_CONDITION = "set_character_condition"
    PICK_UP_PROP = "pick_up_prop"
    DROP_PROP = "drop_prop"
    TRANSFER_PROP = "transfer_prop"
    SET_LIGHT_STATE = "set_light_state"
    SET_DOOR_STATE = "set_door_state"
    SET_OBJECT_STATE = "set_object_state"
    BREAK_OBJECT = "break_object"
    SET_WEATHER = "set_weather"
    ADVANCE_TIME = "advance_time"


class ContinuityTargetType(str, Enum):
    """连续性事件的目标类型。"""

    CHARACTER = "character"
    SCENE = "scene"
    PROP = "prop"


class ContinuityEventTiming(str, Enum):
    """事件相对于当前页面状态快照的生效时机。"""

    BEFORE_PAGE = "before_page"
    AFTER_PAGE = "after_page"


class ContinuityEventSource(str, Enum):
    """连续性事件由谁产生。"""

    LLM = "llm"
    MANUAL = "manual"
    SYSTEM = "system"


class GenerationMode(str, Enum):
    """图片规格和生成的一致性严格程度。"""

    PREVIEW = "preview"
    FINAL = "final"


class SeedStrategy(str, Enum):
    """批量出图时的 seed 分配策略。"""

    PER_PAGE = "per_page"
    SHARED_CANDIDATE = "shared_candidate"


class GenerationRunStatus(str, Enum):
    """单次候选图外部请求的状态。"""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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
