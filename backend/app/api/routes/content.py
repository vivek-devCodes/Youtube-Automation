from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, require, to_dict
from app.database.session import get_db
from app.models import (ApprovalRequest, AssetLicense, Channel, ContentIdea, MediaAsset, ResearchSource, Scene, Script, Trend,
                        User, Video, VideoMetadata, Voiceover, WorkflowRun)
from app.services.audit import audit
from app.workers.dispatch import enqueue_run
from app.workflows import pipeline

router = APIRouter(prefix="/content", tags=["content"])


class GenerateBody(BaseModel):
    channel_id: int
    trend_id: int | None = None
    topic: str | None = Field(None, max_length=300)
    format: str = Field("short", pattern="^(short|long)$")
    review_script: bool = True


@router.post("/generate")
def generate(body: GenerateBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    channel = get_or_404(db, Channel, body.channel_id)
    if body.trend_id:
        trend = get_or_404(db, Trend, body.trend_id)
    elif body.topic:
        trend = Trend(channel_id=channel.id, source="manual", external_id=f"manual:{body.topic.lower()[:250]}",
                      topic=body.topic, title=body.topic, niche=channel.niches[0].slug if channel.niches else "")
        existing = db.scalar(select(Trend).where(Trend.channel_id == channel.id, Trend.source == "manual",
                                                 Trend.external_id == trend.external_id))
        trend = existing or trend
        db.add(trend)
        db.flush()
    else:
        raise HTTPException(400, "Provide trend_id or topic")
    idea = pipeline.idea_from_trend(db, trend, channel, body.format, body.topic)
    run = pipeline.start_run(db, idea, review_script=body.review_script)
    audit(db, "content.generate", user_id=user.id, entity_type="run", entity_id=run.id, detail=body.model_dump())
    db.commit()
    enqueue_run(run.id)
    return {"run_id": run.id, "idea_id": idea.id, "video_id": run.video_id}


def run_summary(db: Session, run: WorkflowRun) -> dict:
    idea = db.get(ContentIdea, run.idea_id)
    video = db.get(Video, run.video_id) if run.video_id else None
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == run.video_id)) if run.video_id else None
    d = to_dict(run)
    d["idea"] = to_dict(idea)
    d["video"] = to_dict(video) if video else None
    if video:
        ch = db.get(Channel, run.channel_id)
        d["video"]["sandbox"] = bool(ch and ch.is_sandbox)
        thumb = video.file_path.replace("final.mp4", "thumbnail.jpg") if video.file_path else None
        d["video"]["thumbnail"] = thumb
    d["title"] = meta.title if meta else idea.title if idea else ""
    return d


