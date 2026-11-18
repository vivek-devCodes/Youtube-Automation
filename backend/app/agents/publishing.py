"""Agent 11: YouTube Publishing. Approval-gated by default, idempotent, resumable, quota-aware.
Success is recorded only after YouTube returns the created video resource."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import QuotaExceeded, StudioError, YouTubeError
from app.core.storage import storage
from app.integrations.youtube.client import SandboxYouTube
from app.models import (ApprovalRequest, Channel, PublishingHistory, PublishingJob, Thumbnail, Video, VideoMetadata)
from app.services import usage
from app.services.audit import notify
from app.services.youtube import youtube_for_channel

log = logging.getLogger(__name__)


def history(db: Session, video_id: int, event: str, job_id: int | None = None, **detail) -> None:
    db.add(PublishingHistory(job_id=job_id, video_id=video_id, event=event, detail=detail))


def unattended_allowed(db: Session, channel: Channel) -> bool:
    auto = usage.get_automation(db)
    return bool(channel.settings.auto_publish and not channel.settings.require_approval and auto
                and auto.unattended_publishing_enabled and auto.unattended_publishing_confirmed_at)


def next_slot(db: Session, channel: Channel, after: datetime | None = None) -> datetime:
    cs = channel.settings
    tz = ZoneInfo(cs.timezone or "UTC")
    after = (after or datetime.now(timezone.utc)) + timedelta(minutes=20)
    taken = {j.scheduled_for.replace(tzinfo=timezone.utc) if j.scheduled_for.tzinfo is None else j.scheduled_for
             for j in db.scalars(select(PublishingJob).where(PublishingJob.channel_id == channel.id,
                                                              PublishingJob.scheduled_for.is_not(None),
                                                              PublishingJob.status.in_(("queued", "uploading", "succeeded"))))}
    times = sorted(cs.publish_times or ["18:00"])
    local = after.astimezone(tz)
    for day in range(0, 60):
        d = (local + timedelta(days=day)).date()
        for t in times:
            hh, mm = (int(x) for x in t.split(":"))
            slot = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
            if slot > after and slot not in taken:
                return slot
    return after + timedelta(days=1)


def request_approval(db: Session, video: Video, channel: Channel) -> ApprovalRequest:
    existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.target_type == "video", ApprovalRequest.target_id == video.id,
                                                       ApprovalRequest.kind == "video_publish", ApprovalRequest.status == "pending"))
    if existing:
        return existing
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id))
    req = ApprovalRequest(channel_id=channel.id, kind="video_publish", target_type="video", target_id=video.id,
                          summary=f"{meta.title if meta else 'Video'} — QA {video.quality_score}",
                          payload={"suggested_slot": next_slot(db, channel).isoformat(), "quality_score": video.quality_score})
    db.add(req)
    video.status = "awaiting_approval"
    notify(db, "Video ready for review", f"'{req.summary}' passed QA and needs your approval.", link=f"/library?video={video.id}")
    db.commit()
    return req


def create_job(db: Session, video: Video, channel: Channel, *, privacy: str, publish_at: datetime | None,
               approved_by: int | None) -> PublishingJob:
    """Idempotent: one upload job per video, ever (key = video id)."""
    key = f"upload:video:{video.id}"
    job = db.scalar(select(PublishingJob).where(PublishingJob.idempotency_key == key))
    if job:
        if job.status in ("failed", "cancelled") and not job.youtube_video_id:
            job.status, job.privacy_status, job.scheduled_for, job.last_error = "queued", privacy, publish_at, None
            db.commit()
        return job
    if privacy not in ("private", "unlisted", "public"):
        raise StudioError("privacy must be private, unlisted or public")
    job = PublishingJob(video_id=video.id, channel_id=channel.id, idempotency_key=key, privacy_status=privacy,
                        scheduled_for=publish_at, run_after=datetime.now(timezone.utc), approved_by=approved_by)
    db.add(job)
    db.flush()
    video.status = "approved"
    history(db, video.id, "queued", job.id, privacy=privacy, publish_at=publish_at.isoformat() if publish_at else None)
    db.commit()
    return job


def _body(meta: VideoMetadata, job: PublishingJob) -> dict:
    status: dict = {"privacyStatus": job.privacy_status, "selfDeclaredMadeForKids": meta.made_for_kids,
                    "containsSyntheticMedia": meta.contains_synthetic_media, "embeddable": True, "license": "youtube"}
    if job.scheduled_for and job.privacy_status == "public":
        # YouTube schedules by uploading as private with publishAt.
        status["privacyStatus"] = "private"
        sf = job.scheduled_for if job.scheduled_for.tzinfo else job.scheduled_for.replace(tzinfo=timezone.utc)
        status["publishAt"] = sf.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"snippet": {"title": meta.title, "description": meta.description, "tags": meta.tags, "categoryId": meta.category_id,
                        "defaultLanguage": meta.language, "defaultAudioLanguage": meta.language}, "status": status}


def execute_job(db: Session, job: PublishingJob) -> PublishingJob:
    video = db.get(Video, job.video_id)
    channel = db.get(Channel, job.channel_id)
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id))
    if job.youtube_video_id or job.status == "succeeded":
        return job  # never upload twice
    if not meta or not video.file_path or not storage.exists(video.file_path):
        job.status, job.last_error = "failed", "video file or metadata missing"
        db.commit()
        return job
    if video.qa_report and not video.qa_report.get("passed"):
        job.status, job.last_error = "failed", "video did not pass QA"
        db.commit()
        return job
    path = storage.path(video.file_path)
    size = path.stat().st_size
    job.status = "uploading"
    job.attempts += 1
    video.status = "uploading"
    db.commit()
    body = _body(meta, job)

    def progress(n: int) -> None:
        job.bytes_uploaded = n
        db.commit()

    try:
        if channel.is_sandbox:
            resource = SandboxYouTube(storage.root).upload(path, body, progress)
        else:
            def charge(units: int, op: str) -> None:
                usage.charge_youtube_quota(db, units, op, settings.youtube_daily_quota, channel.id)
                db.commit()

            yt = youtube_for_channel(db, channel, charge=charge)
            start = 0
            resource = None
            if job.upload_session_url:
                try:
                    start, resource = yt.upload_status(job.upload_session_url, size)
                    history(db, video.id, "resumed", job.id, offset=start)
                except YouTubeError:
                    job.upload_session_url = None
            if resource is None:
                if not job.upload_session_url:
                    job.upload_session_url = yt.start_resumable_upload(body, size)
                    history(db, video.id, "session_started", job.id)
                    db.commit()  # persist before sending bytes so a crash resumes instead of duplicating
                resource = yt.upload_chunks(job.upload_session_url, path, start, progress)
        vid = resource.get("id")
        upload_status = resource.get("status", {}).get("uploadStatus")
        if not vid or upload_status in ("failed", "rejected", "deleted"):
            raise YouTubeError(f"YouTube did not confirm the upload (status={upload_status})", retryable=False)
    except QuotaExceeded as e:
        job.status, job.last_error = "queued", str(e)
        job.run_after = datetime.now(timezone.utc) + timedelta(hours=6)
        video.status = "approved"
        history(db, video.id, "quota_deferred", job.id, error=str(e))
        notify(db, "Upload deferred: YouTube quota", str(e), level="warning")
        db.commit()
        return job
    except Exception as e:  # noqa: BLE001
        retry = getattr(e, "retryable", True) and job.attempts < 5
        job.last_error = str(e)[:2000]
        job.status = "queued" if retry else "failed"
        job.run_after = datetime.now(timezone.utc) + timedelta(minutes=2 ** job.attempts * 5)
        video.status = "approved" if retry else "failed"
        history(db, video.id, "upload_error", job.id, error=str(e)[:500], will_retry=retry)
        if not retry:
            notify(db, "Upload failed", f"Video {video.id}: {e}", level="critical", link=f"/library?video={video.id}")
        db.commit()
        return job

    job.youtube_video_id = vid
    job.status = "succeeded"
    job.bytes_uploaded = size
    video.youtube_video_id = vid
    video.youtube_url = None if channel.is_sandbox else f"https://www.youtube.com/watch?v={vid}"
    publish_at = body["status"].get("publishAt")
    video.status = "scheduled" if publish_at else ("published" if job.privacy_status == "public" else "uploaded")
    video.published_at = job.scheduled_for if publish_at else datetime.now(timezone.utc)
    history(db, video.id, "uploaded", job.id, youtube_video_id=vid, upload_status=upload_status, sandbox=channel.is_sandbox,
            privacy=body["status"]["privacyStatus"], publish_at=publish_at)
    db.commit()

    if not channel.is_sandbox:  # follow-up calls are best-effort; the upload itself already succeeded
        thumb = db.scalar(select(Thumbnail).where(Thumbnail.video_id == video.id, Thumbnail.is_selected.is_(True)))
        try:
            if thumb and storage.exists(thumb.path):
                yt.set_thumbnail(vid, storage.path(thumb.path))
                history(db, video.id, "thumbnail_set", job.id)
        except StudioError as e:
            history(db, video.id, "thumbnail_failed", job.id, error=str(e)[:300],
                    hint="Custom thumbnails require a phone-verified channel")
        if meta.playlist_id:
            try:
                yt.add_to_playlist(meta.playlist_id, vid)
                history(db, video.id, "playlist_added", job.id, playlist=meta.playlist_id)
            except StudioError as e:
                history(db, video.id, "playlist_failed", job.id, error=str(e)[:300])
        db.commit()
    notify(db, "Video uploaded" + (" (sandbox simulation)" if channel.is_sandbox else ""),
           f"{meta.title} → {video.status}", link=f"/library?video={video.id}")
    db.commit()
    return job


def run_due_jobs(db: Session, limit: int = 3) -> int:
    now = datetime.now(timezone.utc)
    jobs = db.scalars(select(PublishingJob).where(PublishingJob.status == "queued").order_by(PublishingJob.id).limit(20)).all()
    n = 0
    for job in jobs:
        ra = job.run_after.replace(tzinfo=timezone.utc) if job.run_after and job.run_after.tzinfo is None else job.run_after
        if ra and ra > now:
            continue
        execute_job(db, job)
        n += 1
        if n >= limit:
            break
    return n
