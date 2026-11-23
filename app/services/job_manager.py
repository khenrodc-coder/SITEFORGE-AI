"""Runs one website generation at a time in a background thread.

Generating with a local model can take minutes, so the browser starts a job
and then asks for its progress. Jobs live in memory only; the finished website
is saved to MySQL in Phase 9. With several server processes each would have
its own jobs, so production must run a single worker process (Phase 12).
"""
import logging
import threading
import time
import uuid

from app.services.ollama_service import OllamaError

log = logging.getLogger(__name__)


class JobBusyError(Exception):
    """Another generation is still running."""


class JobCancelled(Exception):
    """Raised inside a job when the user cancelled it."""


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.status = "running"          # running, cancelling, done, failed, cancelled
        self.progress = {"done": 0, "total": 1, "label": "Starting"}
        self.result = None
        self.error = None
        self.created = time.time()
        self.finished = None
        self.thread = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def set_progress(self, done, total, label):
        with self._lock:
            self.progress = {"done": done, "total": total, "label": label}

    def request_cancel(self):
        with self._lock:
            if self.status != "running":
                return False
            self.status = "cancelling"
        self._cancel.set()
        return True

    def check_cancelled(self):
        if self._cancel.is_set():
            raise JobCancelled()

    def _finish(self, status, result=None, error=None):
        with self._lock:
            self.status = status
            self.result = result
            self.error = error
            self.finished = time.time()

    def is_active(self):
        return self.thread is not None and self.thread.is_alive()

    def snapshot(self):
        with self._lock:
            return {
                "job_id": self.id,
                "status": self.status,
                "progress": dict(self.progress),
                "result": self.result,
                "error": self.error,
            }


class JobManager:
    def __init__(self, max_age_seconds=3600):
        self.max_age = max_age_seconds
        self._jobs = {}
        self._lock = threading.Lock()

    def _purge(self):
        now = time.time()
        old = [job_id for job_id, job in self._jobs.items()
               if job.finished and now - job.finished > self.max_age]
        for job_id in old:
            del self._jobs[job_id]

    def start(self, target):
        """Start `target(job)` in a thread. Raises JobBusyError if one is already running."""
        with self._lock:
            self._purge()
            if any(job.is_active() for job in self._jobs.values()):
                raise JobBusyError()
            job = Job()
            job.thread = threading.Thread(target=self._run, args=(job, target), daemon=True)
            self._jobs[job.id] = job
            job.thread.start()
            return job

    def _run(self, job, target):
        try:
            result = target(job)
            if job._cancel.is_set():
                job._finish("cancelled")
            else:
                job._finish("done", result=result)
        except JobCancelled:
            job._finish("cancelled")
        except OllamaError as exc:
            job._finish("failed", error={"code": exc.code, "message": exc.message})
        except Exception:                     # never leak internals to the browser
            log.exception("Unexpected error in generation job %s", job.id)
            job._finish("failed", error={
                "code": "unexpected_error",
                "message": "Something went wrong while generating the website. Please try again.",
            })

    def get(self, job_id):
        if not isinstance(job_id, str):
            return None
        with self._lock:
            return self._jobs.get(job_id)
