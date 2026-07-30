"""
AsyncRunner: generic background-task executor for operations that take >10 s
(transcript downloads ~7 min, LLM analysis ~30 s).

Usage
-----
from utils.async_runner import submit, get_status, is_running

job_id = submit(some_long_fn, arg1, arg2, job_id="aapl_download")
status = get_status(job_id)   # {status: "running"|"done"|"error", ...}
"""
import threading
import uuid
from typing import Any, Callable


class AsyncRunner:
    """Runs callables in daemon threads and tracks their status."""

    def __init__(self) -> None:
        self._status: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable, *args: Any, job_id: str | None = None) -> str:
        """Submit a callable for background execution.

        If *job_id* is not provided a UUID4 string is generated.
        A job that is already ``running`` will NOT be re-submitted; the
        existing job_id is returned immediately so callers can poll its status.

        Returns:
            The job_id string.
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        with self._lock:
            existing = self._status.get(job_id)
            if existing and existing.get("status") == "running":
                return job_id
            self._status[job_id] = {"status": "running", "message": "started", "result": None}

        t = threading.Thread(target=self._run, args=(job_id, fn, args), daemon=True)
        t.start()
        return job_id

    def _run(self, job_id: str, fn: Callable, args: tuple) -> None:
        try:
            result = fn(*args)
            with self._lock:
                self._status[job_id] = {"status": "done", "message": "completed", "result": result}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._status[job_id] = {
                    "status": "error",
                    "message": str(exc),
                    "result": None,
                }

    def get_status(self, job_id: str) -> dict:
        """Return the current status dict for *job_id*.

        Returns ``{"status": "not_found"}`` when the job_id is unknown.
        Possible statuses: ``running`` | ``done`` | ``error`` | ``not_found``.
        """
        with self._lock:
            return dict(self._status.get(job_id, {"status": "not_found"}))

    def is_running(self, job_id: str) -> bool:
        """Convenience check — True only when the job exists and is ``running``."""
        return self.get_status(job_id).get("status") == "running"


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------
_runner = AsyncRunner()


def submit(fn: Callable, *args: Any, job_id: str | None = None) -> str:
    """Submit a background job via the module-level singleton."""
    return _runner.submit(fn, *args, job_id=job_id)


def get_status(job_id: str) -> dict:
    """Get job status from the module-level singleton."""
    return _runner.get_status(job_id)


def is_running(job_id: str) -> bool:
    """Return True if *job_id* is currently running in the module-level singleton."""
    return _runner.is_running(job_id)
