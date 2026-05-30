from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.outline import router as outline_router
from backend.api.projects import router as projects_router
from backend.models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用启动时初始化数据库表，方便本地 MVP 开发。"""

    init_db()
    yield


app = FastAPI(title="comaic backend", lifespan=lifespan)
app.include_router(outline_router)
app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查接口，用于确认后端服务已启动。"""

    return {"status": "ok"}
