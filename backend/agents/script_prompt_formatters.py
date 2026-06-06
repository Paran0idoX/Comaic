from typing import Any


def format_section(section: dict[str, Any] | None) -> str:
    """把分段数据转成自然语言，避免把数据库字段原样暴露给模型。"""

    if not section:
        return "未提供分段信息。"

    section_no = _text(section.get("section_no"), "未知")
    page_start = _text(section.get("page_start"), "未知")
    page_end = _text(section.get("page_end"), "未知")
    title = _text(section.get("title"))
    description = _text(section.get("description"))
    return "\n".join(
        [
            f"第 {section_no} 段，页码范围：第 {page_start}-{page_end} 页。",
            f"分段标题：{title}",
            f"分段内容：{description}",
        ]
    )


def format_scenes(scenes: list[dict[str, Any]] | None) -> str:
    """格式化中心化场景设定，只保留创作需要的稳定视觉信息。"""

    if not scenes:
        return "无可引用的中心化场景设定。"

    return "\n\n".join(_format_scene(scene) for scene in scenes)


def format_section_characters(characters: list[dict[str, Any]] | None) -> str:
    """格式化当前分段角色细化设定，强调只能引用这些 character_key。"""

    if not characters:
        return "无可引用的分段角色细化设定。"

    return "\n\n".join(_format_section_character(character) for character in characters)


def format_outline_characters(characters: list[dict[str, Any]] | None) -> str:
    """格式化大纲阶段角色基准设定，用于约束跨分段角色一致性。"""

    if not characters:
        return "暂无大纲阶段确认的角色基准设定。"

    return "\n\n".join(_format_outline_character(character) for character in characters)


def format_previous_context(previous_context: dict[str, Any] | None) -> str:
    """格式化已完成分段上下文，给模型衔接参考但避免大段 JSON 干扰。"""

    if not previous_context:
        return "暂无已完成分段。"

    parts: list[str] = []
    summaries = previous_context.get("completed_section_summaries") or []
    if summaries:
        parts.append("已完成分段摘要：")
        parts.extend(_format_completed_section(summary) for summary in summaries)

    recent_sections = previous_context.get("recent_full_sections") or []
    if recent_sections:
        parts.append("最近两个已完成分段的完整页面脚本：")
        parts.extend(_format_recent_section(section) for section in recent_sections)

    known_scenes = previous_context.get("known_scenes") or []
    if known_scenes:
        parts.append("此前已经出现过的场景设定：")
        parts.append(format_scenes(known_scenes))

    return "\n\n".join(parts) if parts else "暂无已完成分段。"


def format_pages(pages: list[dict[str, Any]] | None) -> str:
    """格式化待审查或已生成的分页脚本。"""

    if not pages:
        return "暂无页面脚本。"

    return "\n\n".join(_format_page(page) for page in pages)


def _format_scene(scene: dict[str, Any]) -> str:
    scene_key = _text(scene.get("scene_key"), "未命名场景")
    return "\n".join(
        [
            f"- 场景 key：{scene_key}",
            f"  场景名称：{_text(scene.get('name'))}",
            f"  地点类型：{_text(scene.get('location_type'))}",
            f"  时间与光线：{_text(scene.get('time_of_day'))}；{_text(scene.get('lighting'))}",
            f"  天气或空气状态：{_text(scene.get('weather'))}",
            f"  稳定环境细节：{_text(scene.get('environment_details'))}",
            f"  主色调：{_text(scene.get('color_palette'))}",
            f"  跨页视觉锚点：{_text(scene.get('visual_anchors'))}",
            f"  场景禁止项：{_text(scene.get('negative_constraints'))}",
        ]
    )


