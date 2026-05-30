from enum import Enum


class ComicPageStatus(str, Enum):
    """漫画页面在 MVP 流程中的处理状态。"""

    DRAFT = "draft"
    SCRIPT_READY = "script_ready"
    PROMPT_READY = "prompt_ready"
    IMAGE_SELECTED = "image_selected"


class GenerationTaskStatus(str, Enum):
    """ComfyUI 出图任务的生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SessionPurpose(str, Enum):
    """通用会话的业务用途。"""

    OUTLINE = "outline"


class OutlineVersionStatus(str, Enum):
    """大纲版本的生效状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
