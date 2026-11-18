"""Agent 1 (Trend Discovery) and Agent 2 (Trend Intelligence)."""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ProviderNotConfigured, QuotaExceeded, StudioError
from app.integrations.llm import service as llm
from app.integrations.trends import sources
from app.models import AutomationSettings, Channel, Trend, TrendSnapshot
from app.services import usage
from app.services.catalog import DEFAULT_TREND_WEIGHTS, NICHE_BY_SLUG
from app.services.youtube import youtube_for_channel

log = logging.getLogger(__name__)
LOW_FEASIBILITY = re.compile(r"\b(official (music )?video|trailer|teaser|highlights|full match|live stream|lyrical|full movie|episode \d+)\b", re.I)


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9ऀ-෿]{3,}", s.lower())}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ===================================================================== Agent 1
def discover(db: Session, channel: Channel, *, use_network: bool = True) -> dict:
    """Collect trend candidates for every niche of a channel and upsert them with snapshots."""
    cs = channel.settings
    region, lang = cs.target_country, cs.language if cs.language != "hinglish" else "hi"
    stats = {"youtube": 0, "google_trends": 0, "news": 0, "mock": 0, "errors": []}
    items: list[tuple[str, sources.TrendItem]] = []

    def quota(units: int, op: str) -> None:
        usage.charge_youtube_quota(db, units, op, settings.youtube_daily_quota, channel.id)

    yt = None
    if use_network:
        try:
            yt = youtube_for_channel(db, channel, charge=quota, read_only=True)
        except (ProviderNotConfigured, StudioError) as e:
            stats["errors"].append(f"youtube: {e}")

    for niche in channel.niches:
        _, _, cat_id, _, seed_kw = NICHE_BY_SLUG.get(niche.slug, (niche.slug, niche.name, None, False, []))
        keywords = (niche.keywords or seed_kw or [niche.name])[:3]
        if use_network and yt:
            try:
                for v in yt.most_popular(region, niche.youtube_category_id or cat_id, max_results=15):
                    items.append((niche.slug, sources.from_youtube_video(v, region)))
                    stats["youtube"] += 1
                # search.list costs 100 units: one query per niche per scan keeps a 10k quota safe.
                for v in yt.search_recent(keywords[0], region, lang, days=7, max_results=10):
                    items.append((niche.slug, sources.from_youtube_video(v, region)))
                    stats["youtube"] += 1
            except QuotaExceeded as e:
                stats["errors"].append(str(e))
            except StudioError as e:
                stats["errors"].append(f"youtube: {e}")
        if use_network:
            for kw in keywords[:2]:
                for it in sources.news_trends(kw, lang if lang in ("en", "hi") else "en", region):
                    items.append((niche.slug, it))
                    stats["news"] += 1
        if not use_network or (stats["youtube"] + stats["news"]) == 0:
            for it in sources.mock_trends(niche.slug, region):
                items.append((niche.slug, it))
                stats["mock"] += 1

    if use_network:
        gt = sources.google_trends_daily(region)
        stats["google_trends"] = len(gt)
        for it in gt:  # general trends: attach to the niche they overlap with, if any
            for niche in channel.niches:
                kws = _tokens(" ".join(niche.keywords or NICHE_BY_SLUG.get(niche.slug, (0, 0, 0, 0, []))[4]) + " " + niche.name)
                if kws & _tokens(it.title + " " + it.description):
                    items.append((niche.slug, it))

    now = datetime.now(timezone.utc)
    touched: list[Trend] = []
    for niche_slug, it in items:
        row = db.scalar(select(Trend).where(Trend.channel_id == channel.id, Trend.source == it.source, Trend.external_id == it.external_id))
        if row is None:
            row = Trend(channel_id=channel.id, source=it.source, external_id=it.external_id[:300], niche=niche_slug)
            db.add(row)
        for f in ("topic", "title", "description", "source_channel", "source_url", "published_at", "category_id", "language",
                  "region", "duration_seconds", "view_count", "like_count", "comment_count", "keywords"):
            setattr(row, f, getattr(it, f))
        row.title = row.title[:500]
        row.score_breakdown = {**(row.score_breakdown or {}), "search_interest_raw": it.search_interest}
        row.last_seen_at = now
        db.flush()
        db.add(TrendSnapshot(trend_id=row.id, view_count=it.view_count, like_count=it.like_count, comment_count=it.comment_count))
        touched.append(row)
    db.flush()
    auto = db.scalar(select(AutomationSettings).limit(1))
    for row in touched:
        score_trend(db, row, channel, auto)
    db.commit()
    stats["stored"] = len(touched)
    return stats


