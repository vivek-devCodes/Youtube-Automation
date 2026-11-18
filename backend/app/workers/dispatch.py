"""Dispatch jobs either to Celery or to an in-process background thread (TASK_MODE=inline)."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

from app.core.config import settings
from app.workers import jobs

log = logging.getLogger(__name__)


class InlineRunner:
    """Single worker thread (rendering is CPU-heavy) + a 60s scheduler loop. Development/single-box use."""

    def __init__(self):
        self.q: "queue.Queue[tuple[Callable, tuple, dict]]" = queue.Queue()
        self.pending: set[Any] = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.last_beat: float = 0.0
        self.current: str | None = None

    def start(self):
        if self.threads:
            return
        for target in (self._worker, self._beat):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self.threads.append(t)
        log.info("inline job runner started")

    def submit(self, fn: Callable, *args, key: Any = None, **kwargs) -> bool:
        key = key or (fn.__name__, args)
        with self.lock:
            if key in self.pending:
                return False  # duplicate prevention
            self.pending.add(key)
        self.q.put((fn, args, {**kwargs, "_key": key}))
        return True

    def _worker(self):
        while not self.stop.is_set():
            try:
                fn, args, kwargs = self.q.get(timeout=1)
            except queue.Empty:
                continue
            key = kwargs.pop("_key")
            self.current = f"{fn.__name__}{args}"
            try:
                fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                log.exception("inline job %s failed", fn.__name__)
            finally:
                self.current = None
                with self.lock:
                    self.pending.discard(key)

    def _beat(self):
        time.sleep(5)
        while not self.stop.is_set():
            self.last_beat = time.time()
            try:
                if jobs.automation_running():
                    self.submit(jobs.scan_trends, key="scan")
                    for run_id in jobs.plan_and_list():
                        self.submit(jobs.advance_run, run_id, key=("run", run_id))
                    self.submit(jobs.collect_analytics, key="analytics")
                    self.submit(jobs.weekly_optimize, key="optimize")
                self.submit(jobs.publish_due, key="publish")
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick failed")
            self.stop.wait(settings.pipeline_tick_seconds)


runner = InlineRunner()


def enqueue_run(run_id: int) -> None:
    if settings.task_mode == "celery":
        from app.workers.celery_app import advance_run

        advance_run.delay(run_id)
    else:
        runner.submit(jobs.advance_run, run_id, key=("run", run_id))


def enqueue_scan(channel_id: int | None) -> None:
    if settings.task_mode == "celery":
        from app.workers.celery_app import scan_trends

        scan_trends.delay(channel_id, True)
    else:
        runner.submit(jobs.scan_trends, channel_id, True, key=("scan", channel_id))


def enqueue(fn_name: str, *args) -> None:
    if settings.task_mode == "celery":
        from app.workers import celery_app

        getattr(celery_app, fn_name).delay(*args)
    else:
        runner.submit(getattr(jobs, fn_name), *args)


def worker_health() -> dict:
    if settings.task_mode == "celery":
        try:
            from app.workers.celery_app import celery

            replies = celery.control.ping(timeout=2)
            return {"mode": "celery", "workers": len(replies), "ok": bool(replies)}
        except Exception as e:  # noqa: BLE001
            return {"mode": "celery", "ok": False, "error": str(e)}
    alive = all(t.is_alive() for t in runner.threads) and bool(runner.threads)
    return {"mode": "inline", "ok": alive, "queue": runner.q.qsize(), "current": runner.current,
            "last_beat_s_ago": round(time.time() - runner.last_beat, 1) if runner.last_beat else None}
