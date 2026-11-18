from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import publishing
from app.api.deps import get_or_404, require, to_dict
from app.database.session import get_db
from app.models import ApprovalRequest, Channel, PublishingHistory, PublishingJob, User, Video, VideoMetadata, WorkflowRun
from app.services.audit import audit
from app.workers.dispatch import enqueue, enqueue_run

router = APIRouter(tags=["publishing"])


class UploadBody(BaseModel):
    video_id: int
    privacy: str = Field("private", pattern="^(private|unlisted|public)$")


class ScheduleBody(BaseModel):
    video_id: int
    publish_at: datetime | None = None  # None => next free slot from channel settings


def _approve_video(db: Session, user: User, video: Video, privacy: str, publish_at: datetime | None) -> PublishingJob:
    if not video.qa_report or not video.qa_report.get("passed"):
        raise HTTPException(400, "Only videos that passed QA can be published")
    channel = db.get(Channel, video.channel_id)
    if channel.status != "connected":
        raise HTTPException(400, "Channel is disconnected — reconnect it first")
    if publish_at is not None:
        publish_at = publish_at if publish_at.tzinfo else publish_at.replace(tzinfo=timezone.utc)
        if publish_at < datetime.now(timezone.utc) + timedelta(minutes=15):
            raise HTTPException(400, "Scheduled time must be at least 15 minutes in the future")
    for req in db.scalars(select(ApprovalRequest).where(ApprovalRequest.target_type == "video", ApprovalRequest.target_id == video.id,
                                                        ApprovalRequest.status == "pending")).all():
        req.status, req.decided_by, req.decided_at = "approved", user.id, datetime.now(timezone.utc)
        req.note = f"privacy={privacy} publish_at={publish_at}"
    job = publishing.create_job(db, video, channel, privacy=privacy, publish_at=publish_at, approved_by=user.id)
    audit(db, "video.approve_publish", user_id=user.id, entity_type="video", entity_id=video.id,
          detail={"privacy": privacy, "publish_at": publish_at.isoformat() if publish_at else None, "job": job.id})
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.video_id == video.id))
    if run and run.status in ("waiting_approval", "paused", "failed"):
        run.status = "pending"
    db.commit()
    if run:
        enqueue_run(run.id)
    else:
        enqueue("publish_due")
    return job


@router.post("/publishing/upload")
def upload(body: UploadBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    """Approve and upload now with the chosen privacy. Defaults to private."""
    video = get_or_404(db, Video, body.video_id)
    return to_dict(_approve_video(db, user, video, body.privacy, None))


@router.post("/publishing/schedule")
def schedule(body: ScheduleBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    """Approve for public release at a scheduled time (uploaded private with publishAt)."""
    video = get_or_404(db, Video, body.video_id)
    when = body.publish_at or publishing.next_slot(db, db.get(Channel, video.channel_id))
    return to_dict(_approve_video(db, user, video, "public", when))


@router.get("/publishing/history")
def history(video_id: int | None = None, limit: int = 200, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = select(PublishingHistory).order_by(PublishingHistory.id.desc()).limit(min(limit, 1000))
    if video_id:
        q = q.where(PublishingHistory.video_id == video_id)
    return [to_dict(h) for h in db.scalars(q).all()]


@router.get("/publishing/jobs")
def jobs(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    out = []
    for j in db.scalars(select(PublishingJob).order_by(PublishingJob.id.desc()).limit(300)).all():
        d = to_dict(j)
        meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == j.video_id))
        d["title"] = meta.title if meta else f"Video {j.video_id}"
        out.append(d)
    return out


@router.post("/publishing/jobs/{job_id}/retry")
def retry_job(job_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    job = get_or_404(db, PublishingJob, job_id)
    if job.status == "succeeded":
        raise HTTPException(400, "already uploaded")
    job.status, job.run_after, job.attempts = "queued", datetime.now(timezone.utc), 0
    db.commit()
    enqueue("publish_due")
    return to_dict(job)


@router.post("/publishing/jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    job = get_or_404(db, PublishingJob, job_id)
    if job.status in ("succeeded", "uploading"):
        raise HTTPException(400, f"cannot cancel a job that is {job.status}")
    job.status = "cancelled"
    db.commit()
    return to_dict(job)


# ------------------------------------------------------------------ approvals
@router.get("/approvals")
def approvals(status: str = "pending", user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    out = []
    for a in db.scalars(select(ApprovalRequest).where(ApprovalRequest.status == status).order_by(ApprovalRequest.id.desc())).all():
        d = to_dict(a)
        if a.target_type == "video":
            run = db.scalar(select(WorkflowRun).where(WorkflowRun.video_id == a.target_id))
            d["run_id"] = run.id if run else None
        else:
            run = db.scalar(select(WorkflowRun).where(WorkflowRun.script_id == a.target_id))
            d["run_id"] = run.id if run else None
        out.append(d)
    return out


class DecideBody(BaseModel):
    approve: bool
    privacy: str = Field("private", pattern="^(private|unlisted|public)$")
    publish_at: datetime | None = None
    schedule_next_slot: bool = False
    note: str = ""


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecideBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    req = get_or_404(db, ApprovalRequest, approval_id)
    if req.status != "pending":
        raise HTTPException(400, f"already {req.status}")
    if req.kind == "script":
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.script_id == req.target_id))
        req.status = "approved" if body.approve else "rejected"
        req.note, req.decided_by, req.decided_at = body.note, user.id, datetime.now(timezone.utc)
        if run:
            run.status = "pending"
        db.commit()
        if run:
            enqueue_run(run.id)
        return to_dict(req)
    video = get_or_404(db, Video, req.target_id)
    if not body.approve:
        req.status, req.note, req.decided_by, req.decided_at = "rejected", body.note, user.id, datetime.now(timezone.utc)
        video.status = "rejected"
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.video_id == video.id))
        if run:
            run.status = "pending"
        audit(db, "video.reject", user_id=user.id, entity_type="video", entity_id=video.id, detail={"note": body.note})
        db.commit()
        if run:
            enqueue_run(run.id)
        return to_dict(req)
    publish_at = body.publish_at
    privacy = body.privacy
    if body.schedule_next_slot:
        publish_at = publishing.next_slot(db, db.get(Channel, video.channel_id))
        privacy = "public"
    if publish_at and privacy != "public":
        raise HTTPException(400, "Scheduled publishing makes the video public at that time; choose privacy=public")
    _approve_video(db, user, video, privacy, publish_at)
    db.refresh(req)
    return to_dict(req)
