"""Agent 创建辅助方法，集中创建使用标准 response_format 的结构化 Agent。"""

from typing import Any

from langchain.agents import create_agent
from pydantic import BaseModel


def create_structured_agent(
    *,
    model: Any,
    system_prompt: str,
    response_model: type[BaseModel],
    name: str,
) -> Any:
    """创建结构化 Agent；所有 Provider 统一使用 LangChain 标准 response_format。"""

    return create_agent(
        model=model,
        tools=[],
        system_prompt=system_prompt,
        response_format=response_model,
        name=name,
    )
