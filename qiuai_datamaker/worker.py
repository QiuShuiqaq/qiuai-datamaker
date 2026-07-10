from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class WorkerThread(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, progress=self.progress.emit, **self._kwargs)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
