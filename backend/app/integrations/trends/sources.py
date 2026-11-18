"""Permitted public trend + research sources. No scraping of restricted YouTube pages."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, quote_plus

import feedparser
import httpx

log = logging.getLogger(__name__)
from app.core.config import settings

# Wikimedia's robot policy (https://w.wiki/4wJS) requires a contact URL/email and rejects anonymous clients.
UA = {"User-Agent": f"AIYouTubeStudio/1.0 ({settings.research_contact or settings.public_base_url}) httpx/{httpx.__version__}"}


@dataclass
class TrendItem:
    source: str
    external_id: str
    topic: str
    title: str
    description: str = ""
    source_channel: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    category_id: str | None = None
    language: str | None = None
    region: str | None = None
    duration_seconds: int | None = None
    view_count: int = 0
    like_count: int | None = None
    comment_count: int | None = None
    search_interest: float = 0.0  # 0..1
    keywords: list[str] = field(default_factory=list)


def _iso_duration(d: str | None) -> int | None:
    if not d:
        return None
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return None
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def from_youtube_video(v: dict, region: str) -> TrendItem:
    sn, st = v.get("snippet", {}), v.get("statistics", {})
    pub = sn.get("publishedAt")
    return TrendItem(
        source="youtube", external_id=v["id"], topic=sn.get("title", "")[:300], title=sn.get("title", ""),
        description=(sn.get("description") or "")[:2000], source_channel=sn.get("channelTitle"),
        source_url=f"https://www.youtube.com/watch?v={v['id']}",
        published_at=datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None,
        category_id=sn.get("categoryId"), language=sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
        region=region, duration_seconds=_iso_duration(v.get("contentDetails", {}).get("duration")),
        view_count=int(st.get("viewCount", 0)),
        like_count=int(st["likeCount"]) if "likeCount" in st else None,
        comment_count=int(st["commentCount"]) if "commentCount" in st else None,
        keywords=(sn.get("tags") or [])[:10],
    )


def _traffic(s: str) -> int:
    s = s.replace(",", "").replace("+", "").strip().upper()
    mult = 1000 if s.endswith("K") else 1_000_000 if s.endswith("M") else 1
    try:
        return int(float(s.rstrip("KM")) * mult)
    except ValueError:
        return 0


def google_trends_daily(geo: str) -> list[TrendItem]:
    """Google Trends 'Trending now' public RSS feed."""
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("google trends feed failed: %s", e)
        return []
    feed = feedparser.parse(r.content)
    items = []
    max_traffic = 1
    parsed = []
    for e in feed.entries:
        traffic = _traffic(e.get("ht_approx_traffic", "0"))
        max_traffic = max(max_traffic, traffic)
        parsed.append((e, traffic))
    for e, traffic in parsed:
        title = e.get("title", "").strip()
        if not title:
            continue
        news_title = e.get("ht_news_item_title", "")
        news_url = e.get("ht_news_item_url")
        pub = None
        if e.get("published"):
            try:
                pub = parsedate_to_datetime(e.published)
            except (TypeError, ValueError):
                pub = None
        items.append(TrendItem(
            source="google_trends", external_id=f"{geo}:{title.lower()}:{(pub or datetime.now(timezone.utc)).date()}",
            topic=title, title=title, description=news_title, source_url=news_url, published_at=pub, region=geo,
            search_interest=min(1.0, traffic / max_traffic), view_count=traffic,
        ))
    return items


def google_news(query: str, lang: str = "en", country: str = "IN", limit: int = 8) -> list[dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("google news failed: %s", e)
        return []
    out = []
    for e in feedparser.parse(r.content).entries[:limit]:
        pub = None
        try:
            pub = parsedate_to_datetime(e.published) if e.get("published") else None
        except (TypeError, ValueError):
            pass
        summary = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
        out.append({"url": e.get("link"), "title": e.get("title", ""), "publisher": e.get("source", {}).get("title", ""),
                    "snippet": re.sub(r"\s+", " ", summary).strip()[:600], "published_at": pub, "reliability": "medium"})
    return out


def news_trends(query: str, lang: str, country: str) -> list[TrendItem]:
    items = []
    for n in google_news(query, lang, country, limit=10):
        if not n.get("url"):
            continue
        age_h = max(1.0, (datetime.now(timezone.utc) - n["published_at"]).total_seconds() / 3600) if n.get("published_at") else 48
        if age_h > 72:
            continue
        title = re.sub(r"\s+-\s+[^-]+$", "", n["title"])  # strip " - Publisher"
        items.append(TrendItem(
            source="news", external_id=hashlib.sha1(n["url"].encode()).hexdigest(), topic=title[:300], title=title,
            description=n["snippet"], source_channel=n["publisher"], source_url=n["url"], published_at=n.get("published_at"),
            region=country, language=lang, search_interest=0.4,
        ))
    return items


def wikipedia_sources(query: str, lang: str = "en", limit: int = 3) -> list[dict[str, Any]]:
    wl = lang if lang in {"en", "hi", "mr", "gu", "ta", "te", "kn", "ml", "bn", "es", "fr", "ar"} else "en"
    base = f"https://{wl}.wikipedia.org"
    try:
        r = httpx.get(f"{base}/w/api.php", headers=UA, timeout=20, params={
            "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit})
        r.raise_for_status()
        titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
    except (httpx.HTTPError, ValueError) as e:
        log.warning("wikipedia search failed: %s", e)
        return []
    out = []
    for t in titles:
        try:
            s = httpx.get(f"{base}/api/rest_v1/page/summary/{quote(t.replace(' ', '_'), safe='')}", headers=UA, timeout=20)
            if s.status_code != 200:
                continue
            j = s.json()
            if j.get("type") == "disambiguation":
                continue
            out.append({"url": j.get("content_urls", {}).get("desktop", {}).get("page", f"{base}/wiki/{t}"),
                        "title": j.get("title", t), "publisher": "Wikipedia", "snippet": j.get("extract", "")[:1500],
                        "published_at": None, "reliability": "medium"})
        except (httpx.HTTPError, ValueError):
            continue
    return out


# Offline seed topics per niche (used by the mock source and as evergreen fallbacks).
EVERGREEN = {
    "science-technology": ["How GPS knows where you are", "Why the sky is blue", "How batteries store energy"],
    "artificial-intelligence": ["How large language models work", "What is a neural network", "AI image generation explained"],
    "education": ["The Pomodoro technique", "How memory works", "Why we procrastinate"],
    "facts-stories": ["The Great Emu War", "Why Venice was built on water", "The history of the zipper"],
    "history": ["The Indus Valley Civilisation", "How the printing press changed the world", "The Silk Road"],
    "cricket": ["How the Duckworth-Lewis-Stern method works", "Why cricket balls swing", "The history of the Ashes"],
    "football": ["How the offside rule works", "The history of the World Cup", "Why penalty shootouts are so hard"],
    "finance-education": ["How compound interest works", "What is an index fund", "How inflation affects savings"],
    "motivation": ["The two-minute rule for habits", "Why small wins matter", "How athletes handle pressure"],
    "nursery-rhymes": ["Counting stars from one to ten", "Colours of the rainbow song", "Brushing teeth morning song"],
    "childrens-entertainment": ["A friendly cloud learns to rain", "The tortoise who loved maps", "Shapes around the house"],
}


def mock_trends(niche: str, region: str) -> list[TrendItem]:
    topics = EVERGREEN.get(niche) or EVERGREEN["facts-stories"]
    now = datetime.now(timezone.utc)
    return [
        TrendItem(source="mock", external_id=f"mock:{niche}:{t}", topic=t, title=t, description=f"Evergreen topic in {niche}",
                  published_at=now - timedelta(hours=6 * (i + 1)), region=region, view_count=50000 // (i + 1),
                  search_interest=0.6 - 0.1 * i)
        for i, t in enumerate(topics)
    ]
