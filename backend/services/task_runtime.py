"""应用进程内的长任务运行注册表和后台心跳线程。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import logging
import threading

from backend.models.database import SessionLocal
from backend.models.time import utc_now
from backend.repositories.comic_repository import ComicRepository


logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5
ZOMBIE_SCAN_INTERVAL_SECONDS = 5
ZOMBIE_TIMEOUT_SECONDS = 15
ZOMBIE_ERROR_MESSAGE = "任务因心跳超时自动暂停，可继续生成。"


class RuntimeTaskType(str, Enum):
    """当前进程可真实执行并上报心跳的任务类型。"""

    SCRIPT_GENERATION_TASK = "script_generation_task"
    GENERATION_TASK = "generation_task"


@dataclass(frozen=True)
class RunningTaskRef:
    """进程内运行中任务引用；只保存类型和数据库主键。"""

    task_type: RuntimeTaskType
    task_id: int


class RunningTaskRegistry:
    """线程安全的运行中任务注册表，供心跳线程读取当前进程真实任务。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: set[RunningTaskRef] = set()

    def register(self, task_type: RuntimeTaskType, task_id: int) -> None:
        """任务进入 running 后注册；后台心跳线程只刷新这些任务。"""

        with self._lock:
            self._tasks.add(RunningTaskRef(task_type=task_type, task_id=task_id))
        logger.info("Registered running task type=%s id=%s", task_type.value, task_id)

    def unregister(self, task_type: RuntimeTaskType, task_id: int) -> None:
        """任务结束、暂停、失败或 generator 退出时注销。"""

        with self._lock:
            self._tasks.discard(RunningTaskRef(task_type=task_type, task_id=task_id))
        logger.info("Unregistered running task type=%s id=%s", task_type.value, task_id)

    def snapshot_ids(self) -> tuple[set[int], set[int]]:
        """返回当前注册任务 id 快照，避免后台线程持有锁访问数据库。"""

        with self._lock:
            refs = set(self._tasks)
        script_task_ids = {
            ref.task_id
            for ref in refs
            if ref.task_type == RuntimeTaskType.SCRIPT_GENERATION_TASK
        }
        generation_task_ids = {
            ref.task_id
            for ref in refs
            if ref.task_type == RuntimeTaskType.GENERATION_TASK
        }
        return script_task_ids, generation_task_ids


running_task_registry = RunningTaskRegistry()


class TaskRuntimeController:
    """管理应用级后台线程的生命周期。"""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._threads = [
            threading.Thread(
                target=self._heartbeat_loop,
                name="comaic-task-heartbeat",
                daemon=True,
            ),
            threading.Thread(
                target=self._zombie_scan_loop,
                name="comaic-task-zombie-scan",
                daemon=True,
            ),
        ]

    def start(self) -> None:
        """应用启动时调用，启动心跳线程和僵尸扫描线程。"""

        for thread in self._threads:
            thread.start()
        logger.info("Task runtime threads started")

    def stop(self) -> None:
        """应用关闭时通知后台线程停止，并短暂等待其退出。"""

        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        logger.info("Task runtime threads stopped")

    def _heartbeat_loop(self) -> None:
        """每 5 秒刷新当前进程真实运行中的任务心跳。"""

        while not self._stop_event.is_set():
            self._update_registered_task_heartbeats()
            if self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
                break

    def _zombie_scan_loop(self) -> None:
        """定期把心跳超时的 running 任务自动暂停。"""

        while not self._stop_event.is_set():
            self._suspend_zombie_tasks()
            if self._stop_event.wait(ZOMBIE_SCAN_INTERVAL_SECONDS):
                break

    @staticmethod
    def _update_registered_task_heartbeats() -> None:
        script_task_ids, generation_task_ids = running_task_registry.snapshot_ids()
        if not script_task_ids and not generation_task_ids:
            return

        try:
            with SessionLocal() as session:
                repo = ComicRepository(session)
                script_count, generation_count = repo.update_running_task_heartbeats(
                    script_task_ids=script_task_ids,
                    generation_task_ids=generation_task_ids,
                    heartbeat_at=utc_now(),
                )
                logger.debug(
                    "Task heartbeat updated script=%s generation=%s",
                    script_count,
                    generation_count,
                )
        except Exception:  # noqa: BLE001 - 后台线程不能因单轮数据库错误退出
            logger.exception("Failed to update task heartbeats")

    @staticmethod
    def _suspend_zombie_tasks() -> None:
        stale_before = utc_now() - timedelta(seconds=ZOMBIE_TIMEOUT_SECONDS)
        try:
            with SessionLocal() as session:
                repo = ComicRepository(session)
                script_count, generation_count = repo.suspend_stale_running_tasks(
                    stale_before=stale_before,
                    error_message=ZOMBIE_ERROR_MESSAGE,
                )
                if script_count or generation_count:
                    logger.warning(
                        "Suspended zombie tasks script=%s generation=%s",
                        script_count,
                        generation_count,
                    )
        except Exception:  # noqa: BLE001 - 后台线程不能因单轮数据库错误退出
            logger.exception("Failed to suspend zombie tasks")


def start_task_runtime_threads() -> TaskRuntimeController:
    """创建并启动全局任务运行时线程，由 FastAPI lifespan 持有控制器。"""

    controller = TaskRuntimeController()
    controller.start()
    return controller
