"""实际传图顺序冻结后生成 Qwen 2.1 Prompt；暂不按模型名或 Provider 分支。"""

import json
from collections import defaultdict
from typing import Any

from backend.models.enums import ImagePromptType, VisualAssetRole, PromptLanguage
from backend.utils.prompt_loader import PromptLoader


def apply_reference_prompt(spec: dict[str, Any], items: list[dict[str, Any]]) -> None:
    """只描述实际保留的输入；单图自然引用，多图编号，历史冻结 Prompt 不经过此函数。"""
    if spec.get("reference_target"):
        _apply_reference_generation_prompt(spec, items)
        return
    language = spec.get("prompt_language", PromptLanguage.ORIGINAL.value)
    chinese = language == PromptLanguage.CHINESE.value
    templates = json.loads(PromptLoader.load("qwen21_reference_prompt_zh.json" if chinese else "qwen21_reference_prompt.json"))
    multiple = len(items) > 1
    identities = defaultdict(list)
    lines = []
    for index, item in enumerate(items, 1):
        item["label"] = f"<image{index}>" if multiple else ("该参考图" if chinese else "the image")
        owner = item.get("owner") or {}
        lines.append(templates["source"].format(
            label=item["label"],
            name=owner.get("name") or owner.get("key") or "editing canvas",
            category=templates["categories"].get(owner.get("category", "canvas"), "参考对象") if chinese else owner.get("category", "canvas"),
            key=owner.get("key") or owner.get("id", ""),
            purpose=templates["purposes"].get(item.get("purpose", ""), "图像参考") if chinese else item.get("purpose", ""),
            role=templates["role_names"].get(item.get("role", ""), "画面外观") if chinese else item.get("role", ""),
            reason=item.get("reason", ""),
        ))
        if owner.get("category") == "character" and item.get("role") in {
            VisualAssetRole.IDENTITY_FACE.value, VisualAssetRole.IDENTITY_FULL_BODY.value,
            VisualAssetRole.IDENTITY_SIDE.value, VisualAssetRole.IDENTITY_BACK.value,
        }:
            identities[owner.get("key", "")].append(item["label"])
    prompt = spec.setdefault("prompt", {})
    if spec.get("subjects") and spec.get("shot_plan"):
        from backend.services.image_spec_compilers import BaseImageSpecCompiler
        instructions = {
            subject["character_key"]: templates[
                "back_identity" if BaseImageSpecCompiler._is_back_facing(subject.get("shot") or {}) else "identity"
            ].format(
                name=subject.get("name") or subject["character_key"],
                reference=("和" if chinese else " and ").join(identities[subject["character_key"]]),
            )
            for subject in spec["subjects"]
            if identities.get(subject.get("character_key"))
        }
        if language == PromptLanguage.ORIGINAL.value:
            tags, natural = BaseImageSpecCompiler.reference_positive_components(spec, instructions)
        else:
            # 保留已转换的全部页面描述，实际传图只追加对应语言的身份说明。
            # 不能从原始设定重新投影，否则会覆盖译文并重新混入默认英文模板。
            identity_text = " ".join(instructions.values())
            tags = ", ".join(filter(None, (prompt.get("tag_text", ""), identity_text)))
            natural = " ".join(filter(None, (prompt.get("natural_language_text", ""), identity_text)))
        prompt.update(tag_text=tags, natural_language_text=natural, combined_text=natural + "\n" + tags)
        expression = spec.get("prompt_type", ImagePromptType.NATURAL_LANGUAGE.value)
        if expression == ImagePromptType.TAG.value:
            prompt["positive"] = tags
        elif expression == ImagePromptType.NATURAL_LANGUAGE.value:
            prompt["positive"] = natural
        else:
            prompt["positive"] = prompt["combined_text"]
    canvas = next((item for item in items if item.get("purpose") == "canvas"), None)
    instructions = " ".join([
        templates["canvas_header" if canvas else "header"],
        *lines,
        templates["canvas_scope"].format(canvas=canvas["label"]) if canvas else templates["source_scope"],
        templates["ownership"],
        templates["roles"],
    ])
    target = spec.get("reference_target") or {}
    if target.get("category") == "character" and identities.get(target.get("key")):
        instructions += " " + templates["identity"].format(
            name=target.get("name") or target["key"],
            reference=" and ".join(identities[target["key"]]),
        )
    # 官方增强器要求连续段落；三种表达仍保留各组件，Hybrid 仍先自然语言后 tag。
    if language == PromptLanguage.ORIGINAL.value:
        prompt["positive"] = " ".join((instructions + " " + str(prompt.get("positive") or "")).split())
    else:
        prompt["positive"] = instructions + "\n" + str(prompt.get("positive") or "")
    spec["reference_inputs"]["prompt_protocol"] = {"name": "qwen_image_2_1", "version": 2}


def _apply_reference_generation_prompt(spec, items):
    """参考原图没有漫画页面动作；一次编号说明保留用户原 Prompt 的换行和文字。"""
    templates = json.loads(PromptLoader.load("reference_generation_input_protocol.json"))
    target = spec["reference_target"]
    identities, lines = [], [templates["header"]]
    for index, item in enumerate(items, 1):
        item["label"] = f"<image{index}>" if len(items) > 1 else "the image"
        owner = item.get("owner") or {}
        lines.append(templates["source"].format(label=item["label"], name=owner.get("name") or owner.get("key") or "editing canvas",
            category=owner.get("category", "canvas"), key=owner.get("key") or owner.get("id", ""),
            purpose=item.get("purpose", ""), role=item.get("role", "")))
        if owner.get("category") == "character" and owner.get("key") == target.get("key"):
            identities.append(item["label"])
        if item.get("purpose") == "canvas":
            lines.append(templates["canvas"].format(canvas=item["label"]))
    lines.append(templates["scope"])
    if identities and target.get("category") == "character":
        key = "back_identity" if target.get("role") == VisualAssetRole.IDENTITY_BACK.value else "identity"
        lines.append(templates[key].format(name=target.get("name") or target["key"], reference=" and ".join(identities)))
    spec["prompt"]["positive"] = " ".join(lines) + "\n" + spec["prompt"]["positive"]
    spec["reference_inputs"]["prompt_protocol"] = {"name": "reference_generation", "version": 1}
