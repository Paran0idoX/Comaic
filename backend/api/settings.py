from fastapi import APIRouter, Request, Response, status

from backend.api.schemas.settings import (
    AppSettingsResponse,
    CreateLLMConfigRequest,
    LLMConfigListResponse,
    LLMConfigResponse,
    LLMProviderResponse,
    TestLLMConfigRequest,
    TestLLMConfigResponse,
    UpdateAppSettingsRequest,
    UpdateLLMConfigRequest,
    SystemPromptResponse,
    UpdateSystemPromptRequest,
    UpdateModelSystemPromptRequest,
)
from backend.models.enums import SystemPromptKey
from backend.api.schemas.consistency_evaluation import (
    ConsistencySettingsResponse,
    UpdateConsistencyThresholdsRequest,
)
from backend.evaluation.runtime import METRIC_VERSION
from backend.i18n.errors import http_exception
from backend.i18n.locale import request_locale
from backend.models.comic import LLMConfig
from backend.models.database import SessionLocal
from backend.repositories.comic_repository import ComicRepository
from backend.repositories.consistency_evaluation_repository import (
    ConsistencyEvaluationRepository,
)
from backend.services.consistency_evaluation_service import ConsistencyEvaluationService
from backend.services.settings_service import SettingsService


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/system-prompts", response_model=list[SystemPromptResponse])
def list_system_prompts(http_request: Request):
    """读取可维护的任务提示词白名单。"""
    db_session, service = create_service()
    try:
        return service.list_system_prompts()
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.put("/system-prompts/{key}", response_model=SystemPromptResponse)
def update_system_prompt(key: SystemPromptKey, request: UpdateSystemPromptRequest, http_request: Request):
    """更新一个任务节点或删除其覆盖。"""
    db_session, service = create_service()
    try:
        return service.update_system_prompt(key=key, content=request.content)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.get("/llm/configs/{config_id}/system-prompts", response_model=list[SystemPromptResponse])
def list_model_system_prompts(config_id: int, http_request: Request):
    """不返回 Key 等 API 敏感配置，仅返回每个模型的提示词。"""
    db_session, service = create_service()
    try:
        return service.list_model_system_prompts(config_id=config_id)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.put("/llm/configs/{config_id}/system-prompts", response_model=SystemPromptResponse)
def update_model_system_prompt(config_id: int, request: UpdateModelSystemPromptRequest, http_request: Request):
    """模型名通过请求体传递，兼容名称包含斜线的 Provider。"""
    db_session, service = create_service()
    try:
        return service.update_model_system_prompt(config_id=config_id, **request.model_dump())
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


def consistency_settings_response(
    service: ConsistencyEvaluationService,
) -> ConsistencySettingsResponse:
    config = service.get_config()
    return ConsistencySettingsResponse(
        cids_cross_min=config.cids_cross_min,
        cids_self_min=config.cids_self_min,
        csd_cross_min=config.csd_cross_min,
        csd_self_min=config.csd_self_min,
        occm_min=config.occm_min,
        copy_paste_max=config.copy_paste_max,
        runtime=service.runtime_readiness(),
        metric_version=METRIC_VERSION,
    )


def create_service() -> tuple:
    """创建设置服务及其数据库会话，由路由负责关闭。"""

    db_session = SessionLocal()
    return db_session, SettingsService(ComicRepository(db_session))


def llm_config_to_response(config: LLMConfig) -> LLMConfigResponse:
    """转换模型配置响应；只暴露 API Key 是否存在。"""

    return LLMConfigResponse(
        id=config.id,
        name=config.name,
        provider=config.provider,
        base_url=config.base_url,
        model_names=SettingsService.model_names_from_config(config),
        default_model=config.default_model,
        api_key=config.api_key,
        api_key_set=bool((config.api_key or "").strip()),
        is_active=config.is_active,
        updated_at=config.updated_at,
    )


