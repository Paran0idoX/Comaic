import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from backend.agents.outline_agent import OutlineAgent
from backend.api.schemas.outline import (
    CreateOutlineSessionRequest,
    OutlineMessageResponse,
    OutlineChatStreamRequest,
    OutlineSessionResponse,
    OutlineVersionResponse,
    ResolveOutlineSessionResponse,
)
from backend.models.comic import OutlineVersion
from backend.models.database import SessionLocal
from backend.models.enums import SessionPurpose
from backend.repositories.comic_repository import ComicRepository
from backend.services.comic_service import ComicService


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
    )


@router.post("/sessions", response_model=OutlineSessionResponse)
def create_outline_session(request: CreateOutlineSessionRequest) -> OutlineSessionResponse:
    """创建一个关联项目的大纲会话，并返回前端后续使用的 thread_id。"""

    with SessionLocal() as db_session:
        service = ComicService(ComicRepository(db_session))
        try:
            session = service.create_outline_session(project_id=request.project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return OutlineSessionResponse(
            session_id=session.id,
            project_id=session.project_id,
            thread_id=session.thread_id,
            purpose=session.purpose.value,
        )


@router.post("/sessions/resolve", response_model=ResolveOutlineSessionResponse)
async def resolve_outline_session(
    request: CreateOutlineSessionRequest,
) -> ResolveOutlineSessionResponse:
    """复用项目最近的大纲会话；没有会话时创建一个新的。"""

    with SessionLocal() as db_session:
        service = ComicService(ComicRepository(db_session))
        try:
            session = service.get_or_create_outline_session(project_id=request.project_id)
            versions = service.list_outline_versions(session_id=session.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
def stream_outline_chat(request: OutlineChatStreamRequest) -> EventSourceResponse:
    """用 SSE 流式返回 Agent 回复 token，并在最后返回更新后的大纲版本。"""

    async def event_generator():
        with SessionLocal() as db_session:
            repository = ComicRepository(db_session)
            service = ComicService(repository)
            session = repository.get_session_by_thread_id(request.thread_id)
            if session is None:
                yield sse_event("error", {"message": "Session not found"})
                return
            if session.purpose != SessionPurpose.OUTLINE:
                yield sse_event("error", {"message": "Session is not an outline session"})
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
                    yield sse_event(
                        "outline",
                        {
                            "version_id": outline_version.id,
                            "version_no": outline_version.version_no,
                            "outline": outline_version.content,
                            "status": outline_version.status.value,
                            "created_at": outline_version.created_at.isoformat(),
                        },
                    )
                yield sse_event("done", {"thread_id": request.thread_id})
            except Exception as exc:
                yield sse_event("error", {"message": str(exc)})

    return EventSourceResponse(event_generator())
