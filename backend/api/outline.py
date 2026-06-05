import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.agents.outline_agent import OutlineAgent
from backend.api.schemas.outline import (
    CreateOutlineSessionRequest,
    OutlineCharacterResponse,
    OutlineMessageResponse,
    OutlineChatStreamRequest,
    OutlineSessionResponse,
    OutlineVersionResponse,
    ResolveOutlineSessionResponse,
)
from backend.models.comic import OutlineCharacter, OutlineVersion
from backend.models.database import SessionLocal
from backend.models.enums import SessionPurpose
from backend.repositories.comic_repository import ComicRepository
from backend.i18n.errors import AppError, http_exception, sse_error_payload
from backend.i18n.locale import request_locale
from backend.services.outline_service import OutlineService


router = APIRouter(prefix="/api/outline", tags=["outline"])


def sse_event(event: str, payload: dict) -> dict[str, str]:
    """统一把 Python 字典编码为 SSE 事件。"""

    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False),
    }


def outline_version_to_response(version: OutlineVersion) -> OutlineVersionResponse:
    """把大纲版本 ORM 对象转换为前端稳定使用的响应结构。"""

    return OutlineVersionResponse(
        version_id=version.id,
        version_no=version.version_no,
        outline=version.content,
        status=version.status.value,
        created_at=version.created_at,
        confirmed_at=version.confirmed_at,
        characters=[
            outline_character_to_response(character)
            for character in sorted(version.characters, key=lambda item: item.character_key)
        ],
    )


def outline_character_to_response(character: OutlineCharacter) -> OutlineCharacterResponse:
    """把大纲角色基准设定 ORM 对象转换为 API 响应。"""

    return OutlineCharacterResponse(
        id=character.id,
        outline_version_id=character.outline_version_id,
        character_key=character.character_key,
        name=character.name,
        role=character.role,
        background=character.background,
        appearance=character.appearance,
        visual_anchors=character.visual_anchors,
        negative_constraints=character.negative_constraints,
        default_hairstyle=character.default_hairstyle,
        default_clothing=character.default_clothing,
        default_accessories=character.default_accessories,
        default_color_palette=character.default_color_palette,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


@router.post("/sessions", response_model=OutlineSessionResponse)
def create_outline_session(
    request: CreateOutlineSessionRequest,
    http_request: Request,
) -> OutlineSessionResponse:
    """创建一个关联项目的大纲会话，并返回前端后续使用的 thread_id。"""

    with SessionLocal() as db_session:
        service = OutlineService(ComicRepository(db_session))
        try:
            session = service.create_outline_session(project_id=request.project_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc

        return OutlineSessionResponse(
            session_id=session.id,
            project_id=session.project_id,
            thread_id=session.thread_id,
            purpose=session.purpose.value,
        )


@router.post("/sessions/resolve", response_model=ResolveOutlineSessionResponse)
async def resolve_outline_session(
    request: CreateOutlineSessionRequest,
    http_request: Request,
) -> ResolveOutlineSessionResponse:
    """复用项目最近的大纲会话；没有会话时创建一个新的。"""

    with SessionLocal() as db_session:
        service = OutlineService(ComicRepository(db_session))
        try:
            session = service.get_or_create_outline_session(project_id=request.project_id)
            versions = service.list_outline_versions(session_id=session.id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc

        async with OutlineAgent() as agent:
            history_messages = await agent.get_conversation_messages(
                thread_id=session.thread_id,
            )

        return ResolveOutlineSessionResponse(
            session_id=session.id,
            project_id=session.project_id,
            thread_id=session.thread_id,
            purpose=session.purpose.value,
            outline_versions=[
                outline_version_to_response(version)
                for version in sorted(
                    versions,
                    key=lambda item: item.version_no,
                    reverse=True,
                )
            ],
            messages=[
                OutlineMessageResponse(
                    role=message["role"],
                    content=message["content"],
                )
                for message in history_messages
            ],
        )


@router.post("/chat/stream")
def stream_outline_chat(request: OutlineChatStreamRequest, http_request: Request) -> EventSourceResponse:
    """用 SSE 流式返回 Agent 回复 token，并在最后返回更新后的大纲版本。"""

    locale = request_locale(http_request)

    async def event_generator():
        with SessionLocal() as db_session:
            repository = ComicRepository(db_session)
            service = OutlineService(repository)
            session = repository.get_session_by_thread_id(request.thread_id)
            if session is None:
                yield sse_event(
                    "error",
                    sse_error_payload(AppError("session.not_found", status_code=404), locale),
                )
                return
            if session.purpose != SessionPurpose.OUTLINE:
                yield sse_event(
                    "error",
                    sse_error_payload(AppError("outline.session_invalid", status_code=400), locale),
                )
                return

            try:
                current_outline = service.get_current_outline(session_id=session.id)
                async with OutlineAgent() as agent:
                    async for token in agent.chat(
                        thread_id=request.thread_id,
                        user_message=request.message,
                        current_outline=current_outline,
                    ):
                        yield sse_event("token", {"text": token})

                    outline = agent.consume_updated_outline()

                if outline:
                    outline_version = service.save_outline_snapshot(
                        thread_id=request.thread_id,
                        outline=outline,
                    )
                    await service.generate_and_save_outline_characters(
                        outline_version=outline_version,
                        user_message=request.message,
                    )
                    yield sse_event(
                        "outline",
                        outline_version_to_response(outline_version).model_dump(mode="json"),
                    )
                yield sse_event("done", {"thread_id": request.thread_id})
            except Exception as exc:
                yield sse_event("error", sse_error_payload(exc, locale))

    return EventSourceResponse(event_generator())


@router.post("/versions/{version_id}/confirm", response_model=OutlineVersionResponse)
def confirm_outline_version(version_id: int, http_request: Request) -> OutlineVersionResponse:
    """确认大纲版本和该版本下的角色基准设定。"""

    with SessionLocal() as db_session:
        service = OutlineService(ComicRepository(db_session))
        try:
            outline_version = service.confirm_outline_version(outline_version_id=version_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(http_request)) from exc
        return outline_version_to_response(outline_version)
