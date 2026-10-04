from enum import Enum


class SystemPromptKey(str, Enum):
    """设置页允许维护的任务提示词，业务协议仍由代码和只读模板约束。"""

    OUTLINE_CONVERSATION = "outline_conversation"
    OUTLINE_UPDATE = "outline_update"
    OUTLINE_CHARACTER = "outline_character"
    OUTLINE_SNAPSHOT = "outline_snapshot"
    SCRIPT_PLANNING = "script_planning"
    SCRIPT_WRITER = "script_writer"
    SCRIPT_SUPERVISOR = "script_supervisor"
    SHOT_PLANNER = "shot_planner"
    SHOT_LANGUAGE = "shot_language"


class ImageSpecStaleReason(str, Enum):
    """提示词来源变化原因，供界面翻译并引导重新准备。"""

    PAGE_SCRIPT_CHANGED = "page_script_changed"
    CHARACTER_INPUTS_CHANGED = "character_inputs_changed"
    SCENE_INPUTS_CHANGED = "scene_inputs_changed"
    PROP_INPUTS_CHANGED = "prop_inputs_changed"
    PROMPT_RULES_CHANGED = "prompt_rules_changed"
    INPUTS_CHANGED = "inputs_changed"


class OutlineEntityKind(str, Enum):
    """大纲提取时的临时实体分类，不作为角色视觉类型或数据库字段。"""

    CHARACTER = "character"
    PROP = "prop"
    SCENE = "scene"
    CONCEPT = "concept"


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


class GenerationTaskKind(str, Enum):
    """图片生成任务在批次中的层级。"""

    LEGACY = "legacy"
    BATCH = "batch"
    PAGE = "page"


class CharacterVisualType(str, Enum):
    """ViStoryBench CIDS 选择角色特征编码器时使用的角色视觉类型。"""

    REALISTIC_HUMAN = "realistic_human"
    STYLIZED_HUMAN = "stylized_human"
    NON_HUMAN = "non_human"


class ConsistencyEvaluationStatus(str, Enum):
    """一致性评估长任务的生命周期状态。"""

    PENDING = "pending"
    WAITING_RESOURCE = "waiting_resource"
    RUNNING = "running"
    SUSPENDED = "suspended"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConsistencyTrackStatus(str, Enum):
    """单条候选轨道的一致性准出结论。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


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


class PromptLanguage(str, Enum):
    """最终漫画提示词的输出语言；原文模式兼容现有编译结果。"""

    ORIGINAL = "original"
    CHINESE = "zh"
    ENGLISH = "en"


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
    IDENTITY_HALF_BODY = "identity_half_body"  # 仅解码历史记录，新生成与选图已停用。
    IDENTITY_FULL_BODY = "identity_full_body"
    IDENTITY_SIDE = "identity_side"
    IDENTITY_BACK = "identity_back"
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


class ReferenceSourceMode(str, Enum):
    """生成参考图时选择已有图片条件的方式。"""

    AUTO = "auto"
    NONE = "none"
    MANUAL = "manual"


class ReferenceImageTransport(str, Enum):
    """外部生图接口消费独立参考原图的传输方式。"""

    NONE = "none"
    MULTIPART = "multipart"
    JSON_DATA_URL = "json_data_url"


class ReferenceImageLabelFormat(str, Enum):
    """工具配置选择的有序图片编号表达。"""

    IMAGE_N = "image_N"
    PICTURE_N = "picture_N"
    BRACKET_N = "bracket_N"


class SubjectReferenceView(str, Enum):
    """镜头规划确定的目标人物视角。"""

    FRONT = "front"
    THREE_QUARTER = "three_quarter"
    SIDE = "side"
    BACK = "back"
    UNKNOWN = "unknown"


class SubjectReferenceFraming(str, Enum):
    """镜头规划确定的目标人物景别。"""

    FACE = "face"
    HALF_BODY = "half_body"
    FULL_BODY = "full_body"
    UNKNOWN = "unknown"


class ReferencePurpose(str, Enum):
    """模型无关的参考条件语义。"""

    IDENTITY = "identity"
    APPEARANCE = "appearance"
    SCENE = "scene"
    PROP = "prop"


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
    # 仅用于设定草稿的内部删除标记，保留原图归属和自动派生去重依据。
    DELETED = "deleted"


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


class ReferenceProfileKind(str, Enum):
    """参考图视觉摘要的独立来源，版本不能重新定义人物身份。"""

    CHARACTER = "character"
    OUTFIT = "outfit"
    SCENE_SUBJECT = "scene_subject"
    SCENE_VERSION = "scene_version"
    PROP_SUBJECT = "prop_subject"


class ReferenceProfileView(str, Enum):
    """视觉摘要仅使用当前可生成用途，不向模型暴露历史资产用途。"""

    IDENTITY_FACE = "identity_face"
    IDENTITY_FULL_BODY = "identity_full_body"
    IDENTITY_SIDE = "identity_side"
    IDENTITY_BACK = "identity_back"
    SCENE_MASTER = "scene_master"
    PROP_REFERENCE = "prop_reference"


class ReferenceFactKind(str, Enum):
    """视觉事实的语义，用于服装覆盖及视角投影。"""

    IDENTITY = "identity"
    FACE = "face"
    HEAD = "head"
    BODY = "body"
    CLOTHING = "clothing"
    WEARABLE = "wearable"
    COLOR = "color"
    ENVIRONMENT = "environment"
    LAYOUT = "layout"
    MATERIAL = "material"
    LIGHTING = "lighting"
    OBJECT_STATE = "object_state"
    SHAPE = "shape"


class ReferenceFactPolarity(str, Enum):
    """正向视觉事实和负向排除项必须分开。"""

    REQUIRED = "required"
    FORBIDDEN = "forbidden"
