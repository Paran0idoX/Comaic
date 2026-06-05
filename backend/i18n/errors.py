import gettext
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException


LOCALE_DIR = Path(__file__).resolve().parents[1] / "locales"
DEFAULT_ERROR_CODE = "common.internal_error"


ERROR_MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "common.internal_error": "服务暂时不可用，请稍后再试。",
        "common.validation_error": "请求参数不合法。",
        "common.not_found": "资源不存在。",
        "common.required_text": "{field}不能为空。",
        "project.not_found": "项目不存在。",
        "project.title_empty": "项目标题不能为空。",
        "session.not_found": "会话不存在。",
        "outline.session_invalid": "当前会话不是大纲会话。",
        "outline.version_not_found": "大纲版本不存在。",
        "outline.version_project_mismatch": "大纲版本不属于当前项目。",
        "outline.required": "当前项目还没有可用的大纲版本。",
        "script.task_not_found": "脚本生成任务不存在。",
        "script.section_not_found": "脚本分段不存在。",
        "script.page_not_found": "页面脚本不存在。",
        "script.total_pages_invalid": "总页数必须大于 0。",
        "script.page_range_invalid": "页码必须在总页数范围内。",
        "script.generated_page_missing": "模型没有返回有效页码。",
        "script.page_field_empty": "页面脚本字段不能为空。",
        "script.section_plan_invalid": "分段计划不合法。",
        "script.section_pages_invalid": "分段页面脚本不合法。",
        "script.task_not_succeeded": "脚本任务完成后才能继续操作。",
        "script.pages_not_found": "脚本任务下没有可用页面。",
        "image_prompt.preset_not_found": "图片 Prompt 配置不存在。",
        "image_prompt.kind_invalid": "图片 Prompt 配置类型不正确。",
        "image_prompt.generated_empty": "生成的图片 Prompt 为空。",
        "image_generation.workflow_not_found": "ComfyUI Workflow 配置不存在。",
        "image_generation.page_not_found": "图片生成页面不存在。",
        "image_generation.prompt_missing": "页面缺少图片 Prompt。",
        "image_generation.prompts_not_found": "该脚本任务下没有可生成图片的 Prompt。",
        "image_generation.comfyui_no_images": "ComfyUI 没有返回图片。",
        "image_generation.file_not_found": "图片文件不存在。",
        "image_generation.workflow_json_invalid": "Workflow JSON 解析失败。",
        "image_generation.workflow_json_object_required": "Workflow JSON 必须是对象。",
        "image_generation.workflow_node_not_found": "Workflow 节点不存在。",
        "image_generation.workflow_node_inputs_missing": "Workflow 节点没有 inputs。",
        "image_generation.workflow_input_name_empty": "Workflow 输入名不能为空。",
        "image_generation.workflow_input_not_found": "Workflow 节点输入不存在。",
        "llm.config_not_found": "模型配置不存在。",
        "llm.config_missing": "请先配置模型 API Key。",
        "llm.provider_unsupported": "当前模型服务商暂不支持。",
        "llm.model_names_empty": "模型名称列表不能为空。",
        "llm.default_model_invalid": "默认模型必须包含在模型名称列表中。",
        "llm.last_config_delete_forbidden": "至少需要保留一组模型 API 配置。",
        "llm.test_failed": "模型连接测试失败，请检查 API、模型名和 Key。",
    },
    "en": {
        "common.internal_error": "The service is temporarily unavailable. Please try again later.",
        "common.validation_error": "The request parameters are invalid.",
        "common.not_found": "The resource does not exist.",
        "common.required_text": "{field} cannot be empty.",
        "project.not_found": "Project not found.",
        "project.title_empty": "Project title cannot be empty.",
        "session.not_found": "Session not found.",
        "outline.session_invalid": "This session is not an outline session.",
        "outline.version_not_found": "Outline version not found.",
        "outline.version_project_mismatch": "The outline version does not belong to this project.",
        "outline.required": "This project has no available outline version.",
        "script.task_not_found": "Script generation task not found.",
        "script.section_not_found": "Script section not found.",
        "script.page_not_found": "Page script not found.",
        "script.total_pages_invalid": "Total pages must be greater than 0.",
        "script.page_range_invalid": "Page number must be within the total page count.",
        "script.generated_page_missing": "The model did not return a valid page number.",
        "script.page_field_empty": "Page script fields cannot be empty.",
        "script.section_plan_invalid": "The section plan is invalid.",
        "script.section_pages_invalid": "The section page scripts are invalid.",
        "script.task_not_succeeded": "The script task must be completed before this operation.",
        "script.pages_not_found": "No available pages were found under this script task.",
        "image_prompt.preset_not_found": "Image prompt preset not found.",
        "image_prompt.kind_invalid": "The image prompt preset kind is invalid.",
        "image_prompt.generated_empty": "The generated image prompt is empty.",
        "image_generation.workflow_not_found": "ComfyUI workflow preset not found.",
        "image_generation.page_not_found": "Image generation page not found.",
        "image_generation.prompt_missing": "The page has no image prompt.",
        "image_generation.prompts_not_found": "No image prompts were found under this script task.",
        "image_generation.comfyui_no_images": "ComfyUI returned no images.",
        "image_generation.file_not_found": "Image file not found.",
        "image_generation.workflow_json_invalid": "Failed to parse workflow JSON.",
        "image_generation.workflow_json_object_required": "Workflow JSON must be an object.",
        "image_generation.workflow_node_not_found": "Workflow node not found.",
        "image_generation.workflow_node_inputs_missing": "Workflow node has no inputs.",
        "image_generation.workflow_input_name_empty": "Workflow input name cannot be empty.",
        "image_generation.workflow_input_not_found": "Workflow node input not found.",
        "llm.config_not_found": "LLM configuration not found.",
        "llm.config_missing": "Please configure the model API key first.",
        "llm.provider_unsupported": "This model provider is not supported yet.",
        "llm.model_names_empty": "The model name list cannot be empty.",
        "llm.default_model_invalid": "The default model must be included in the model name list.",
        "llm.last_config_delete_forbidden": "At least one model API configuration must remain.",
        "llm.test_failed": "Model connection test failed. Please check the API, model, and key.",
    },
}


