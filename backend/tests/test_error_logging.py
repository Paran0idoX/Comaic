import asyncio
import logging

from backend.agents.outline_agent import OutlineAgent
from backend.i18n.errors import AppError, error_payload, http_exception, sse_error_payload


def test_http_exception_logs_stable_business_error(caplog) -> None:
    """业务错误转换为 HTTP 响应时，也应留下可检索的 warning。"""

    with caplog.at_level(logging.WARNING, logger="backend.i18n.errors"):
        result = http_exception(ValueError("LLMConfig API key is missing."), "zh")

    assert result.status_code == 400
    assert result.detail["code"] == "llm.config_missing"
    assert "status=400" in caplog.text
    assert "code=llm.config_missing" in caplog.text
    assert "exception=ValueError" in caplog.text


def test_unexpected_error_log_redacts_secret_and_keeps_stack(caplog) -> None:
    """未知异常保留定位堆栈，但异常消息中的凭据必须脱敏。"""

    try:
        raise RuntimeError("Authorization: Bearer top-secret-token")
    except RuntimeError as exc:
        with caplog.at_level(logging.ERROR, logger="backend.i18n.errors"):
            payload = sse_error_payload(exc, "en")

    assert payload["code"] == "common.internal_error"
    assert "top-secret-token" not in caplog.text
    assert "Authorization: ***" in caplog.text
    assert "Traceback frames:" in caplog.text
    assert "exception=RuntimeError" in caplog.text


def test_debug_error_payload_redacts_api_key(monkeypatch) -> None:
    """即使显式启用调试错误，也不能把完整 API Key 返回给前端。"""

    monkeypatch.setenv("COMAIC_DEBUG_ERRORS", "1")
    payload = error_payload(
        AppError(
            code="common.internal_error",
            status_code=500,
            debug_message="api_key=sk-sensitive-value",
        ),
        "en",
    )

    assert payload["debug_message"] == "api_key=***"


def test_checkpoint_history_load_does_not_require_llm(tmp_path) -> None:
    """恢复空会话历史不应构造 LLM，也不应要求设置 API Key。"""

    messages = asyncio.run(
        OutlineAgent.load_conversation_messages(
            thread_id="empty-thread",
            memory_path=tmp_path / "outline-memory.sqlite3",
        )
    )

    assert messages == []