@router.get("")
def list_runs(channel_id: int | None = None, status: str | None = None, limit: int = 100,
              user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = select(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(min(limit, 500))
    if channel_id:
        q = q.where(WorkflowRun.channel_id == channel_id)
    if status:
        q = q.where(WorkflowRun.status == status)
    return [run_summary(db, r) for r in db.scalars(q).all()]


@router.get("/{run_id}")
def get_run(run_id: int, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    run = get_or_404(db, WorkflowRun, run_id)
    d = run_summary(db, run)
    d["sources"] = [to_dict(s) for s in db.scalars(select(ResearchSource).where(ResearchSource.idea_id == run.idea_id)).all()]
    script = db.get(Script, run.script_id) if run.script_id else None
    d["script"] = to_dict(script) if script else None
    if script:
        scenes = []
        for s in db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all():
            sd = to_dict(s)
            vo = db.scalar(select(Voiceover).where(Voiceover.scene_id == s.id))
            img = db.scalar(select(MediaAsset).where(MediaAsset.scene_id == s.id, MediaAsset.kind == "image",
                                                     MediaAsset.video_id == run.video_id))
            sd["voiceover"] = to_dict(vo) if vo else None
            sd["image"] = to_dict(img) if img else None
            scenes.append(sd)
        d["scenes"] = scenes
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == run.video_id))
    d["metadata"] = to_dict(meta) if meta else None
    assets = db.scalars(select(MediaAsset).where(MediaAsset.video_id == run.video_id)).all()
    d["provenance"] = [{**to_dict(a), "license": to_dict(db.scalar(select(AssetLicense).where(AssetLicense.asset_id == a.id)))}
                       for a in assets]
    d["approvals"] = [to_dict(a) for a in db.scalars(select(ApprovalRequest).where(
        ((ApprovalRequest.target_type == "video") & (ApprovalRequest.target_id == run.video_id))
        | ((ApprovalRequest.target_type == "script") & (ApprovalRequest.target_id == (run.script_id or -1))))).all()]
    return d


class ScenePatch(BaseModel):
    id: int
    narration: str | None = Field(None, max_length=3000)
    on_screen_text: str | None = Field(None, max_length=200)
    visual_prompt: str | None = Field(None, max_length=2000)


class ContentPatch(BaseModel):
    scenes: list[ScenePatch] = []
    metadata: dict | None = None


@router.patch("/{run_id}")
def edit(run_id: int, body: ContentPatch, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    """Edit script scenes/metadata. Only the affected assets are regenerated; the run resumes from the earliest affected step."""
    run = get_or_404(db, WorkflowRun, run_id)
    if run.status == "running" and run.locked_until:
        raise HTTPException(409, "This run is processing right now; try again when it pauses")
    video = db.get(Video, run.video_id)
    if video and video.status in ("uploading", "uploaded", "scheduled", "published"):
        raise HTTPException(409, "Already uploaded — edits are not possible")
    earliest = None
    script = db.get(Script, run.script_id) if run.script_id else None
    for sp in body.scenes:
        scene = db.get(Scene, sp.id)
        if not scene or not script or scene.script_id != script.id:
            raise HTTPException(400, f"scene {sp.id} does not belong to this run")
        if sp.narration is not None and sp.narration.strip() != scene.narration:
            scene.narration = sp.narration.strip()
            db.execute(delete(Voiceover).where(Voiceover.scene_id == scene.id))
            earliest = "originality"
        if sp.visual_prompt is not None and sp.visual_prompt != scene.visual_prompt:
            scene.visual_prompt = sp.visual_prompt
            db.execute(delete(MediaAsset).where(MediaAsset.scene_id == scene.id, MediaAsset.video_id == run.video_id))
            earliest = earliest or "visuals"
        if sp.on_screen_text is not None and sp.on_screen_text != scene.on_screen_text:
            scene.on_screen_text = sp.on_screen_text
            if scene.idx == 0:
                db.execute(delete(MediaAsset).where(MediaAsset.scene_id == scene.id, MediaAsset.video_id == run.video_id))
            earliest = earliest or "visuals"
    if script and earliest == "originality":
        scenes = db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all()
        script.body = " ".join(s.narration for s in scenes)
        script.hook = scenes[0].narration if scenes else script.hook
    if body.metadata:
        meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == run.video_id))
        if not meta:
            raise HTTPException(400, "metadata not generated yet")
        for k in ("title", "description", "tags", "hashtags", "thumbnail_text", "playlist_id"):
            if k in body.metadata:
                v = body.metadata[k]
                if k == "title" and (not str(v).strip() or len(str(v)) > 100):
                    raise HTTPException(400, "title must be 1-100 characters")
                setattr(meta, k, v)
        if "thumbnail_text" in body.metadata:
            earliest = earliest or "render"
    if earliest:
        steps = pipeline.STEPS
        start = steps.index(earliest)
        for s in steps[start:]:
            if s in ("approval", "publish", "script_review"):
                continue
            pipeline._set_step(run, s, status="pending")
        pipeline._set_step(run, "approval", status="pending")
        if video:
            video.status = "in_production"
        if run.status in ("succeeded", "failed", "waiting_approval", "paused"):
            run.status = "pending"
        for req in db.scalars(select(ApprovalRequest).where(ApprovalRequest.target_type == "video",
                                                            ApprovalRequest.target_id == run.video_id,
                                                            ApprovalRequest.status == "pending")).all():
            req.status = "superseded"
    audit(db, "content.edit", user_id=user.id, entity_type="run", entity_id=run.id, detail={"resume_from": earliest})
    db.commit()
    return get_run(run_id, user, db)


class Decision(BaseModel):
    approve: bool
    note: str = ""


@router.post("/{run_id}/script-decision")
def script_decision(run_id: int, body: Decision, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    run = get_or_404(db, WorkflowRun, run_id)
    req = db.scalar(select(ApprovalRequest).where(ApprovalRequest.kind == "script", ApprovalRequest.target_id == run.script_id,
                                                  ApprovalRequest.status == "pending"))
    if not req:
        raise HTTPException(400, "no pending script review for this run")
    req.status = "approved" if body.approve else "rejected"
    req.note, req.decided_by, req.decided_at = body.note, user.id, datetime.now(timezone.utc)
    run.status = "pending"
    audit(db, "script.decision", user_id=user.id, entity_type="run", entity_id=run.id, detail=body.model_dump())
    db.commit()
    enqueue_run(run.id)
    return {"ok": True}


class RetryBody(BaseModel):
    from_step: str | None = None


@router.post("/{run_id}/retry")
def retry(run_id: int, body: RetryBody, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    run = get_or_404(db, WorkflowRun, run_id)
    if body.from_step and body.from_step not in pipeline.STEPS:
        raise HTTPException(400, "unknown step")
    if run.status == "succeeded" and not body.from_step:
        raise HTTPException(400, "run already succeeded")
    pipeline.resume(db, run, body.from_step)
    audit(db, "run.retry", user_id=user.id, entity_type="run", entity_id=run.id, detail=body.model_dump())
    db.commit()
    enqueue_run(run.id)
    return {"ok": True}


@router.post("/{run_id}/cancel")
def cancel(run_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    run = get_or_404(db, WorkflowRun, run_id)
    run.cancel_requested = True
    if run.status not in ("running",):
        run.status = "cancelled"
        video = db.get(Video, run.video_id)
        if video and video.status not in ("published", "scheduled", "uploaded"):
            video.status = "cancelled"
    audit(db, "run.cancel", user_id=user.id, entity_type="run", entity_id=run.id)
    db.commit()
    return {"ok": True}
