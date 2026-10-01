"""单 worker 串行执行 GPU 一致性评估，避免多个模型进程争抢显存。"""

from __future__ import annotations

import logging
from queue import Queue
import threading

from backend.models.database import SessionLocal
from backend.repositories.consistency_evaluation_repository import (
    ConsistencyEvaluationRepository,
)
from backend.services.consistency_evaluation_service import ConsistencyEvaluationService


logger = logging.getLogger(__name__)


class ConsistencyEvaluationRuntime:
    """进程内串行队列；数据库任务状态仍是恢复与审计的唯一事实来源。"""

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
                name="comaic-consistency-evaluation",
                daemon=True,
            )
            self._thread.start()

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
                    service = ConsistencyEvaluationService(
                        ConsistencyEvaluationRepository(session)
                    )
                    service.run_task(task_id)
            except Exception:  # noqa: BLE001 - 单个任务不能终止队列线程
                logger.exception("Consistency evaluation worker crashed task_id=%s", task_id)
            finally:
                with self._lock:
                    self._queued.discard(task_id)
                self._queue.task_done()


consistency_evaluation_runtime = ConsistencyEvaluationRuntime()
