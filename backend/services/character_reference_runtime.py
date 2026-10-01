"""串行执行人物参考图任务，避免同一进程并发挤占本地 Renderer。"""

from __future__ import annotations

import asyncio
import logging
from queue import Queue
import threading

from backend.models.database import SessionLocal
from backend.repositories.character_reference_repository import (
    CharacterReferenceRepository,
)
from backend.services.reference_image_service import ReferenceImageService


logger = logging.getLogger(__name__)


class CharacterReferenceRuntime:
    """进程内串行队列；任务、Prompt 和进度始终以数据库为准。"""

    def __init__(self) -> None:
        self._queue: Queue[int | None] = Queue()
        self._queued: set[int] = set()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="comaic-character-reference-generation",
                daemon=True,
            )
            self._thread.start()
        # 数据库初始化先于 runtime.start；恢复 pending 不会自动恢复失败或暂停任务。
        try:
            with SessionLocal() as session:
                pending_ids = CharacterReferenceRepository(
                    session
                ).list_pending_task_ids()
        except Exception:  # noqa: BLE001 - 恢复失败不能阻止应用启动
            logger.exception("Failed to restore pending character reference tasks")
            return
        for task_id in pending_ids:
            self.submit(task_id)

    def submit(self, task_id: int) -> None:
        self.start()
        with self._lock:
            if task_id in self._queued:
                return
            self._queued.add(task_id)
            self._queue.put(task_id)

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._queue.put(None)
        thread.join(timeout=2)

    def _worker(self) -> None:
        while True:
            task_id = self._queue.get()
            if task_id is None:
                self._queue.task_done()
                return
            try:
                with SessionLocal() as session:
                    asyncio.run(
                        ReferenceImageService(
                            CharacterReferenceRepository(session)
                        ).run_task(task_id)
                    )
            except Exception:  # noqa: BLE001 - 单个任务不能终止后台队列
                logger.exception(
                    "Character reference worker crashed task_id=%s", task_id
                )
            finally:
                with self._lock:
                    self._queued.discard(task_id)
                self._queue.task_done()


character_reference_runtime = CharacterReferenceRuntime()
