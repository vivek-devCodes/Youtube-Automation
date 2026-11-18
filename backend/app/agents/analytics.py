"""Agent 12: Analytics & Optimization. Read-only toward YouTube: it never deletes videos or edits
metadata. Findings are written to automation_settings.optimization_insights for the planner/scriptwriter."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import StudioError
from app.core.storage import storage
from app.integrations.youtube.client import SandboxYouTube
from app.models import AnalyticsSnapshot, Channel, ContentIdea, Script, Trend, Video
from app.services import usage
from app.services.youtube import youtube_for_channel

log = logging.getLogger(__name__)


def _window(age_h: float) -> str:
    return "24h" if age_h <= 24 else "48h" if age_h <= 48 else "7d" if age_h <= 168 else "28d" if age_h <= 672 else "lifetime"


def collect_channel(db: Session, channel: Channel) -> dict:
    vids = db.scalars(select(Video).where(Video.channel_id == channel.id, Video.youtube_video_id.is_not(None))).all()
    now = datetime.now(timezone.utc)
    out = {"videos": len(vids), "snapshots": 0, "errors": []}
    if channel.is_sandbox:
        sb = SandboxYouTube(storage.root)
        total_views = 0
        for v in vids:
            pub = v.published_at.replace(tzinfo=timezone.utc) if v.published_at and v.published_at.tzinfo is None else (v.published_at or now)
            age = max(0.5, (now - pub).total_seconds() / 3600)
            s = sb.stats(v.youtube_video_id, age)
            total_views += s["views"]
            db.add(AnalyticsSnapshot(channel_id=channel.id, video_id=v.id, window=_window(age), views=s["views"], likes=s["likes"],
                                     comments=s["comments"], watch_time_minutes=s["watch_minutes"],
                                     avg_view_duration_seconds=s["avg_view_duration"],
                                     avg_view_percentage=round(100 * s["avg_view_duration"] / max(1, v.duration_seconds or 60), 1),
                                     subscribers_gained=s["subscribers_gained"], source="sandbox"))
            out["snapshots"] += 1
        db.add(AnalyticsSnapshot(channel_id=channel.id, window="channel", views=total_views,
                                 subscribers_total=sum(1 for _ in vids) * 3, source="sandbox"))
        db.commit()
        return out

    def charge(units: int, op: str) -> None:
        usage.charge_youtube_quota(db, units, op, settings.youtube_daily_quota, channel.id)

    try:
        yt = youtube_for_channel(db, channel, charge=charge)
        ch = yt.my_channels()
        if ch:
            st = ch[0].get("statistics", {})
            channel.subscriber_count = int(st.get("subscriberCount", 0))
            channel.view_count = int(st.get("viewCount", 0))
            channel.video_count = int(st.get("videoCount", 0))
            db.add(AnalyticsSnapshot(channel_id=channel.id, window="channel", views=channel.view_count,
                                     subscribers_total=channel.subscriber_count, source="data_api"))
        by_id = {v.youtube_video_id: v for v in vids}
        stats = {i["id"]: i.get("statistics", {}) for i in yt.videos(list(by_id), part="statistics")} if by_id else {}
        analytics: dict[str, dict] = {}
        if by_id:
            start = (now - timedelta(days=90)).date().isoformat()
            metrics = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "subscribersGained", "shares"]
            if settings.enable_monetary_analytics:
                metrics.append("estimatedRevenue")
            ids = list(by_id)
            for i in range(0, len(ids), 200):
                try:
                    rep = yt.analytics_report(start, now.date().isoformat(), metrics, dimensions="video",
                                              filters="video==" + ",".join(ids[i : i + 200]))
                    cols = [c["name"] for c in rep.get("columnHeaders", [])]
                    for row in rep.get("rows", []):
                        analytics[row[0]] = dict(zip(cols, row))
                except StudioError as e:
                    out["errors"].append(f"analytics: {e}")
        for yid, v in by_id.items():
            s, a = stats.get(yid, {}), analytics.get(yid, {})
            pub = v.published_at.replace(tzinfo=timezone.utc) if v.published_at and v.published_at.tzinfo is None else (v.published_at or now)
            age = max(0.5, (now - pub).total_seconds() / 3600)
            db.add(AnalyticsSnapshot(
                channel_id=channel.id, video_id=v.id, window=_window(age), views=int(s.get("viewCount", a.get("views", 0)) or 0),
                likes=int(s["likeCount"]) if "likeCount" in s else None, comments=int(s["commentCount"]) if "commentCount" in s else None,
                watch_time_minutes=a.get("estimatedMinutesWatched"), avg_view_duration_seconds=a.get("averageViewDuration"),
                avg_view_percentage=a.get("averageViewPercentage"), subscribers_gained=a.get("subscribersGained"),
                shares=a.get("shares"), revenue_usd=a.get("estimatedRevenue"), source="analytics_api" if a else "data_api",
                raw={"statistics": s, "analytics": a}))
            out["snapshots"] += 1
        db.commit()
    except StudioError as e:
        out["errors"].append(str(e))
        db.rollback()
    return out


def _latest_per_video(db: Session) -> dict[int, AnalyticsSnapshot]:
    latest: dict[int, AnalyticsSnapshot] = {}
    for s in db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.video_id.is_not(None)).order_by(AnalyticsSnapshot.captured_at)):
        latest[s.video_id] = s
    return latest


def optimize(db: Session) -> dict:
    latest = _latest_per_video(db)
    if not latest:
        insights = {"summary": "Not enough published videos yet to learn from.", "videos_analyzed": 0}
    else:
        groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        rows = []
        for vid, snap in latest.items():
            v = db.get(Video, vid)
            if not v:
                continue
            idea = db.get(ContentIdea, v.idea_id) if v.idea_id else None
            trend = db.get(Trend, idea.trend_id) if idea and idea.trend_id else None
            script = db.get(Script, v.script_id) if v.script_id else None
            dur = v.duration_seconds or 0
            bucket = "<=30s" if dur <= 30 else "31-60s" if dur <= 60 else "1-3m" if dur <= 180 else "3-8m" if dur <= 480 else "8m+"
            hook_type = "question" if script and script.hook.strip().endswith("?") else "statement"
            for dim, key in (("format", v.format), ("duration", bucket), ("niche", trend.niche if trend else "unknown"),
                             ("language", idea.language if idea else "?"), ("hook", hook_type)):
                groups[dim][key].append(snap.views)
            rows.append((snap.views, idea.title if idea else "", snap.avg_view_percentage))
        best = {dim: max(vals.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[0] for dim, vals in groups.items() if vals}
        rows.sort(key=lambda r: -r[0])
        top = rows[: max(1, len(rows) // 4)]
        words: dict[str, int] = defaultdict(int)
        for _, title, _ in top:
            for w in re.findall(r"[a-z]{4,}", title.lower()):
                words[w] += 1
        retention = [r[2] for r in rows if r[2] is not None]
        avg_ret = round(sum(retention) / len(retention), 1) if retention else None
        insights = {
            "videos_analyzed": len(rows),
            "best": best,
            "winning_keywords": [w for w, _ in sorted(words.items(), key=lambda kv: -kv[1])[:10]],
            "avg_view_percentage": avg_ret,
            "summary": (f"Best format: {best.get('format')}; best length: {best.get('duration')}; best niche: {best.get('niche')}; "
                        f"{best.get('hook')} hooks perform better. "
                        + (f"Average viewers watch {avg_ret}% — " + ("tighten the first 5 seconds." if avg_ret < 50 else "retention is healthy.")
                           if avg_ret is not None else "")),
        }
    insights["updated_at"] = datetime.now(timezone.utc).isoformat()
    auto = usage.get_automation(db)
    if auto:
        auto.optimization_insights = insights
        auto.last_optimization_at = datetime.now(timezone.utc)
        db.commit()
    return insights
