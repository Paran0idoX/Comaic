import logging
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError


logger = logging.getLogger(__name__)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class StructuredOutputError(ValueError):
    """结构化输出调用失败，通常表示模型没有按 response_format 返回结果。"""


async def ainvoke_structured_with_retries(
    agent: Any,
    *,
    messages: Sequence[BaseMessage],
    response_model: type[ResponseT],
    operation: str,
    max_retries: int = 3,
    config: RunnableConfig | None = None,
    validator: Callable[[ResponseT], None] | None = None,
) -> ResponseT:
    """调用使用 response_format 的 Agent，并在结构化结果不可用时自动重试。

    这里是 Agent 层的通用封装，只负责读取和校验 structured_response；
    不解析自然语言、Markdown 代码块或文件输出，也不处理数据库落库。
    """

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        attempt_messages = _messages_for_attempt(
            messages=messages,
            attempt=attempt,
            last_error=last_error,
            response_model=response_model,
        )
        logger.info(
            "Structured output invoking operation=%s model=%s attempt=%s/%s",
            operation,
            response_model.__name__,
            attempt,
            max_retries,
        )

        result_state = await agent.ainvoke(
            {"messages": attempt_messages},
            config=config,
        )
        try:
            response = _parse_structured_response(
                result_state=result_state,
                response_model=response_model,
            )
            if validator is not None:
                validator(response)
            logger.info(
                "Structured output completed operation=%s model=%s attempt=%s/%s",
                operation,
                response_model.__name__,
                attempt,
                max_retries,
            )
            return response
        except (StructuredOutputError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "Structured output failed operation=%s model=%s attempt=%s/%s error=%s",
                operation,
                response_model.__name__,
                attempt,
                max_retries,
                exc,
            )

    raise StructuredOutputError(
        f"{operation} failed to return valid {response_model.__name__} "
        f"after {max_retries} attempts: {last_error}"
    )


def _parse_structured_response(
    *,
    result_state: dict[str, Any],
    response_model: type[ResponseT],
) -> ResponseT:
    """把不同形态的 structured_response 统一校验成目标 Pydantic 模型。"""

    structured_response = result_state.get("structured_response")
    if structured_response is None:
        raise StructuredOutputError("Agent returned no structured_response.")

    if isinstance(structured_response, response_model):
        return structured_response
    if isinstance(structured_response, dict):
        return response_model.model_validate(structured_response)
    if hasattr(structured_response, "model_dump"):
        return response_model.model_validate(structured_response.model_dump())

    raise StructuredOutputError(
        f"Unsupported structured_response type: {type(structured_response)!r}"
    )


def _messages_for_attempt(
    *,
    messages: Sequence[BaseMessage],
    attempt: int,
    last_error: Exception | None,
    response_model: type[BaseModel],
) -> list[BaseMessage]:
    """每次重试复制原始消息，并追加一条结构化输出反馈。"""

    attempt_messages = list(messages)
    if attempt == 1 or last_error is None:
        return attempt_messages

    attempt_messages.append(
        HumanMessage(
            content="\n\n".join(
                [
                    "结构化输出重试要求：",
                    f"上一次调用没有返回可用的 structured_response，或 structured_response 不符合 {response_model.__name__}。",
                    "请不要输出 Markdown、代码块、解释性文字或把结果写入文件；必须通过 response_format 返回结构化结果。",
                    f"上一次失败原因：{last_error}",
                ]
            )
        )
    )
    return attempt_messages
