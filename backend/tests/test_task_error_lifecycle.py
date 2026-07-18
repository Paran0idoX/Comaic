from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.comic import ComicProject, GenerationTask, ScriptGenerationTask
from backend.models.database import Base
from backend.models.enums import (
    GenerationTaskStatus,
    ScriptGenerationMode,
    ScriptGenerationTaskStatus,
)
from backend.repositories.comic_repository import ComicRepository


def _repository() -> tuple[ComicRepository, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    return ComicRepository(session), session


def test_script_task_retry_and_success_clear_stale_error() -> None:
    repository, session = _repository()
    try:
        project = ComicProject(title="task lifecycle")
        session.add(project)
        session.flush()
        task = ScriptGenerationTask(
            project_id=project.id,
            status=ScriptGenerationTaskStatus.FAILED,
            mode=ScriptGenerationMode.BATCH,
            total_pages=1,
            error_message="old validation failure",
        )
        session.add(task)
        session.commit()

        running = repository.update_script_task(
            task_id=task.id,
            status=ScriptGenerationTaskStatus.RUNNING,
        )
        assert running.error_message is None

        repository.update_script_task(
            task_id=task.id,
            status=ScriptGenerationTaskStatus.FAILED,
            error_message="new failure",
        )
        succeeded = repository.update_script_task(
            task_id=task.id,
            status=ScriptGenerationTaskStatus.SUCCEEDED,
        )
        assert succeeded.error_message is None
    finally:
        session.close()


def test_generation_task_retry_and_success_clear_stale_error() -> None:
    repository, session = _repository()
    try:
        project = ComicProject(title="generation lifecycle")
        session.add(project)
        session.flush()
        task = GenerationTask(
            project_id=project.id,
            status=GenerationTaskStatus.FAILED,
            batch_size=1,
            error_message="old ComfyUI failure",
        )
        session.add(task)
        session.commit()

        running = repository.update_generation_task(
            task_id=task.id,
            status=GenerationTaskStatus.RUNNING,
        )
        assert running.error_message is None

        repository.update_generation_task(
            task_id=task.id,
            status=GenerationTaskStatus.FAILED,
            error_message="new failure",
        )
        succeeded = repository.update_generation_task(
            task_id=task.id,
            status=GenerationTaskStatus.SUCCEEDED,
        )
        assert succeeded.error_message is None
    finally:
        session.close()
