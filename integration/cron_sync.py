"""CronSync — 定时同步系统"""
from __future__ import annotations
import logging, threading, time
from typing import Callable
logger = logging.getLogger(__name__)

class CronJob:
    def __init__(self, name: str, func: Callable, interval: float) -> None:
        self.name, self.func, self.interval = name, func, interval
        self.run_count = 0; self._last_run = 0.0

    def should_run(self) -> bool:
        return (time.time() - self._last_run) >= self.interval

    def run(self) -> None:
        try:
            self.func()
            self.run_count += 1
            self._last_run = time.time()
        except Exception as e:
            logger.error(f"[CronSync] Job {self.name} 失败: {e}")

class CronSync:
    """定时同步任务管理器。"""
    def __init__(self) -> None:
        self._jobs: list[CronJob] = []
        self._running = False
        self._thread: threading.Thread | None = None

    def register(self, name: str, func: Callable, interval: float = 300) -> None:
        self._jobs.append(CronJob(name, func, interval))
        logger.info(f"[CronSync] 注册定时任务: {name} (每{interval}s)")

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            for job in self._jobs:
                if job.should_run():
                    job.run()
            time.sleep(10)

    def run_now(self, name: str) -> bool:
        for job in self._jobs:
            if job.name == name:
                job.run(); return True
        return False

    def stats(self) -> dict:
        return {"jobs": [{"name": j.name, "runs": j.run_count} for j in self._jobs]}
