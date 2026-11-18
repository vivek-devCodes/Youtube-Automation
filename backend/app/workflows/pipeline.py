"""Persisted, resumable production workflow.

research → script → [script_review] → originality → seo → voice → visuals → render → qa → approval → publish

Each step's status/output lives in workflow_runs.steps. `advance()` skips completed steps, so a crash,
retry or worker restart resumes exactly where it stopped without regenerating finished assets."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents import compliance, content, media, publishing, qa
from app.core.errors import BudgetExceeded, ComplianceFailure, QualityFailure, StudioError
from app.models import (ApprovalRequest, Channel, ContentIdea, PublishingJob, Script, Trend, Video, WorkflowRun)
from app.services import usage
from app.services.audit import notify

log = logging.getLogger(__name__)
STEPS = ["research", "script", "script_review", "originality", "seo", "voice", "visuals", "render", "qa", "approval", "publish"]
MAX_ATTEMPTS = 4
LOCK_MINUTES = 45


class Wait(Exception):
    """Step cannot complete yet (human approval / deferred upload)."""

    def __init__(self, status: str, until: datetime | None = None, note: str = ""):
        super().__init__(note)
        self.status, self.until, self.note = status, until, note


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def start_run(db: Session, idea: ContentIdea, *, review_script: bool = False) -> WorkflowRun:
    channel = db.get(Channel, idea.channel_id)
    w, h = (1080, 1920) if idea.format == "short" else (1920, 1080)
    video = Video(channel_id=channel.id, idea_id=idea.id, format=idea.format, width=w, height=h, status="in_production")
    db.add(video)
    db.flush()
    run = WorkflowRun(channel_id=channel.id, idea_id=idea.id, video_id=video.id, status="pending",
                      steps={s: {"status": "pending"} for s in STEPS}, review_script=review_script)
    idea.status = "in_production"
    db.add(run)
    db.commit()
    return run


def _set_step(run: WorkflowRun, name: str, **fields: Any) -> None:
    steps = dict(run.steps or {})
    steps[name] = {**steps.get(name, {}), **fields}
    run.steps = steps  # reassign so SQLAlchemy detects the JSON change


# ----------------------------------------------------------------------------- steps
def _ctx(db: Session, run: WorkflowRun):
    idea = db.get(ContentIdea, run.idea_id)
    channel = db.get(Channel, run.channel_id)
    video = db.get(Video, run.video_id)
    script = db.get(Script, run.script_id) if run.script_id else None
    return idea, channel, video, script


def step_research(db, run):
    idea, channel, _, _ = _ctx(db, run)
    return content.research(db, idea, channel, run.id)


def step_script(db, run):
    idea, channel, video, _ = _ctx(db, run)
    script = content.write_script(db, idea, channel, run.id)
    run.script_id = script.id
    video.script_id = script.id
    db.commit()
    return {"script_id": script.id, "version": script.version, "scenes": len(script.scenes),
            "estimated_seconds": script.estimated_duration_seconds, "provider": script.llm_provider}


def step_script_review(db, run):
    if not run.review_script:
        return {"skipped": True}
    _, channel, _, script = _ctx(db, run)
    req = db.scalar(select(ApprovalRequest).where(ApprovalRequest.kind == "script", ApprovalRequest.target_id == script.id))
    if req is None:
        db.add(ApprovalRequest(channel_id=channel.id, kind="script", target_type="script", target_id=script.id,
                               summary=f"Review script: {script.title}"))
        notify(db, "Script ready for review", script.title, link=f"/studio?run={run.id}")
        db.commit()
        raise Wait("waiting_approval", note="script review")
    if req.status == "pending":
        raise Wait("waiting_approval", note="script review")
    if req.status == "rejected":
        raise ComplianceFailure(f"Script rejected by reviewer: {req.note}")
    script.status = "approved"
    return {"approved": True}


def step_originality(db, run):
    idea, channel, _, script = _ctx(db, run)
    report = compliance.check_script(db, script, idea, channel)
    if report["passed"]:
        return {"originality_score": report["originality_score"], "checks": len(report["checks"])}
    rewrites = (run.steps.get("originality") or {}).get("rewrites", 0)
    failed = [c["name"] for c in report["checks"] if c["critical"] and not c["passed"]]
    if rewrites < 2 and set(failed) <= {"reference_similarity", "source_verbatim_copy", "not_repetitive"}:
        _set_step(run, "originality", rewrites=rewrites + 1, last_failure=failed)
        _set_step(run, "script", status="pending")
        _set_step(run, "script_review", status="pending")
        db.commit()
        raise Wait("rewrite", note=f"originality failed ({failed}); rewriting script")
    raise ComplianceFailure(f"Originality/compliance failed: {failed}")


def step_seo(db, run):
    idea, channel, video, script = _ctx(db, run)
    meta = content.generate_metadata(db, video, script, idea, channel, run.id)
    return {"title": meta.title, "tags": len(meta.tags), "hashtags": meta.hashtags}


def step_voice(db, run):
    _, channel, _, script = _ctx(db, run)
    return media.generate_voice(db, script, channel, run.id)


def step_visuals(db, run):
    _, channel, video, script = _ctx(db, run)
    return media.generate_visuals(db, script, video, channel, run.id)


def step_render(db, run):
    _, channel, video, script = _ctx(db, run)
    video.status = "rendering"
    db.commit()
    return media.render_video(db, script, video, channel)


def step_qa(db, run):
    _, channel, video, _ = _ctx(db, run)
    report = qa.run_qa(db, video, channel, run.id)
    if not report["passed"]:
        raise QualityFailure(f"QA score {report['score']} (min {report['min_score']}); critical: {report['critical_failures']}")
    return {"score": report["score"]}


def step_approval(db, run):
    _, channel, video, _ = _ctx(db, run)
    job = db.scalar(select(PublishingJob).where(PublishingJob.video_id == video.id))
    if job:
        return {"job_id": job.id, "privacy": job.privacy_status}
    if publishing.unattended_allowed(db, channel):
        slot = publishing.next_slot(db, channel)
        job = publishing.create_job(db, video, channel, privacy="public", publish_at=slot, approved_by=None)
        return {"job_id": job.id, "unattended": True, "publish_at": slot.isoformat()}
    last = db.scalar(select(ApprovalRequest).where(ApprovalRequest.target_type == "video", ApprovalRequest.target_id == video.id,
                                                   ApprovalRequest.kind == "video_publish").order_by(ApprovalRequest.id.desc()).limit(1))
    if last and last.status == "rejected":
        video.status = "rejected"
        db.commit()
        raise ComplianceFailure(f"Publishing rejected by reviewer: {last.note}")
    publishing.request_approval(db, video, channel)
    raise Wait("waiting_approval", note="publish approval")


def step_publish(db, run):
    _, _, video, _ = _ctx(db, run)
    job = db.scalar(select(PublishingJob).where(PublishingJob.video_id == video.id))
    if not job:
        _set_step(run, "approval", status="pending")
        raise Wait("waiting_approval", note="no publishing job")
    if job.status == "queued" and (_aware(job.run_after) or now()) <= now():
        publishing.execute_job(db, job)
    if job.status == "succeeded":
        return {"youtube_video_id": job.youtube_video_id, "status": video.status}
    if job.status == "failed":
        raise StudioError(f"Upload failed: {job.last_error}", retryable=False)
    raise Wait("running", until=_aware(job.run_after) or now() + timedelta(minutes=10), note=job.last_error or "upload pending")


HANDLERS: dict[str, Callable[[Session, WorkflowRun], dict]] = {
    "research": step_research, "script": step_script, "script_review": step_script_review, "originality": step_originality,
    "seo": step_seo, "voice": step_voice, "visuals": step_visuals, "render": step_render, "qa": step_qa,
    "approval": step_approval, "publish": step_publish,
}


# ----------------------------------------------------------------------------- engine
def _acquire(db: Session, run_id: int) -> bool:
    """Row-level lease so two workers never process the same run concurrently."""
    t = now()
    res = db.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, (WorkflowRun.locked_until.is_(None)) | (WorkflowRun.locked_until < t))
        .values(locked_until=t + timedelta(minutes=LOCK_MINUTES))
    )
    db.commit()
    return res.rowcount == 1


def _release(db: Session, run: WorkflowRun) -> None:
    run.locked_until = None
    db.commit()


def advance(db: Session, run_id: int) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None or run.status in ("succeeded", "failed", "cancelled"):
        return run
    if not _acquire(db, run_id):
        return run
    db.refresh(run)
    try:
        run.status = "running"
        db.commit()
        i = 0
        while i < len(STEPS):
            name = STEPS[i]
            if run.cancel_requested:
                run.status = "cancelled"
                video = db.get(Video, run.video_id)
                if video and video.status not in ("published", "scheduled", "uploaded"):
                    video.status = "cancelled"
                break
            if (run.steps.get(name) or {}).get("status") == "done":
                i += 1
                continue
            run.current_step = name
            _set_step(run, name, status="running", started_at=now().isoformat())
            db.commit()
            try:
                output = HANDLERS[name](db, run)
            except Wait as w:
                if w.status == "rewrite":
                    i = STEPS.index("script")
                    continue
                _set_step(run, name, status="waiting", note=w.note)
                run.status = w.status
                run.next_attempt_at = w.until
                db.commit()
                return run
            _set_step(run, name, status="done", finished_at=now().isoformat(), output=output, error=None)
            run.attempts = 0
            run.last_error = None
            db.commit()
            i += 1
        else:
            run.status = "succeeded"
            run.current_step = None
            idea = db.get(ContentIdea, run.idea_id)
            if idea:
                idea.status = "done"
        db.commit()
        return run
    except BudgetExceeded as e:
        db.rollback()
        _fail_step(db, run, e, status="paused")
        auto = usage.get_automation(db)
        if auto:
            auto.paused_reason = f"Monthly AI budget reached: {e}"
        notify(db, "Paid generation paused: budget limit", str(e), level="critical", link="/settings")
        db.commit()
        return run
    except Exception as e:  # noqa: BLE001
        db.rollback()
        retryable = getattr(e, "retryable", not isinstance(e, (ComplianceFailure, QualityFailure)))
        run.attempts += 1
        if retryable and run.attempts < MAX_ATTEMPTS:
            delay = timedelta(minutes=2 ** run.attempts)
            _fail_step(db, run, e, status="retry_scheduled", until=now() + delay)
        else:
            _fail_step(db, run, e, status="failed")
            video = db.get(Video, run.video_id)
            if video and video.status not in ("qa_failed",):
                video.status = "failed"
            notify(db, "Production run failed", f"Run {run.id} at step '{run.current_step}': {e}", level="critical",
                   link=f"/studio?run={run.id}")
            db.commit()
        return run
    finally:
        _release(db, run)


def _fail_step(db: Session, run: WorkflowRun, e: Exception, *, status: str, until: datetime | None = None) -> None:
    db.refresh(run)
    name = run.current_step or "unknown"
    log.warning("run %s step %s failed: %s", run.id, name, e, extra={"run_id": run.id, "step": name})
    _set_step(run, name, status="error", error=str(e)[:2000], trace=traceback.format_exc()[-2000:], failed_at=now().isoformat())
    run.status = status
    run.last_error = f"{name}: {e}"[:2000]
    run.next_attempt_at = until
    db.commit()


def resume(db: Session, run: WorkflowRun, from_step: str | None = None) -> None:
    """Manual retry: optionally reset a step (and everything after it), then mark runnable."""
    if from_step:
        reset = False
        for s in STEPS:
            reset = reset or s == from_step
            if reset:
                _set_step(run, s, status="pending")
    else:
        for s, st in (run.steps or {}).items():
            if st.get("status") in ("error", "running", "waiting"):
                _set_step(run, s, status="pending")
    run.status, run.attempts, run.next_attempt_at, run.cancel_requested = "pending", 0, None, False
    run.locked_until = None
    db.commit()


def runnable_ids(db: Session) -> list[int]:
    t = now()
    rows = db.scalars(select(WorkflowRun).where(WorkflowRun.status.in_(("pending", "running", "retry_scheduled")))).all()
    out = []
    for r in rows:
        if r.locked_until and _aware(r.locked_until) > t:
            continue
        if r.next_attempt_at and _aware(r.next_attempt_at) > t:
            continue
        out.append(r.id)
    return out


# ----------------------------------------------------------------------------- planner
def plan(db: Session) -> list[int]:
    """Create new production runs up to each automated channel's publishing capacity."""
    auto = usage.get_automation(db)
    if not auto or not auto.is_running or auto.paused_reason:
        return []
    created = []
    day_ago, week_ago = now() - timedelta(days=1), now() - timedelta(days=7)
    for channel in db.scalars(select(Channel).where(Channel.automation_enabled.is_(True), Channel.status == "connected")).all():
        cs = channel.settings
        active = select(WorkflowRun).join(Video, Video.id == WorkflowRun.video_id).where(
            WorkflowRun.channel_id == channel.id, WorkflowRun.status.notin_(("failed", "cancelled")))
        shorts = len(db.scalars(active.where(Video.format == "short", WorkflowRun.created_at >= day_ago)).all())
        longs = len(db.scalars(active.where(Video.format == "long", WorkflowRun.created_at >= week_ago)).all())
        for fmt, have, cap in (("short", shorts, cs.shorts_per_day), ("long", longs, cs.long_per_week)):
            if have >= cap:
                continue
            trend = _pick_topic(db, channel, auto)
            if not trend:
                break
            idea = idea_from_trend(db, trend, channel, fmt)
            created.append(start_run(db, idea).id)
    return created


def _pick_topic(db: Session, channel: Channel, auto) -> Trend | None:
    q = select(Trend).where(Trend.channel_id == channel.id).order_by(Trend.score.desc())
    t = db.scalar(q.where(Trend.status == "approved").limit(1))
    if t is None and auto.auto_select_topics:
        t = db.scalar(q.where(Trend.status == "new", Trend.score >= auto.min_trend_score).limit(1))
    return t


def idea_from_trend(db: Session, trend: Trend, channel: Channel, fmt: str, title: str | None = None) -> ContentIdea:
    from app.services.catalog import LONG_RANGES

    cs = channel.settings
    if fmt == "short":
        target = cs.short_duration_seconds
    else:
        lo, hi = LONG_RANGES.get(cs.long_duration_range, (300, 480))
        target = (lo + hi) // 2
    if not title:
        title = (trend.suggested_ideas or [None])[0] or trend.topic
    idea = ContentIdea(channel_id=channel.id, trend_id=trend.id, title=title[:300], format=fmt, target_duration_seconds=target,
                       language=cs.language, angle=(trend.score_breakdown or {}).get("why_it_works", ""), status="approved")
    trend.status = "used"
    db.add(idea)
    db.commit()
    return idea
