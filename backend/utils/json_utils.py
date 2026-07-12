import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """使用稳定排序和紧凑分隔符序列化，供快照与生成规格计算 hash。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_hash(value: Any) -> str:
    """计算规范 JSON 的 SHA-256。"""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_json_object(value: str | None, *, field_name: str) -> dict[str, Any]:
    """读取 JSON object，并在边界处给出稳定、可定位的校验错误。"""

    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return parsed


def parse_json_list(value: str | None, *, field_name: str) -> list[Any]:
    """读取 JSON array。"""

    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON array.")
    return parsed
