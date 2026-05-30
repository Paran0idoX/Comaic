from datetime import datetime

from pydantic import BaseModel, Field


class CreateOutlineSessionRequest(BaseModel):
    """创建大纲会话的请求体。"""

    project_id: int = Field(gt=0)


class OutlineSessionResponse(BaseModel):
    """创建大纲会话后的响应体。"""

    session_id: int
    project_id: int
    thread_id: str
    purpose: str


class OutlineVersionResponse(BaseModel):
    """大纲版本响应体，前端用于展示当前快照和最近版本。"""

    version_id: int
    version_no: int
    outline: str
    status: str
    created_at: datetime


class OutlineMessageResponse(BaseModel):
    """大纲会话历史消息响应体。"""

    role: str
    content: str


class ResolveOutlineSessionResponse(OutlineSessionResponse):
    """复用或创建会话后的响应体，同时带回该会话的大纲版本。"""

    outline_versions: list[OutlineVersionResponse]
    messages: list[OutlineMessageResponse] = Field(default_factory=list)


class OutlineChatStreamRequest(BaseModel):
    """大纲流式对话请求体。"""

    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
