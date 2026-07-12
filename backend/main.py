from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.image_generation import router as image_generation_router
from backend.api.image_specs import router as image_specs_router
from backend.api.outline import router as outline_router
from backend.api.projects import router as projects_router
from backend.api.scripts import project_pages_router, router as scripts_router
from backend.api.settings import router as settings_router
from backend.api.visual_bible import router as visual_bible_router
from backend.i18n.errors import (
    AppError,
    app_error_from_exception,
    error_payload,
    log_api_exception,
)
from backend.i18n.locale import request_locale
from backend.models.database import init_db
from backend.services.task_runtime import start_task_runtime_threads


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用启动时初始化数据库，并启动长任务心跳与僵尸扫描线程。"""

    logger.info("Initializing database")
    init_db()
    logger.info("Database ready")
    task_runtime = start_task_runtime_threads()
    try:
        yield
    finally:
        task_runtime.stop()


app = FastAPI(title="comaic backend", lifespan=lifespan)


@app.middleware("http")
async def handle_unhandled_api_exception(request: Request, call_next):
    """兜底记录未进入统一错误转换的异常，并返回稳定的本地化错误结构。"""

    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 - API 最外层必须把未知异常记录并转换为稳定响应
        error = app_error_from_exception(exc)
        log_api_exception(
            exc,
            error,
            source=f"http {request.method} {request.url.path}",
        )
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error_payload(error, request_locale(request))},
        )


app.include_router(outline_router)
app.include_router(projects_router)
app.include_router(scripts_router)
app.include_router(project_pages_router)
app.include_router(image_specs_router)
app.include_router(image_generation_router)
app.include_router(settings_router)
app.include_router(visual_bible_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 FastAPI 参数校验错误也转换成稳定 code，避免前端解析英文 detail。"""

    logger.warning(
        "API validation error method=%s path=%s error_count=%s",
        request.method,
        request.url.path,
        len(exc.errors()),
    )
    error = AppError(
        code="common.validation_error",
        status_code=422,
        debug_message=str(exc),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": error_payload(error, request_locale(request))},
    )


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查接口，用于确认后端服务已启动。"""

    return {"status": "ok"}
