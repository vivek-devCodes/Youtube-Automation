"""Dashboard, analytics, automation control, settings, AI providers, usage, notifications, audit, catalog."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, require, to_dict
from app.core.config import settings
from app.core.security import encrypt_secret, mask_secret
from app.database.session import get_db
from app.integrations.registry import CATALOG, api_key_for, mark_health, model_config
from app.models import (AIProvider, AnalyticsSnapshot, ApiUsage, ApprovalRequest, AuditLog, Channel, ModelConfiguration,
                        Notification, User, Video, WorkflowRun)
from app.services import usage
from app.services.audit import audit
from app.services.catalog import (BUDGET_MODES, LANGUAGES, LONG_RANGES, NICHES, SHORT_DURATIONS, YPP_TARGETS)
from app.services.settings import ensure_automation
from app.workers.dispatch import enqueue, worker_health

router = APIRouter(tags=["system"])
PUBLISHED = ("published", "scheduled", "uploaded")


# ------------------------------------------------------------------ catalog
@router.get("/meta/catalog")
def catalog():
    return {
        "niches": [{"slug": s, "name": n, "category_id": c, "kids": k, "keywords": kw} for s, n, c, k, kw in NICHES],
        "languages": LANGUAGES, "short_durations": SHORT_DURATIONS, "long_ranges": list(LONG_RANGES),
        "budget_modes": BUDGET_MODES, "providers": CATALOG, "ypp_targets": YPP_TARGETS,
        "google_oauth_configured": settings.google_oauth_configured, "youtube_api_key_configured": bool(settings.youtube_api_key),
        "task_mode": settings.task_mode,
    }


# ------------------------------------------------------------------ dashboard
def _latest_video_snaps(db: Session) -> dict[int, AnalyticsSnapshot]:
    latest: dict[int, AnalyticsSnapshot] = {}
    for s in db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.video_id.is_not(None)).order_by(AnalyticsSnapshot.captured_at)):
        latest[s.video_id] = s
    return latest


@router.get("/dashboard")
def dashboard(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    auto = ensure_automation(db, user)
    vids = db.scalars(select(Video)).all()
    latest = _latest_video_snaps(db)
    pub = [v for v in vids if v.status in PUBLISHED]
    channels = db.scalars(select(Channel)).all()
    since90 = datetime.now(timezone.utc) - timedelta(days=90)
    shorts_views_90 = sum(latest[v.id].views for v in pub if v.format == "short" and v.id in latest
                          and v.published_at and _aw(v.published_at) >= since90)
    watch_hours = sum((latest[v.id].watch_time_minutes or 0) for v in pub if v.format == "long" and v.id in latest) / 60
    uploads_90 = sum(1 for v in pub if v.published_at and _aw(v.published_at) >= since90)
    subs = sum(c.subscriber_count for c in channels if not c.is_sandbox)
    revenue = [s.revenue_usd for s in latest.values() if s.revenue_usd is not None]
    return {
        "channels": len(channels),
        "sandbox_channels": sum(1 for c in channels if c.is_sandbox),
        "videos_generated": sum(1 for v in vids if v.file_path),
        "videos_published": len(pub),
        "shorts_published": sum(1 for v in pub if v.format == "short"),
        "long_published": sum(1 for v in pub if v.format == "long"),
        "total_views": sum(s.views for s in latest.values()),
        "total_subscribers": subs,
        "estimated_revenue": round(sum(revenue), 2) if revenue else None,
        "pending_approvals": db.scalar(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")),
        "active_runs": db.scalar(select(func.count(WorkflowRun.id)).where(WorkflowRun.status.in_(("pending", "running", "retry_scheduled")))),
        "failed_runs_7d": db.scalar(select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "failed",
                                                                            WorkflowRun.updated_at >= datetime.now(timezone.utc) - timedelta(days=7))),
        "automation": {"running": auto.is_running, "paused_reason": auto.paused_reason, "budget_mode": auto.budget_mode,
                       "last_trend_scan_at": auto.last_trend_scan_at.isoformat() if auto.last_trend_scan_at else None},
        "costs": {"month_to_date": round(usage.month_to_date_spend(db), 4), "monthly_budget": auto.monthly_budget_usd,
                  "youtube_quota_used_today": usage.youtube_quota_used_today(db), "youtube_quota_limit": settings.youtube_daily_quota},
        "ypp": {"targets": YPP_TARGETS, "progress": {"subscribers": subs, "public_uploads_90d": uploads_90,
                                                     "watch_hours_12m": round(watch_hours, 1), "shorts_views_90d": shorts_views_90},
                "note": "Real channels only count. Eligibility is decided by YouTube review — thresholds change; verify in YouTube Help."},
        "worker": worker_health(),
    }


def _aw(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ------------------------------------------------------------------ analytics
@router.get("/analytics/overview")
def analytics_overview(days: int = 30, channel_id: int | None = None, user: User = Depends(require("viewer")),
                       db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(AnalyticsSnapshot).where(AnalyticsSnapshot.captured_at >= since).order_by(AnalyticsSnapshot.captured_at)
    if channel_id:
        q = q.where(AnalyticsSnapshot.channel_id == channel_id)
    per_day: dict[str, dict[int, AnalyticsSnapshot]] = defaultdict(dict)
    chan_day: dict[str, dict[int, AnalyticsSnapshot]] = defaultdict(dict)
    for s in db.scalars(q):
        day = s.captured_at.date().isoformat()
        if s.video_id:
            per_day[day][s.video_id] = s
        elif s.window == "channel":
            chan_day[day][s.channel_id] = s
    series = []
    for day in sorted(set(per_day) | set(chan_day)):
        vs = per_day.get(day, {}).values()
        ctr = [s.ctr for s in vs if s.ctr is not None]
        ret = [s.avg_view_percentage for s in vs if s.avg_view_percentage is not None]
        series.append({"date": day, "views": sum(s.views for s in vs),
                       "watch_hours": round(sum((s.watch_time_minutes or 0) for s in vs) / 60, 2),
                       "subscribers": sum((s.subscribers_total or 0) for s in chan_day.get(day, {}).values()) or None,
                       "ctr": round(sum(ctr) / len(ctr), 2) if ctr else None,
                       "retention": round(sum(ret) / len(ret), 1) if ret else None,
                       "revenue": round(sum((s.revenue_usd or 0) for s in vs), 2) if any(s.revenue_usd is not None for s in vs) else None})
    auto = ensure_automation(db, user)
    return {"series": series, "insights": auto.optimization_insights or {}}


@router.get("/analytics/videos")
def analytics_videos(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    from app.models import ContentIdea, Trend, VideoMetadata

    out = []
    for vid, s in _latest_video_snaps(db).items():
        v = db.get(Video, vid)
        if not v:
            continue
        meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == vid))
        idea = db.get(ContentIdea, v.idea_id) if v.idea_id else None
        trend = db.get(Trend, idea.trend_id) if idea and idea.trend_id else None
        out.append({"video_id": vid, "title": meta.title if meta else "", "format": v.format, "niche": trend.niche if trend else "",
                    "youtube_video_id": v.youtube_video_id, **{k: getattr(s, k) for k in (
                        "views", "likes", "comments", "watch_time_minutes", "avg_view_duration_seconds", "avg_view_percentage",
                        "subscribers_gained", "ctr", "impressions", "revenue_usd", "source", "window")}})
    out.sort(key=lambda r: -r["views"])
    by_niche: dict[str, dict] = defaultdict(lambda: {"videos": 0, "views": 0})
    for r in out:
        by_niche[r["niche"] or "unknown"]["videos"] += 1
        by_niche[r["niche"] or "unknown"]["views"] += r["views"]
    return {"videos": out, "by_niche": [{"niche": k, **v} for k, v in by_niche.items()]}


@router.get("/analytics/channels")
def analytics_channels(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Channel)).all():
        snaps = db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.channel_id == c.id, AnalyticsSnapshot.window == "channel")
                           .order_by(AnalyticsSnapshot.captured_at)).all()
        out.append({"channel_id": c.id, "title": c.title, "sandbox": c.is_sandbox, "subscribers": c.subscriber_count,
                    "views": c.view_count, "history": [{"date": s.captured_at.isoformat(), "views": s.views,
                                                        "subscribers": s.subscribers_total} for s in snaps]})
    return out


@router.post("/analytics/collect")
def analytics_collect(user: User = Depends(require("editor"))):
    enqueue("collect_analytics", True)
    enqueue("weekly_optimize", True)
    return {"queued": True}


# ------------------------------------------------------------------ automation
@router.get("/automation/status")
def automation_status(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    auto = ensure_automation(db, user)
    runs = db.scalars(select(WorkflowRun).where(WorkflowRun.status.notin_(("succeeded", "cancelled"))).order_by(WorkflowRun.id.desc()).limit(50)).all()
    return {"running": auto.is_running, "paused_reason": auto.paused_reason, "worker": worker_health(),
            "unattended_publishing": auto.unattended_publishing_enabled,
            "runs": [{"id": r.id, "status": r.status, "step": r.current_step, "error": r.last_error,
                      "next_attempt_at": r.next_attempt_at.isoformat() if r.next_attempt_at else None} for r in runs]}


def _set_running(db: Session, user: User, running: bool, action: str):
    auto = ensure_automation(db, user)
    if running and not user.onboarding_completed:
        raise HTTPException(400, "Finish onboarding first")
    auto.is_running = running
    if running:
        auto.paused_reason = None
    audit(db, f"automation.{action}", user_id=user.id)
    db.commit()
    return {"running": auto.is_running}


@router.post("/automation/start")
def automation_start(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return _set_running(db, user, True, "start")


@router.post("/automation/pause")
def automation_pause(user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    return _set_running(db, user, False, "pause")


@router.post("/automation/resume")
def automation_resume(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return _set_running(db, user, True, "resume")


# ------------------------------------------------------------------ settings
@router.get("/settings")
def get_settings_(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    return to_dict(ensure_automation(db, user))


class SettingsPatch(BaseModel):
    budget_mode: str | None = None
    monthly_budget_usd: float | None = Field(None, ge=0)
    trend_scan_interval_minutes: int | None = Field(None, ge=30, le=1440)
    analytics_interval_hours: int | None = Field(None, ge=1, le=168)
    min_quality_score: int | None = Field(None, ge=50, le=100)
    trend_weights: dict[str, float] | None = None
    max_similarity: float | None = Field(None, ge=0.05, le=0.8)
    trademark_blocklist: list[str] | None = None
    data_retention_days: int | None = Field(None, ge=7, le=3650)
    notification_prefs: dict | None = None
    auto_select_topics: bool | None = None
    min_trend_score: float | None = Field(None, ge=0, le=100)
    unattended_publishing_enabled: bool | None = None
    confirm_unattended: bool = False


@router.patch("/settings")
def patch_settings(body: SettingsPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    auto = ensure_automation(db, user)
    data = body.model_dump(exclude_none=True, exclude={"confirm_unattended"})
    if "budget_mode" in data and data["budget_mode"] not in BUDGET_MODES:
        raise HTTPException(400, "invalid budget mode")
    if data.get("unattended_publishing_enabled"):
        if not body.confirm_unattended:
            raise HTTPException(400, "Unattended public publishing requires explicit confirmation (confirm_unattended=true)")
        auto.unattended_publishing_confirmed_at = datetime.now(timezone.utc)
    elif data.get("unattended_publishing_enabled") is False:
        auto.unattended_publishing_confirmed_at = None
    if "trend_weights" in data and any(v < 0 for v in data["trend_weights"].values()):
        raise HTTPException(400, "weights must be non-negative")
    for k, v in data.items():
        setattr(auto, k, v)
    if "monthly_budget_usd" in data and auto.paused_reason and "budget" in auto.paused_reason.lower():
        auto.paused_reason = None  # raising the budget lifts a budget pause
        for r in db.scalars(select(WorkflowRun).where(WorkflowRun.status == "paused")).all():
            r.status = "pending"
    audit(db, "settings.update", user_id=user.id, detail=data)
    db.commit()
    return to_dict(auto)


# ------------------------------------------------------------------ AI providers
def provider_out(db: Session, p: AIProvider) -> dict:
    d = to_dict(p)
    key = api_key_for(p)
    d["api_key_set"] = bool(key)
    d["api_key_masked"] = mask_secret(key)
    d["needs_key"] = any(c.get("env") for c in CATALOG if c["kind"] == p.kind and c["name"] == p.name)
    mc = model_config(db, p)
    d["model"] = to_dict(mc) if mc else None
    if "workflow" in (d.get("config") or {}):
        d["config"] = {**d["config"], "workflow": "(saved)"}
    return d


@router.get("/providers")
def providers(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    return [provider_out(db, p) for p in db.scalars(select(AIProvider).order_by(AIProvider.kind, AIProvider.id)).all()]


class ProviderPatch(BaseModel):
    api_key: str | None = Field(None, max_length=500)
    clear_api_key: bool = False
    base_url: str | None = Field(None, max_length=300)
    enabled: bool | None = None
    is_default: bool | None = None
    model_name: str | None = Field(None, max_length=120)
    cost_per_1k_input: float | None = Field(None, ge=0)
    cost_per_1k_output: float | None = Field(None, ge=0)
    cost_per_unit: float | None = Field(None, ge=0)
    config: dict | None = None


@router.patch("/providers/{provider_id}")
def patch_provider(provider_id: int, body: ProviderPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, provider_id)
    if body.api_key:
        p.api_key_enc = encrypt_secret(body.api_key.strip())  # stored encrypted, never returned
    if body.clear_api_key:
        p.api_key_enc = None
    if body.base_url is not None:
        p.base_url = body.base_url.strip() or None
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.config is not None:
        cfg = dict(p.config or {})
        cfg.update(body.config)
        p.config = cfg
    if body.is_default:
        if not p.enabled and body.enabled is not True:
            raise HTTPException(400, "enable the provider before making it the default")
        for other in db.scalars(select(AIProvider).where(AIProvider.kind == p.kind)).all():
            other.is_default = other.id == p.id
    mc = model_config(db, p)
    if mc is None:
        mc = ModelConfiguration(provider_id=p.id, task="default", model_name=body.model_name or "")
        db.add(mc)
    for k in ("model_name", "cost_per_1k_input", "cost_per_1k_output", "cost_per_unit"):
        v = getattr(body, k)
        if v is not None:
            setattr(mc, k, v)
    audit(db, "provider.update", user_id=user.id, entity_type="provider", entity_id=p.id,
          detail={k: v for k, v in body.model_dump(exclude_none=True).items() if k != "api_key"} | {"api_key_changed": bool(body.api_key)})
    db.commit()
    return provider_out(db, p)


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, user: User = Depends(require("editor")), db: Session = Depends(get_db)):
    from app.integrations.image.providers import IMAGE_PROVIDERS, ComfyUIVideo, ImageConfig
    from app.integrations.llm.mock import MockLLM
    from app.integrations.llm.providers import PROVIDERS, LLMConfig
    from app.integrations.tts.providers import TTS_PROVIDERS, TTSConfig

    p = get_or_404(db, AIProvider, provider_id)
    mc = model_config(db, p)
    key, model = api_key_for(p), (mc.model_name if mc else "")
    try:
        if p.kind == "llm":
            inst = PROVIDERS.get(p.name, MockLLM)(LLMConfig(name=p.name, model=model, api_key=key, base_url=p.base_url, params=p.config or {}))
        elif p.kind == "tts":
            inst = TTS_PROVIDERS[p.name](TTSConfig(name=p.name, api_key=key, base_url=p.base_url, params=p.config or {}))
        elif p.kind == "image":
            inst = IMAGE_PROVIDERS[p.name](ImageConfig(name=p.name, model=model, api_key=key, base_url=p.base_url, params=p.config or {}))
        elif p.name == "comfyui":
            inst = ComfyUIVideo(ImageConfig(name=p.name, base_url=p.base_url, params=p.config or {}))
        else:
            mark_health(db, p, True, "no external service")
            return provider_out(db, p)
        ok, msg = inst.health()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, str(e)
    mark_health(db, p, ok, msg)
    return provider_out(db, p)


# ------------------------------------------------------------------ usage / costs
@router.get("/usage")
def usage_report(days: int = 31, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(select(ApiUsage).where(ApiUsage.created_at >= since)).all()
    by_provider: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0, "units": 0.0})
    by_day: dict[str, float] = defaultdict(float)
    by_video: dict[int, float] = defaultdict(float)
    for r in rows:
        k = f"{r.kind}:{r.provider}"
        by_provider[k]["calls"] += 1
        by_provider[k]["cost_usd"] += r.cost_usd
        by_provider[k]["units"] += r.units
        by_day[r.created_at.date().isoformat()] += r.cost_usd
        if r.video_id:
            by_video[r.video_id] += r.cost_usd
    # LLM calls are tagged with the workflow run; attribute them to that run's video.
    run_costs: dict[int, float] = defaultdict(float)
    for r in rows:
        if r.workflow_run_id:
            run_costs[r.workflow_run_id] += r.cost_usd
    for run_id, cost in run_costs.items():
        run = db.get(WorkflowRun, run_id)
        if run and run.video_id:
            by_video[run.video_id] += cost
    auto = ensure_automation(db, user)
    return {"month_to_date": round(usage.month_to_date_spend(db), 4), "monthly_budget": auto.monthly_budget_usd,
            "budget_mode": auto.budget_mode, "by_provider": [{"provider": k, **{kk: round(vv, 4) for kk, vv in v.items()}}
                                                             for k, v in by_provider.items()],
            "by_day": [{"date": d, "cost_usd": round(c, 4)} for d, c in sorted(by_day.items())],
            "per_video": [{"video_id": v, "cost_usd": round(c, 4)} for v, c in sorted(by_video.items())],
            "youtube_quota_used_today": usage.youtube_quota_used_today(db), "youtube_quota_limit": settings.youtube_daily_quota}


class Estimate(BaseModel):
    format: str = "short"
    seconds: int = 45


@router.post("/usage/estimate")
def estimate(body: Estimate, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    """Estimated cost of producing one video with the current default providers (shown before expensive operations)."""
    from app.integrations.registry import default_provider

    words = body.seconds * 2.5
    scenes = max(3, int(body.seconds / 7))
    lines = []
    for kind, units in (("llm", None), ("tts", words * 6), ("image", scenes)):
        p = default_provider(db, kind)
        mc = model_config(db, p)
        if not p.is_paid or not mc:
            lines.append({"kind": kind, "provider": p.name, "cost_usd": 0.0})
            continue
        if kind == "llm":  # research + script + seo + factcheck + ideas
            cost = 5 * (3000 / 1000 * mc.cost_per_1k_input) + (words * 2 + 3500) / 1000 * mc.cost_per_1k_output
        elif kind == "tts":
            cost = units / 1000 * mc.cost_per_unit
        else:
            cost = units * mc.cost_per_unit
        lines.append({"kind": kind, "provider": p.name, "cost_usd": round(cost, 4)})
    total = round(sum(item["cost_usd"] for item in lines), 4)
    auto = ensure_automation(db, user)
    left = auto.monthly_budget_usd - usage.month_to_date_spend(db)
    return {"lines": lines, "total_usd": total, "budget_remaining_usd": round(left, 4),
            "videos_affordable": int(left / total) if total > 0 else None}


# ------------------------------------------------------------------ notifications / audit
@router.get("/notifications")
def notifications(unread: bool = False, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = select(Notification).order_by(Notification.id.desc()).limit(100)
    if unread:
        q = q.where(Notification.read.is_(False))
    return [to_dict(n) for n in db.scalars(q).all()]


@router.post("/notifications/read")
def mark_read(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.read.is_(False))).all():
        n.read = True
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(limit: int = 200, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [to_dict(a) for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))).all()]
