"""参考图按用途设置尺寸；只消费工具声明的绑定，不猜测模型或节点。"""

from backend.i18n.errors import AppError
from backend.models.enums import ImageGenerationProvider, VisualAssetRole
from backend.services.workflow_compiler import parse_bindings


def supports_reference_size(tool) -> bool:
    """宽高必须同时绑定；外部图片 API 通过其 size 参数传递。"""
    if tool.provider == ImageGenerationProvider.OPENAI_IMAGES_COMPATIBLE:
        return True
    sources = {item.source for item in parse_bindings(tool.bindings_json).bindings}
    return {"render.width", "render.height"}.issubset(sources)


def reference_sizes(tool, roles, sizes=None) -> dict:
    """旧工具未传尺寸时保持兼容；显式尺寸无法消费时必须在提交前失败。"""
    sizes = sizes or {}
    if set(sizes) - {role.value for role in roles}:
        raise AppError("reference.size_invalid", status_code=422)
    if not supports_reference_size(tool):
        if sizes:
            raise AppError("reference.size_unsupported", status_code=422)
        return {}
    result = {}
    for role in roles:
        default = {"width": 768, "height": 768} if role == VisualAssetRole.IDENTITY_FACE else (
            {"width": 512, "height": 768} if role in {
                VisualAssetRole.IDENTITY_FULL_BODY, VisualAssetRole.IDENTITY_SIDE, VisualAssetRole.IDENTITY_BACK
            } else {"width": 1024, "height": 1024})
        size = sizes.get(role.value, default)
        if (not isinstance(size, dict) or set(size) != {"width", "height"}
                or any(type(value) is not int or not 256 <= value <= 2048 or value % 32
                       for value in size.values())):
            raise AppError("reference.size_invalid", status_code=422)
        result[role.value] = dict(size)
    return result
