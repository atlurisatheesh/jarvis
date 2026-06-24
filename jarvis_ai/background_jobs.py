"""Background job queue for long-running skill actions.

Runs web searches, document summarization, and similar slow tasks in a
background thread pool so the mic loop stays responsive.  Progress is
reported via an optional callback.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field


@dataclass
class BackgroundJob:
    """A single background task."""

    id: str
    name: str
    fn: callable  # () -> str
    on_progress: callable | None = None
    on_done: callable | None = None
    on_error: callable | None = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: float = 0.0
    finished_at: float = 0.0
    result: str | None = None
    error: str | None = None


class BackgroundJobs:
    """Thread-safe background job queue."""

    def __init__(self, max_workers: int = 2, timeout: float = 120.0):
        self._queue: queue.Queue[BackgroundJob] = queue.Queue()
        self._active: dict[str, BackgroundJob] = {}
        self._completed: list[BackgroundJob] = []
        self._max_workers = max_workers
        self._timeout = timeout
        self._lock = threading.Lock()
        self._running = True
        self._workers: list[threading.Thread] = []
        for _ in range(max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def submit(
        self,
        name: str,
        fn: callable,
        on_progress: callable | None = None,
        on_done: callable | None = None,
        on_error: callable | None = None,
    ) -> str:
        """Submit a job, return its ID."""
        job_id = f"job_{int(time.monotonic() * 1000)}"
        job = BackgroundJob(
            id=job_id, name=name, fn=fn,
            on_progress=on_progress, on_done=on_done, on_error=on_error,
        )
        self._queue.put(job)
        return job_id

    def get_status(self, job_id: str) -> dict | None:
        with self._lock:
            if job_id in self._active:
                j = self._active[job_id]
                return {"id": j.id, "name": j.name, "status": "running",
                        "elapsed": round(time.monotonic() - j.started_at, 1)}
            for j in self._completed[-20:]:
                if j.id == job_id:
                    return {
                        "id": j.id, "name": j.name,
                        "status": "done" if j.error is None else "error",
                        "result": j.result, "error": j.error,
                        "elapsed": round(j.finished_at - j.started_at, 1),
                    }
        return None

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def recent_completed(self) -> list[dict]:
        with self._lock:
            return [
                {"id": j.id, "name": j.name, "status": "done" if j.error is None else "error",
                 "result": j.result, "error": j.error}
                for j in self._completed[-10:]
            ]

    def shutdown(self):
        self._running = False
        for _ in self._workers:
            self._queue.put(None)  # poison pill

    def _worker_loop(self):
        while self._running:
            job = self._queue.get()
            if job is None:
                break
            with self._lock:
                self._active[job.id] = job
            job.started_at = time.monotonic()
            try:
                result = job.fn()
                if isinstance(result, str) and len(result) > 2000:
                    result = result[:2000] + "..."
                job.result = result
            except Exception as exc:
                job.error = str(exc)
            finally:
                job.finished_at = time.monotonic()
                with self._lock:
                    del self._active[job.id]
                    self._completed.append(job)
                    if len(self._completed) > 50:
                        self._completed = self._completed[-50:]
            # Notify callbacks
            if job.error and job.on_error:
                try:
                    job.on_error(job.error)
                except Exception:
                    pass
            elif job.on_done:
                try:
                    job.on_done(job.result)
                except Exception:
                    pass


# Module-level singleton
_bg: BackgroundJobs | None = None


def get_background_jobs() -> BackgroundJobs:
    global _bg
    if _bg is None:
        _bg = BackgroundJobs()
    return _bg