@router.get("/app", response_model=AppSettingsResponse)
def get_app_settings(http_request: Request) -> AppSettingsResponse:
    """读取应用级运行设置。"""

    db_session, service = create_service()
    try:
        settings = service.get_app_settings()
        return AppSettingsResponse(
            script_section_max_concurrency=settings.script_section_max_concurrency,
        )
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.put("/app", response_model=AppSettingsResponse)
def update_app_settings(
    request: UpdateAppSettingsRequest,
    http_request: Request,
) -> AppSettingsResponse:
    """更新应用级运行设置。"""

    db_session, service = create_service()
    try:
        settings = service.update_app_settings(**request.model_dump())
        return AppSettingsResponse(
            script_section_max_concurrency=settings.script_section_max_concurrency,
        )
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.get("/consistency-evaluation", response_model=ConsistencySettingsResponse)
def get_consistency_evaluation_settings(
    http_request: Request,
) -> ConsistencySettingsResponse:
    """读取一致性准出阈值与当前 comaic 环境 readiness。"""

    with SessionLocal() as db_session:
        service = ConsistencyEvaluationService(
            ConsistencyEvaluationRepository(db_session)
        )
        try:
            return consistency_settings_response(service)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc


@router.put("/consistency-evaluation", response_model=ConsistencySettingsResponse)
def update_consistency_evaluation_settings(
    request: UpdateConsistencyThresholdsRequest,
    http_request: Request,
) -> ConsistencySettingsResponse:
    """更新可编辑阈值；阈值变化会让旧结果不再代表当前准出配置。"""

    with SessionLocal() as db_session:
        service = ConsistencyEvaluationService(
            ConsistencyEvaluationRepository(db_session)
        )
        try:
            service.update_config(**request.model_dump())
            return consistency_settings_response(service)
        except Exception as exc:
            raise http_exception(exc, request_locale(http_request)) from exc


@router.get("/llm", response_model=LLMConfigListResponse)
def list_llm_configs(http_request: Request) -> LLMConfigListResponse:
    """读取全部模型 API 配置。"""

    db_session, service = create_service()
    try:
        configs = service.list_llm_configs()
        active_config = next((config for config in configs if config.is_active), None)
        return LLMConfigListResponse(
            items=[llm_config_to_response(config) for config in configs],
            active_config_id=active_config.id if active_config is not None else None,
        )
    except ValueError as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.get("/llm/providers", response_model=list[LLMProviderResponse])
def list_llm_providers() -> list[LLMProviderResponse]:
    """返回设置页可选 LangChain Provider 元信息。"""

    return [
        LLMProviderResponse(**provider)
        for provider in SettingsService.provider_options()
    ]


@router.post("/llm/configs", response_model=LLMConfigResponse, status_code=status.HTTP_201_CREATED)
def create_llm_config(
    request: CreateLLMConfigRequest,
    http_request: Request,
) -> LLMConfigResponse:
    """新增一组模型 API 配置。"""

    db_session, service = create_service()
    try:
        config = service.create_llm_config(**request.model_dump())
        return llm_config_to_response(config)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.put("/llm/configs/{config_id}", response_model=LLMConfigResponse)
def update_llm_config(
    config_id: int,
    request: UpdateLLMConfigRequest,
    http_request: Request,
) -> LLMConfigResponse:
    """更新一组模型 API 配置。"""

    db_session, service = create_service()
    try:
        config = service.update_llm_config(config_id=config_id, **request.model_dump())
        return llm_config_to_response(config)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.delete("/llm/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm_config(config_id: int, http_request: Request) -> Response:
    """删除一组模型 API 配置；最后一组不允许删除。"""

    db_session, service = create_service()
    try:
        service.delete_llm_config(config_id=config_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.post("/llm/configs/{config_id}/activate", response_model=LLMConfigResponse)
def activate_llm_config(config_id: int, http_request: Request) -> LLMConfigResponse:
    """设置某组模型 API 配置为当前使用。"""

    db_session, service = create_service()
    try:
        config = service.activate_llm_config(config_id=config_id)
        return llm_config_to_response(config)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()


@router.post("/llm/test", response_model=TestLLMConfigResponse)
async def test_llm_config(
    request: TestLLMConfigRequest,
    http_request: Request,
) -> TestLLMConfigResponse:
    """使用已保存或临时表单配置做一次模型连接测试。"""

    db_session, service = create_service()
    try:
        await service.test_llm_config(**request.model_dump())
        return TestLLMConfigResponse(ok=True)
    except Exception as exc:
        raise http_exception(exc, request_locale(http_request)) from exc
    finally:
        db_session.close()