def _format_section_character(character: dict[str, Any]) -> str:
    character_key = _text(character.get("character_key"), "未命名角色")
    outline_character = character.get("outline_character")
    lines = [
        f"- 角色 key：{character_key}",
        f"  角色名称：{_text(character.get('name'))}",
        f"  当前分段功能：{_text(character.get('section_role'))}",
        f"  当前发型：{_text(character.get('current_hairstyle'))}",
        f"  当前服装：{_text(character.get('current_clothing'))}",
        f"  当前配件：{_text(character.get('current_accessories'))}",
        f"  当前身体状态：{_text(character.get('current_state'))}",
        f"  当前情绪：{_text(character.get('emotion'))}",
        f"  临时变化：{_text(character.get('temporary_changes'), '无')}",
        f"  分段视觉锚点：{_text(character.get('visual_anchors'))}",
        f"  分段禁止项：{_text(character.get('negative_constraints'))}",
    ]
    if isinstance(outline_character, dict):
        lines.append("  对应大纲角色基准：")
        lines.append(_indent(_format_outline_character(outline_character), "    "))
    return "\n".join(lines)


def _format_outline_character(character: dict[str, Any]) -> str:
    character_key = _text(character.get("character_key"), "未命名角色")
    return "\n".join(
        [
            f"- 角色 key：{character_key}",
            f"  角色名称：{_text(character.get('name'))}",
            f"  身份/叙事角色：{_text(character.get('role'))}",
            f"  背景设定：{_text(character.get('background'))}",
            f"  固定样貌：{_text(character.get('appearance'))}",
            f"  固定视觉锚点：{_text(character.get('visual_anchors'))}",
            f"  禁止改写项：{_text(character.get('negative_constraints'))}",
            f"  默认发型：{_text(character.get('default_hairstyle'))}",
            f"  默认服装：{_text(character.get('default_clothing'))}",
            f"  默认配件：{_text(character.get('default_accessories'))}",
            f"  默认色彩：{_text(character.get('default_color_palette'))}",
        ]
    )


def _format_completed_section(section: dict[str, Any]) -> str:
    section_no = _text(section.get("section_no"), "未知")
    page_start = _text(section.get("page_start"), "未知")
    page_end = _text(section.get("page_end"), "未知")
    generated_pages = _text(section.get("generated_pages"), "0")
    return "\n".join(
        [
            f"- 第 {section_no} 段（第 {page_start}-{page_end} 页）：{_text(section.get('title'))}",
            f"  分段内容：{_text(section.get('description'))}",
            f"  已生成页数：{generated_pages}",
            f"  页面摘要：{_text(section.get('script_summary'))}",
        ]
    )


def _format_recent_section(section: dict[str, Any]) -> str:
    section_no = _text(section.get("section_no"), "未知")
    page_start = _text(section.get("page_start"), "未知")
    page_end = _text(section.get("page_end"), "未知")
    pages = section.get("pages") or []
    lines = [
        f"- 第 {section_no} 段（第 {page_start}-{page_end} 页）：{_text(section.get('title'))}",
    ]
    lines.extend(_indent(_format_page(page), "  ") for page in pages)
    return "\n".join(lines)


def _format_page(page: dict[str, Any]) -> str:
    character_keys = page.get("character_keys") or []
    if isinstance(character_keys, list):
        character_keys_text = "、".join(str(item) for item in character_keys) or "无"
    else:
        character_keys_text = _text(character_keys, "无")

    lines = [
        f"- 第 {_text(page.get('page_no'), '未知')} 页",
        f"  所属分段：第 {_text(page.get('section_no'), '未知')} 段",
        f"  场景 key：{_text(page.get('scene_key'))}",
        f"  角色 key：{character_keys_text}",
        f"  摘要：{_text(page.get('summary'))}",
        f"  人物：{_text(page.get('characters'))}",
        f"  服装：{_text(page.get('clothing'))}",
        f"  场景：{_text(page.get('scene'))}",
        f"  构图：{_text(page.get('composition'))}",
        f"  人物动作：{_text(page.get('character_action'))}",
        f"  对话/旁白：{_text(page.get('dialogue'), '无')}",
    ]
    if page.get("is_revision"):
        lines.append(f"  修订说明：{_text(page.get('revision_note'))}")
    return "\n".join(lines)


def _text(value: Any, default: str = "未设定") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" if line else line for line in text.splitlines())
