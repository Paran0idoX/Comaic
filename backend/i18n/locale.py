from fastapi import Request


DEFAULT_LOCALE = "zh"
SUPPORTED_LOCALES = {"zh", "en"}


def normalize_locale(value: str | None) -> str | None:
    """把请求中的语言值规整为后端支持的短语言码。"""

    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("en"):
        return "en"
    return None


def locale_from_headers(x_locale: str | None, accept_language: str | None) -> str:
    """按 X-Locale -> Accept-Language -> 默认中文 的优先级选择语言。"""

    explicit_locale = normalize_locale(x_locale)
    if explicit_locale in SUPPORTED_LOCALES:
        return explicit_locale

    if accept_language:
        for item in accept_language.split(","):
            locale = normalize_locale(item.split(";")[0])
            if locale in SUPPORTED_LOCALES:
                return locale

    return DEFAULT_LOCALE


def request_locale(request: Request) -> str:
    """从 FastAPI Request 中读取本次响应应使用的语言。"""

    return locale_from_headers(
        request.headers.get("X-Locale"),
        request.headers.get("Accept-Language"),
    )

