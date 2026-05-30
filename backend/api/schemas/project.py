from datetime import datetime

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    """创建项目请求体；MVP 第一版只接收项目标题。"""

    title: str = Field(min_length=1, max_length=255)


class UpdateProjectRequest(BaseModel):
    """更新项目请求体；当前只允许修改标题。"""

    title: str = Field(min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    """项目接口响应体，供前端列表和编辑弹窗复用。"""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """项目列表响应体，后续添加分页字段时可以保持外层结构稳定。"""

    items: list[ProjectResponse]