@dataclass(slots=True)
class AppError(Exception):
    """带稳定错误码的业务异常，API 层负责把它翻译成本地化响应。"""

    code: str
    message_key: str | None = None
    status_code: int = 400
    params: dict[str, Any] = field(default_factory=dict)
    debug_message: str | None = None

    def __str__(self) -> str:
        return self.debug_message or self.code


def translate(message_key: str, locale: str, params: dict[str, Any] | None = None) -> str:
    """优先使用 Babel 编译出的 gettext catalog，缺失时回退到内置字典。"""

    fallback_template = ERROR_MESSAGES.get(locale, ERROR_MESSAGES["zh"]).get(
        message_key,
        ERROR_MESSAGES["zh"].get(message_key, message_key),
    )
    try:
        translation = gettext.translation("messages", localedir=LOCALE_DIR, languages=[locale])
        template = translation.gettext(message_key)
        if template == message_key:
            template = fallback_template
    except FileNotFoundError:
        template = fallback_template

    try:
        return template.format(**(params or {}))
    except (KeyError, ValueError):
        return template


def error_payload(error: AppError, locale: str) -> dict[str, Any]:
    """生成统一错误响应；开发模式可附带 debug_message 方便定位。"""

    message_key = error.message_key or error.code
    payload: dict[str, Any] = {
        "code": error.code,
        "message": translate(message_key, locale, error.params),
    }
    if os.getenv("COMAIC_DEBUG_ERRORS") == "1" and error.debug_message:
        payload["debug_message"] = error.debug_message
    return payload


def http_exception(exc: Exception, locale: str) -> HTTPException:
    """把 Service/Repository 抛出的异常转换为本地化 HTTPException。"""

    error = app_error_from_exception(exc)
    return HTTPException(status_code=error.status_code, detail=error_payload(error, locale))


def sse_error_payload(exc: Exception, locale: str) -> dict[str, Any]:
    """SSE error 事件也使用同样的 code/message 结构。"""

    return error_payload(app_error_from_exception(exc), locale)