# ===================================================================== Agent 2
def score_trend(db: Session, t: Trend, channel: Channel, auto: AutomationSettings | None) -> None:
    weights = {**DEFAULT_TREND_WEIGHTS, **((auto.trend_weights if auto else None) or {})}
    now = datetime.now(timezone.utc)
    snaps = db.scalars(select(TrendSnapshot).where(TrendSnapshot.trend_id == t.id).order_by(TrendSnapshot.captured_at)).all()
    published = _aware(t.published_at)
    age_h = max(1.0, (now - published).total_seconds() / 3600) if published else 24.0
    if len(snaps) >= 2 and t.source == "youtube":
        a, b = snaps[0], snaps[-1]
        dh = max(0.25, (_aware(b.captured_at) - _aware(a.captured_at)).total_seconds() / 3600)
        velocity = max(0.0, (b.view_count - a.view_count) / dh)
    else:
        velocity = t.view_count / age_h if t.source in ("youtube", "mock") else 0.0
    t.view_velocity = round(velocity, 2)

    s_velocity = min(1.0, math.log10(velocity + 1) / 5)  # 100k views/hour => 1.0
    if t.view_count and t.like_count is not None:
        rate = (t.like_count + 2 * (t.comment_count or 0)) / t.view_count
        s_engagement = min(1.0, rate / 0.08)
    else:
        s_engagement = 0.4
    s_search = float((t.score_breakdown or {}).get("search_interest_raw") or (0.5 if t.source == "youtube" else 0.3))
    s_fresh = math.exp(-age_h / 48)
    niche_kw = set()
    for n in channel.niches:
        if n.slug == t.niche:
            niche_kw = _tokens(" ".join(n.keywords or NICHE_BY_SLUG.get(n.slug, (0, 0, 0, 0, []))[4]) + " " + n.name)
    text = _tokens(f"{t.title} {t.description} {' '.join(t.keywords or [])}")
    s_relevance = min(1.0, 0.3 + 0.35 * len(niche_kw & text)) if niche_kw else 0.3
    insights = (auto.optimization_insights if auto else None) or {}
    boost_words = set(w.lower() for w in insights.get("winning_keywords", []))
    if boost_words & text:
        s_relevance = min(1.0, s_relevance + 0.15)
    s_feasible = 0.2 if (t.category_id == "10" or LOW_FEASIBILITY.search(t.title)) else 0.85
    if t.duration_seconds and t.duration_seconds > 3600:
        s_feasible = min(s_feasible, 0.4)  # long streams rarely translate to original explainers
    t.competition = round(min(1.0, math.log10(t.view_count + 1) / 7), 3) if t.source == "youtube" else 0.4

    parts = {"view_velocity": s_velocity, "engagement": s_engagement, "search_interest": s_search,
             "freshness": s_fresh, "relevance": s_relevance, "feasibility": s_feasible}
    total = sum(weights.get(k, 0) * v for k, v in parts.items()) / max(1e-9, sum(weights.values()))
    t.score = round(100 * total, 1)
    t.score_breakdown = {**{k: round(v, 3) for k, v in parts.items()}, "search_interest_raw": s_search,
                         "weights": weights, "age_hours": round(age_h, 1)}


def suggest_ideas(db: Session, t: Trend, channel: Channel) -> list[str]:
    """Ask the LLM what made the topic work and for distinct, original angles."""
    cs = channel.settings
    system = ("You are a YouTube content strategist. You never copy other creators. Given a trending reference, "
              "explain briefly why it is performing and propose ORIGINAL video ideas with a distinct angle that adds value.")
    prompt = (f"Trending reference (for research only — do not reproduce it):\nTitle: {t.title}\nDescription: {t.description[:600]}\n"
              f"Channel niche: {t.niche}. Audience: {cs.primary_audience}. Language: {cs.language}.\n"
              'Return JSON: {"why_it_works": str, "ideas": [3 short original video titles], "keywords": [up to 6]}')
    res = llm.generate(db, task="ideas", system=system, prompt=prompt, channel_id=channel.id, expected_output_tokens=400,
                       context={"topic": t.topic, "description": t.description})
    ideas = [str(i)[:200] for i in res.data.get("ideas", [])][:3]
    t.suggested_ideas = ideas
    t.score_breakdown = {**(t.score_breakdown or {}), "why_it_works": str(res.data.get("why_it_works", ""))[:500]}
    if res.data.get("keywords"):
        t.keywords = list(dict.fromkeys([*(t.keywords or []), *[str(k) for k in res.data["keywords"]]]))[:12]
    db.commit()
    return ideas
