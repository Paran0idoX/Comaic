from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from backend.api.image_generation import router as image_generation_router
from backend.api.image_prompts import router as image_prompts_router
from backend.api.outline import router as outline_router
from backend.api.projects import router as projects_router
from backend.api.scripts import project_pages_router, router as scripts_router
from backend.models.database import init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用启动时初始化数据库表，方便本地 MVP 开发。"""

    logger.info("Initializing database")
    init_db()
    logger.info("Database ready")
    yield


app = FastAPI(title="comaic backend", lifespan=lifespan)
app.include_router(outline_router)
app.include_router(projects_router)
app.include_router(scripts_router)
app.include_router(project_pages_router)
app.include_router(image_prompts_router)
app.include_router(image_generation_router)


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查接口，用于确认后端服务已启动。"""

    return {"status": "ok"}
