"""Tiny in-memory job registry shared by the ZIM and map managers."""
import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()
# One heavy job per kind at a time: a Pi shouldn't run parallel multi-GB transfers.
_gates = {"zim": threading.Semaphore(1), "map": threading.Semaphore(1)}


class Job:
    def __init__(self, kind, title):
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.title = title
        self.state = "queued"   # queued | running | done | error | cancelled
        self.done = 0
        self.total = 0
        self.message = ""
        self.cancel = threading.Event()
        self.proc = None        # subprocess handle, if any (so cancel can kill it)
        self.started = time.time()
        with _lock:
            _jobs[self.id] = self

    def public(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state,
                "done": self.done, "total": self.total, "message": self.message}


def start(kind, title, fn):
    """Run fn(job) in a background thread once the gate for `kind` is free."""
    job = Job(kind, title)

    def run():
        with _gates[kind]:
            if job.cancel.is_set():
                job.state = "cancelled"
                return
            job.state = "running"
            try:
                fn(job)
                if job.state == "running":
                    job.state = "cancelled" if job.cancel.is_set() else "done"
            except Exception as e:  # surface any failure in the UI
                job.state = "cancelled" if job.cancel.is_set() else "error"
                job.message = job.message or str(e)

    threading.Thread(target=run, daemon=True).start()
    return job


def cancel(job_id):
    job = _jobs.get(job_id)
    if not job:
        return False
    job.cancel.set()
    if job.proc and job.proc.poll() is None:
        job.proc.terminate()
    return True


def snapshot(keep_finished=20):
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.started, reverse=True)
        # forget old finished jobs so the list doesn't grow forever
        for j in jobs[keep_finished:]:
            if j.state in ("done", "error", "cancelled"):
                _jobs.pop(j.id, None)
        return [j.public() for j in jobs[:keep_finished]]
