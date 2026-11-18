"""Celery worker + beat configuration (TASK_MODE=celery). Start with:
    celery -A app.workers.celery_app worker -l info -Q default,render
    celery -A app.workers.celery_app beat -l info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.workers import jobs

celery = Celery("studio", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_acks_late=True,                 # re-deliver if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3 * 3600,            # hard timeout
    task_soft_time_limit=3 * 3600 - 120,
    task_default_queue="default",
    task_routes={"studio.advance_run": {"queue": "render"}},
    timezone="UTC",
    beat_schedule={
        "tick": {"task": "studio.tick", "schedule": 60.0},
        "trend-scan": {"task": "studio.scan_trends", "schedule": settings.trend_scan_interval_minutes * 60.0},
        "analytics": {"task": "studio.collect_analytics", "schedule": crontab(minute=15, hour="*/6")},
        "optimize": {"task": "studio.weekly_optimize", "schedule": crontab(minute=0, hour=3, day_of_week=1)},
    },
)


@celery.task(name="studio.tick")
def tick():
    if not jobs.automation_running():
        jobs.publish_due()  # approved uploads still go out while new production is paused
        return "paused"
    for run_id in jobs.plan_and_list():
        advance_run.delay(run_id)
    jobs.publish_due()
    return "ok"


@celery.task(name="studio.advance_run", bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
def advance_run(self, run_id: int):
    return jobs.advance_run(run_id)


@celery.task(name="studio.scan_trends")
def scan_trends(channel_id: int | None = None, force: bool = False):
    if not force and not jobs.automation_running():
        return "paused"
    return jobs.scan_trends(channel_id, force)


@celery.task(name="studio.collect_analytics")
def collect_analytics(force: bool = False):
    return jobs.collect_analytics(force)


@celery.task(name="studio.weekly_optimize")
def weekly_optimize(force: bool = False):
    return jobs.weekly_optimize(force)


@celery.task(name="studio.health")
def health():
    return "ok"