def app_error_from_exception(exc: Exception) -> AppError:
    """兼容旧代码里的 ValueError 文案，把它们映射为稳定错误码。"""

    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, ValueError):
        code, status_code = code_from_message(str(exc))
        params: dict[str, Any] = {}
        if code == "common.required_text":
            params["field"] = str(exc).split(" cannot be empty", 1)[0]
        return AppError(code=code, status_code=status_code, params=params, debug_message=str(exc))
    return AppError(code=DEFAULT_ERROR_CODE, status_code=500, debug_message=str(exc))


def code_from_message(message: str) -> tuple[str, int]:
    """集中维护旧异常文本到错误码的映射，避免前端继续解析英文字符串。"""

    lowered = message.lower()
    if "project title cannot be empty" in lowered:
        return "project.title_empty", 400
    if "comicproject not found" in lowered:
        return "project.not_found", 404
    if "session is not an outline" in lowered:
        return "outline.session_invalid", 400
    if "session not found" in lowered:
        return "session.not_found", 404
    if "outlineversion does not belong" in lowered:
        return "outline.version_project_mismatch", 400
    if "outlineversion not found" in lowered:
        return "outline.version_not_found", 404
    if "active outline not found" in lowered:
        return "outline.required", 400
    if "scriptgenerationtask must be succeeded" in lowered:
        return "script.task_not_succeeded", 400
    if "scriptgenerationtask not found" in lowered:
        return "script.task_not_found", 404
    if "scriptsection not found" in lowered:
        return "script.section_not_found", 404
    if "comicpage not found" in lowered or "comicpage not found for project" in lowered:
        return "script.page_not_found", 404
    if "total_pages must be greater" in lowered:
        return "script.total_pages_invalid", 400
    if "page_no must be between" in lowered:
        return "script.page_range_invalid", 400
    if "generated script missing page_no" in lowered:
        return "script.generated_page_missing", 400
    if "page field cannot be empty" in lowered:
        return "script.page_field_empty", 400
    if "section plan" in lowered or "分段计划" in message:
        return "script.section_plan_invalid", 400
    if "section pages" in lowered or "page item" in lowered or "duplicate page_no" in lowered:
        return "script.section_pages_invalid", 400
    if "script pages not found" in lowered:
        return "script.pages_not_found", 404
    if "imagepromptpreset" in lowered and "kind must be" in lowered:
        return "image_prompt.kind_invalid", 400
    if "invalid image prompt preset kind" in lowered:
        return "image_prompt.kind_invalid", 400
    if "imagepromptpreset not found" in lowered:
        return "image_prompt.preset_not_found", 404
    if "generated image prompt cannot be empty" in lowered:
        return "image_prompt.generated_empty", 400
    if "image prompts not found" in lowered:
        return "image_generation.prompts_not_found", 404
    if "image prompt not found" in lowered:
        return "image_generation.prompt_missing", 400
    if "comfyworkflowpreset not found" in lowered:
        return "image_generation.workflow_not_found", 404
    if "comfyui generated no images" in lowered or "history contains no images" in lowered:
        return "image_generation.comfyui_no_images", 400
    if "workflow json is invalid" in lowered:
        return "image_generation.workflow_json_invalid", 400
    if "workflow json must be an object" in lowered:
        return "image_generation.workflow_json_object_required", 400
    if "workflow node not found" in lowered:
        return "image_generation.workflow_node_not_found", 400
    if "workflow node has no inputs" in lowered:
        return "image_generation.workflow_node_inputs_missing", 400
    if "workflow input name cannot be empty" in lowered:
        return "image_generation.workflow_input_name_empty", 400
    if "workflow node input not found" in lowered:
        return "image_generation.workflow_input_not_found", 400
    if "llmconfig not found" in lowered:
        return "llm.config_not_found", 404
    if "llmconfig api key is missing" in lowered:
        return "llm.config_missing", 400
    if "unsupported llm provider" in lowered:
        return "llm.provider_unsupported", 400
    if "llm model names cannot be empty" in lowered:
        return "llm.model_names_empty", 400
    if "llm default model must be included" in lowered:
        return "llm.default_model_invalid", 400
    if "cannot delete the last llmconfig" in lowered:
        return "llm.last_config_delete_forbidden", 400
    if "cannot be empty" in lowered:
        field_name = message.split(" cannot be empty", 1)[0]
        return "common.required_text", 400
    if "not found" in lowered:
        return "common.not_found", 404
    return "common.validation_error", 400
