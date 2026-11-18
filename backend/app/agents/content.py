"""Agent 3 (Content Research), Agent 5 (Scriptwriting) and Agent 6 (SEO & Metadata)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import StudioError
from app.integrations.llm import service as llm
from app.integrations.trends import sources
from app.models import Channel, ContentIdea, ResearchSource, Scene, Script, Trend, Video, VideoMetadata
from app.services.catalog import LANGUAGES, NICHE_BY_SLUG, YOUTUBE_LANG
from app.services.usage import get_automation

log = logging.getLogger(__name__)
TIME_SENSITIVE = {"cricket", "football", "sports", "entertainment-news", "gaming", "business", "finance-education"}
WPS = {"en": 2.5, "hinglish": 2.4, "hi": 2.3}  # narration words/second


def words_per_second(lang: str) -> float:
    return WPS.get(lang, 2.2)


# ===================================================================== Agent 3
def research(db: Session, idea: ContentIdea, channel: Channel, run_id: int | None = None) -> dict:
    lang = channel.settings.language
    wl = "hi" if lang in ("hi", "hinglish") else lang
    query = idea.title
    trend = db.get(Trend, idea.trend_id) if idea.trend_id else None
    if trend and trend.topic and trend.topic != idea.title:
        query = trend.topic
    found = sources.wikipedia_sources(query, "en" if wl not in ("hi", "en") else wl, limit=3)
    if wl != "en" and not found:
        found = sources.wikipedia_sources(query, "en", limit=3)
    niche = trend.niche if trend else ""
    time_sensitive = niche in TIME_SENSITIVE or (trend is not None and trend.source in ("news", "google_trends"))
    if time_sensitive:
        found += sources.google_news(query, "en", channel.settings.target_country, limit=6)

    db.execute(delete(ResearchSource).where(ResearchSource.idea_id == idea.id))
    for s in found:
        db.add(ResearchSource(idea_id=idea.id, url=s["url"][:800], title=s["title"][:500], publisher=s["publisher"][:200],
                              snippet=s["snippet"], reliability=s["reliability"], published_at=s.get("published_at")))
    db.flush()
    src_text = "\n\n".join(
        f"[{i + 1}] {s['title']} — {s['publisher']} ({s['published_at'].date() if s.get('published_at') else 'undated'})\n"
        f"URL: {s['url']}\n{s['snippet'][:1200]}" for i, s in enumerate(found)
    ) or "(no external sources were found)"
    today = datetime.now(timezone.utc).date().isoformat()
    system = ("You are a meticulous research assistant for an educational video channel. Use ONLY the provided sources. "
              "Separate verified facts from speculation. Flag claims that conflict between sources or are unconfirmed. "
              "Never invent statistics, dates or quotes.")
    prompt = (f"Today is {today}. Topic: {query}\nAudience: {channel.settings.primary_audience}\n"
              f"{'This is time-sensitive (news/sports): verify dates and results, and exclude unconfirmed reports.' if time_sensitive else ''}\n\n"
              f"SOURCES:\n{src_text}\n\n"
              'Return JSON: {"summary": str, "facts": [{"fact": str, "source_url": str, "confidence": "high|medium|low"}], '
              '"uncertain_claims": [str], "angle": str (a distinctive original angle for our video)}')
    res = llm.generate(db, task="research", system=system, prompt=prompt, channel_id=channel.id, workflow_run_id=run_id,
                       expected_output_tokens=1500, context={"topic": query, "sources": found,
                                                             "audience": channel.settings.primary_audience})
    urls = {s["url"] for s in found}
    facts = [f for f in res.data.get("facts", []) if isinstance(f, dict) and f.get("fact")]
    for f in facts:  # facts must trace to a real source we fetched
        if f.get("source_url") not in urls:
            f["confidence"] = "low"
            f["unsourced"] = True
    usable = [f for f in facts if not f.get("unsourced") and f.get("confidence") != "low"]
    if not usable and not found:
        raise StudioError(f"No reliable sources found for '{query}' — topic skipped", retryable=False)
    idea.research_summary = str(res.data.get("summary", ""))[:5000]
    idea.research_facts = usable or facts
    if res.data.get("angle") and not idea.angle:
        idea.angle = str(res.data["angle"])[:1000]
    db.commit()
    return {"sources": len(found), "facts": len(idea.research_facts), "uncertain": res.data.get("uncertain_claims", [])[:10],
            "provider": res.data.get("_provider")}


# ===================================================================== Agent 5
def write_script(db: Session, idea: ContentIdea, channel: Channel, run_id: int | None = None) -> Script:
    cs = channel.settings
    lang = cs.language
    wps = words_per_second(lang)
    target = idea.target_duration_seconds
    words = int(target * wps)
    auto = get_automation(db)
    insights = (auto.optimization_insights if auto else {}) or {}
    previous = db.scalars(
        select(Script.hook).join(ContentIdea, ContentIdea.id == Script.idea_id)
        .where(ContentIdea.channel_id == channel.id, Script.idea_id != idea.id).order_by(Script.id.desc()).limit(8)
    ).all()
    kids = cs.made_for_kids or any(NICHE_BY_SLUG.get(n.slug, (0, 0, 0, False))[3] for n in channel.niches)
    structure = (
        "SHORT FORMAT: 1) hook in the first 1-3 seconds, 2) main content with curiosity, 3) retention beats, "
        "4) deliver the promised value, 5) brief natural CTA."
        if idea.format == "short" else
        "LONG FORMAT: strong opening, introduction, 3-6 main sections with facts and examples, storytelling, conclusion, natural CTA."
    )
    lang_rule = {"hinglish": "Write in Hinglish (Hindi in Latin script mixed with common English words)."}.get(
        lang, f"Write narration in {LANGUAGES.get(lang, 'English')}.")
    system = (
        "You are a scriptwriter for an original faceless YouTube channel. Write COMPLETELY ORIGINAL scripts: "
        "never reproduce another creator's transcript, article or phrasing; paraphrase research in your own voice. "
        "Use only facts supplied in the research. No misleading clickbait, no exaggerated claims. "
        "Each scene's visual prompt must describe ORIGINAL artwork: no real people's likeness, logos, brands or copyrighted characters."
        + (" CHILD-SAFE: gentle, age-appropriate language and visuals; no violence, fear, or commercial pressure; "
           "original characters only." if kids else "")
    )
    facts = "\n".join(f"- {f['fact']} (source: {f.get('source_url', '')})" for f in idea.research_facts[:20])
    prompt = (
        f"Video idea: {idea.title}\nAngle: {idea.angle}\nAudience: {cs.primary_audience}\nStyle: {cs.content_style}, visuals: {cs.visual_style}\n"
        f"{lang_rule}\nTarget length: ~{target}s (~{words} words of narration total).\n{structure}\n"
        f"Avoid reusing these previous hooks: {previous}\n"
        f"What has worked on this channel: {insights.get('summary', 'no data yet')}\n\nRESEARCH FACTS:\n{facts}\n\n"
        'Return JSON: {"title": str (<=90 chars), "hook": str, "cta": str, "music": str (mood), '
        '"scenes": [{"narration": str, "on_screen_text": str (<=6 words), "visual_prompt": str}], "estimated_seconds": number}. '
        "The hook is the first scene's narration and the CTA is the last scene's narration."
    )
    res = llm.generate(db, task="script", system=system, prompt=prompt, channel_id=channel.id, workflow_run_id=run_id,
                       expected_output_tokens=max(1500, words * 3),
                       context={"topic": idea.title, "facts": idea.research_facts, "target_seconds": target,
                                "format": idea.format, "language": lang})
    d = res.data
    scenes = [s for s in d.get("scenes", []) if isinstance(s, dict) and str(s.get("narration", "")).strip()]
    if len(scenes) < 2:
        raise StudioError("Script generation returned fewer than 2 scenes", retryable=True)
    version = (db.scalar(select(Script.version).where(Script.idea_id == idea.id).order_by(Script.version.desc()).limit(1)) or 0) + 1
    body = " ".join(str(s["narration"]).strip() for s in scenes)
    script = Script(
        idea_id=idea.id, version=version, title=str(d.get("title") or idea.title)[:300], hook=str(d.get("hook", scenes[0]["narration"])),
        body=body, cta=str(d.get("cta", "")), language=lang, music_suggestion=str(d.get("music", ""))[:200],
        estimated_duration_seconds=round(len(body.split()) / wps, 1), llm_provider=d.get("_provider", ""), llm_model=d.get("_model", ""),
    )
    db.add(script)
    db.flush()
    for i, s in enumerate(scenes):
        narr = str(s["narration"]).strip()
        db.add(Scene(script_id=script.id, idx=i, narration=narr, on_screen_text=str(s.get("on_screen_text", ""))[:200],
                     visual_prompt=str(s.get("visual_prompt", ""))[:2000], estimated_seconds=round(len(narr.split()) / wps, 1)))
    db.commit()
    db.refresh(script)
    return script


# ===================================================================== Agent 6
HASHTAG_RE = re.compile(r"[^\w]", re.U)


def generate_metadata(db: Session, video: Video, script: Script, idea: ContentIdea, channel: Channel,
                      run_id: int | None = None) -> VideoMetadata:
    cs = channel.settings
    srcs = db.scalars(select(ResearchSource).where(ResearchSource.idea_id == idea.id)).all()
    system = ("You are a YouTube SEO specialist. Write accurate, specific metadata. No keyword stuffing, no unrelated "
              "trending hashtags, no misleading clickbait. Thumbnail text must reflect what the video actually delivers.")
    prompt = (f"Video script:\n{script.body[:4000]}\n\nFormat: {idea.format}. Language: {LANGUAGES.get(cs.language)}.\n"
              'Return JSON: {"title": str (<=90 chars), "description": str (2-4 short paragraphs), "tags": [<=12 str], '
              '"hashtags": [<=3 str starting with #], "thumbnail_text": str (<=4 words), "thumbnail_prompt": str}')
    res = llm.generate(db, task="seo", system=system, prompt=prompt, channel_id=channel.id, workflow_run_id=run_id,
                       expected_output_tokens=800, context={"topic": idea.title, "script": script.body, "format": idea.format,
                                                            "title": script.title})
    d = res.data
    corpus = (script.body + " " + idea.title).lower()

    def clean(s: str) -> str:
        return s.replace("<", "").replace(">", "").strip()

    title = clean(str(d.get("title") or script.title))[:100]
    # Keep only hashtags whose words actually relate to the content (prevents unrelated trend-jacking).
    hashtags = []
    for h in d.get("hashtags", []):
        word = HASHTAG_RE.sub("", str(h))
        if word and (word.lower() in corpus.replace(" ", "") or word.lower() == "shorts"):
            hashtags.append("#" + word)
    if idea.format == "short" and "#Shorts" not in hashtags:
        hashtags.append("#Shorts")
    tags, total = [], 0
    for t in d.get("tags", []):
        t = clean(str(t)).replace(",", " ")[:60]
        if t and total + len(t) + 2 <= 480:
            tags.append(t)
            total += len(t) + 2
    desc = clean(str(d.get("description", "")))
    sources_txt = "\n".join(f"• {s.title or s.publisher}: {s.url}" for s in srcs[:8])
    desc = (f"{desc}\n\n{' '.join(hashtags[:3])}\n\nSources:\n{sources_txt or '• Original analysis'}\n\n"
            "Narration and visuals in this video were created with AI tools and reviewed for accuracy.")[:4900]
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id)) or VideoMetadata(video_id=video.id)
    meta.title = title
    meta.description = desc
    meta.tags = tags
    meta.hashtags = hashtags[:5]
    meta.category_id = cs.youtube_category_id
    meta.language = YOUTUBE_LANG.get(cs.language, cs.language)
    meta.made_for_kids = cs.made_for_kids
    meta.contains_synthetic_media = True
    meta.privacy_status = "private"
    meta.thumbnail_text = clean(str(d.get("thumbnail_text") or idea.title))[:60]
    meta.thumbnail_prompt = str(d.get("thumbnail_prompt", ""))[:2000]
    db.add(meta)
    db.commit()
    return meta
