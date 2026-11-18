from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import trends as trend_agent
from app.api.deps import get_or_404, require, to_dict
from app.core.errors import StudioError
from app.database.session import get_db
from app.models import Channel, Trend, User
from app.services.audit import audit
from app.workers.dispatch import enqueue_run, enqueue_scan
from app.workflows import pipeline

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("")
def list_trends(channel_id: int | None = None, status: str | None = None, niche: str | None = None,
                source: str | None = None, min_score: float = 0, limit: int = Query(100, le=500),
                user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = select(Trend).where(Trend.score >= min_score)
    if channel_id:
        q = q.where(Trend.channel_id == channel_id)
    if status:
        q = q.where(Trend.status == status)
    if niche:
        q = q.where(Trend.niche == niche)
    if source:
        q = q.where(Trend.source == source)
    return [to_dict(t) for t in db.scalars(q.order_by(Trend.score.desc()).limit(limit)).all()]


class ScanBody(BaseModel):
    channel_id: int | None = None


@router.post("/scan")
def scan(body: ScanBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    if body.channel_id:
        get_or_404(db, Channel, body.channel_id)
    enqueue_scan(body.channel_id)
    return {"queued": True}


class ApproveBody(BaseModel):
    format: str = Field("short", pattern="^(short|long)$")
    title: str | None = None
    start_production: bool = True
    review_script: bool = False


@router.post("/{trend_id}/approve")
def approve(trend_id: int, body: ApproveBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trend, trend_id)
    if not t.channel_id:
        raise HTTPException(400, "trend is not linked to a channel")
    channel = db.get(Channel, t.channel_id)
    t.status = "approved"
    audit(db, "trend.approve", user_id=user.id, entity_type="trend", entity_id=t.id, detail=body.model_dump())
    db.commit()
    if not body.start_production:
        return {"trend": to_dict(t)}
    idea = pipeline.idea_from_trend(db, t, channel, body.format, body.title)
    run = pipeline.start_run(db, idea, review_script=body.review_script)
    enqueue_run(run.id)
    return {"trend": to_dict(t), "run_id": run.id, "idea_id": idea.id}


@router.post("/{trend_id}/reject")
def reject(trend_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trend, trend_id)
    t.status = "rejected"
    audit(db, "trend.reject", user_id=user.id, entity_type="trend", entity_id=t.id)
    db.commit()
    return to_dict(t)


@router.post("/{trend_id}/ideas")
def ideas(trend_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trend, trend_id)
    try:
        trend_agent.suggest_ideas(db, t, db.get(Channel, t.channel_id))
    except StudioError as e:
        raise HTTPException(400, str(e)) from e
    return to_dict(t)
