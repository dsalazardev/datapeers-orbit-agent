"""Background scheduling adapter based on FastAPI BackgroundTasks (design D4).

The job is handed to the framework and executed after the HTTP response is
emitted; the use case never awaits it (ORB-FR-023, partial coverage: the
parallel execution framework is ORB-TK-03).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import BackgroundTasks


class BackgroundTasksScheduler:
    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._background_tasks = background_tasks

    def schedule(self, job: Callable[[], Awaitable[None]]) -> None:
        self._background_tasks.add_task(job)
