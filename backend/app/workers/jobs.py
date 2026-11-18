"""Background job bodies, shared by Celery tasks and the inline (no-Redis) scheduler."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents import analytics, publishing, trends
from app.database.session import SessionLocal
from app.models import Channel, Trend
from app.services.usage import get_automation
from app.workflows import pipeline

log = logging.getLogger(__name__)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def scan_trends(channel_id: int | None = None, force: bool = False) -> dict:
    with SessionLocal() as db:
        auto = get_automation(db)
        now = datetime.now(timezone.utc)
        if not force and auto and auto.last_trend_scan_at and \
                _aware(auto.last_trend_scan_at) + timedelta(minutes=auto.trend_scan_interval_minutes) > now:
            return {"skipped": "not due"}
        q = select(Channel).where(Channel.status == "connected")
        q = q.where(Channel.id == channel_id) if channel_id else q.where(Channel.automation_enabled.is_(True))
        results = {}
        for ch in db.scalars(q).all():
            try:
                results[ch.id] = trends.discover(db, ch)
                # LLM idea suggestions only for the top few new trends (keeps paid usage small).
                top = db.scalars(select(Trend).where(Trend.channel_id == ch.id, Trend.status == "new")
                                 .order_by(Trend.score.desc()).limit(5)).all()
                for t in top:
                    if not t.suggested_ideas:
                        try:
                            trends.suggest_ideas(db, t, ch)
                        except Exception as e:  # noqa: BLE001
                            log.warning("idea suggestion failed for trend %s: %s", t.id, e)
                            db.rollback()
                            break
            except Exception as e:  # noqa: BLE001
                db.rollback()
                log.exception("trend scan failed for channel %s", ch.id)
                results[ch.id] = {"error": str(e)}
        if auto and not channel_id:
            auto.last_trend_scan_at = now
            db.commit()
        return results


def advance_run(run_id: int) -> str:
    with SessionLocal() as db:
        run = pipeline.advance(db, run_id)
        return run.status if run else "missing"


def plan_and_list() -> list[int]:
    """Create new runs within capacity, then return run ids ready to advance."""
    with SessionLocal() as db:
        try:
            pipeline.plan(db)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("planner failed")
        return pipeline.runnable_ids(db)


def publish_due() -> int:
    with SessionLocal() as db:
        return publishing.run_due_jobs(db)


def collect_analytics(force: bool = False) -> dict:
    with SessionLocal() as db:
        auto = get_automation(db)
        now = datetime.now(timezone.utc)
        if not force and auto and auto.last_analytics_at and \
                _aware(auto.last_analytics_at) + timedelta(hours=auto.analytics_interval_hours) > now:
            return {"skipped": "not due"}
        out = {ch.id: analytics.collect_channel(db, ch) for ch in db.scalars(select(Channel).where(Channel.status == "connected")).all()}
        if auto:
            auto.last_analytics_at = now
            db.commit()
        return out


def weekly_optimize(force: bool = False) -> dict:
    with SessionLocal() as db:
        auto = get_automation(db)
        if not force and auto and auto.last_optimization_at and \
                _aware(auto.last_optimization_at) + timedelta(days=7) > datetime.now(timezone.utc):
            return {"skipped": "not due"}
        return analytics.optimize(db)


def automation_running() -> bool:
    with SessionLocal() as db:
        auto = get_automation(db)
        return bool(auto and auto.is_running)
