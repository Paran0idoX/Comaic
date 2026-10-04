"""参考图 Prompt 预览的专用线程池，不占用图片生成队列。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Callable, TypeVar
from backend.models.enums import CompilationStatus

ResultT = TypeVar("ResultT")
REFERENCE_PROMPT_WORKERS = 5


class ReferencePromptRuntime:
    """限制进程内并发预览；调用方须在线程内创建并关闭数据库会话。"""

    def __init__(self):
        self._lock = Lock()
        self._executor: ThreadPoolExecutor | None = None

    async def run(self, operation: Callable[[], ResultT]) -> ResultT:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=REFERENCE_PROMPT_WORKERS,
                    thread_name_prefix="comaic-reference-prompt")
            future = self._executor.submit(operation)
        return await asyncio.wrap_future(future)

    async def stream(self, operations: list[Callable[[], ResultT]]):
        """一次接收整批；线程实际开始时发状态，结果按完成顺序逐项返回。"""
        loop = asyncio.get_running_loop()
        events = asyncio.Queue()

        async def execute(index, operation):
            def prepare():
                loop.call_soon_threadsafe(events.put_nowait, (index, CompilationStatus.RUNNING, None))
                return operation()
            try:
                result = await self.run(prepare)
                await events.put((index, CompilationStatus.SUCCEEDED, result))
            except Exception as exc:
                await events.put((index, CompilationStatus.FAILED, exc))

        tasks = [asyncio.create_task(execute(index, operation)) for index, operation in enumerate(operations)]
        completed = 0
        try:
            while completed < len(tasks):
                event = await events.get()
                if event[1] in {CompilationStatus.SUCCEEDED, CompilationStatus.FAILED}:
                    completed += 1
                yield event
        finally:
            # 断开预览只取消排队项；正在执行的模型调用会结束并保存其有效摘要。
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        """关闭时取消尚未开始的预览，已开始的调用自行释放会话。"""
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


reference_prompt_runtime = ReferencePromptRuntime()
