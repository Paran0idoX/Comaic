"""可扩展的固定参考图目录；显示分类不改变历史资产枚举用途。"""

from backend.models.enums import VisualAssetRole, VisualEntityType


CHARACTER_REFERENCE_ROLES = (
    VisualAssetRole.IDENTITY_FACE,
    VisualAssetRole.IDENTITY_FULL_BODY,
    VisualAssetRole.IDENTITY_SIDE,
    VisualAssetRole.IDENTITY_BACK,
)
# 兼容人物整套生成入口只生成脸部和正面全身；侧面、背面在目录中按需生成。
DEFAULT_CHARACTER_REFERENCE_ROLES = (
    VisualAssetRole.IDENTITY_FACE,
    VisualAssetRole.IDENTITY_FULL_BODY,
)
REFERENCE_CATALOG = {
    VisualEntityType.CHARACTER: CHARACTER_REFERENCE_ROLES,
    VisualEntityType.SCENE: (VisualAssetRole.SCENE_MASTER,),
    VisualEntityType.PROP: (VisualAssetRole.PROP_REFERENCE,),
}


def selected_task_roles(task) -> tuple[VisualAssetRole, ...]:
    """历史任务没有快照时从实际运行恢复，绝不扩大为当前目录的所有类别。"""
    import json

    values = json.loads(task.selected_roles_json or "[]")
    if not values:
        values = list(dict.fromkeys(run.role.value for run in task.runs))
    return tuple(VisualAssetRole(value) for value in values)
