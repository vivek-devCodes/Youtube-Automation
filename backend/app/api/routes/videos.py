from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import qa
from app.api.deps import current_user, get_or_404, require, to_dict
from app.core.storage import storage
from app.database.session import get_db
from app.models import (AnalyticsSnapshot, Channel, PublishingHistory, PublishingJob, Subtitle, Thumbnail, User, Video,
                        VideoMetadata, WorkflowRun)
from app.workers.dispatch import enqueue_run
from app.workflows import pipeline

router = APIRouter(prefix="/videos", tags=["videos"])
media_router = APIRouter(tags=["media"])


def video_out(db: Session, v: Video) -> dict:
    d = to_dict(v)
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == v.id))
    d["metadata"] = to_dict(meta) if meta else None
    thumb = db.scalar(select(Thumbnail).where(Thumbnail.video_id == v.id, Thumbnail.is_selected.is_(True)))
    d["thumbnail"] = thumb.path if thumb else None
    snap = db.scalar(select(AnalyticsSnapshot).where(AnalyticsSnapshot.video_id == v.id).order_by(AnalyticsSnapshot.captured_at.desc()).limit(1))
    d["analytics"] = to_dict(snap) if snap else None
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.video_id == v.id))
    d["run_id"] = run.id if run else None
    d["run_status"] = run.status if run else None
    ch = db.get(Channel, v.channel_id)
    d["sandbox"] = bool(ch and ch.is_sandbox)
    return d


@router.get("")
def list_videos(channel_id: int | None = None, format: str | None = None, status: str | None = None,
                user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = select(Video).order_by(Video.id.desc()).limit(500)
    if channel_id:
        q = q.where(Video.channel_id == channel_id)
    if format:
        q = q.where(Video.format == format)
    if status:
        q = q.where(Video.status.in_(status.split(",")))
    return [video_out(db, v) for v in db.scalars(q).all()]


@router.get("/{video_id}")
def get_video(video_id: int, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    v = get_or_404(db, Video, video_id)
    d = video_out(db, v)
    d["subtitles"] = [to_dict(s) for s in db.scalars(select(Subtitle).where(Subtitle.video_id == v.id)).all()]
    d["jobs"] = [to_dict(j) for j in db.scalars(select(PublishingJob).where(PublishingJob.video_id == v.id)).all()]
    d["history"] = [to_dict(h) for h in db.scalars(select(PublishingHistory).where(PublishingHistory.video_id == v.id)
                                                    .order_by(PublishingHistory.id)).all()]
    d["analytics_history"] = [to_dict(s) for s in db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.video_id == v.id)
                                                             .order_by(AnalyticsSnapshot.captured_at)).all()]
    return d


class RenderBody(BaseModel):
    run_id: int


@router.post("/render")
def render(body: RenderBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    """Re-render a run's video from existing script/voice/visual assets (missing ones are regenerated)."""
    run = get_or_404(db, WorkflowRun, body.run_id)
    if not run.script_id:
        raise HTTPException(400, "script not written yet")
    pipeline.resume(db, run, "voice")
    enqueue_run(run.id)
    return {"queued": True}


@router.post("/{video_id}/quality-check")
def quality_check(video_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    v = get_or_404(db, Video, video_id)
    if not v.file_path:
        raise HTTPException(400, "video not rendered yet")
    return qa.run_qa(db, v, db.get(Channel, v.channel_id))


@media_router.get("/media/{key:path}")
def media(key: str, user: User = Depends(current_user)):
    """Authenticated access to generated media (videos are private until published)."""
    if not any(key.startswith(p) for p in ("videos/", "channels/", "scripts/")):
        raise HTTPException(404)
    try:
        path = storage.path(key)
    except ValueError as e:
        raise HTTPException(404) from e
    if not path.exists() or path.is_dir():
        raise HTTPException(404)
    return FileResponse(path)
