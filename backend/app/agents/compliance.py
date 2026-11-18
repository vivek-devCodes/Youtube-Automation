"""Agent 4: Copyright & Originality. Mandatory gate — a failed check stops the workflow.

Script checks: n-gram overlap against the trend reference, research sources (catches copying source
prose verbatim) and the channel's own previous scripts (catches repetitive mass-produced output),
plus trademark/franchise and child-safety screens.
Asset checks: every asset in the video must carry a provenance + licence record of an allowed type."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (AssetLicense, Channel, ContentIdea, MediaAsset, ResearchSource, Scene, Script, Trend, Video,
                        VideoMetadata, Voiceover)
from app.services.catalog import DEFAULT_TRADEMARK_BLOCKLIST, KIDS_BANNED_TERMS, NICHE_BY_SLUG
from app.services.usage import get_automation

ALLOWED_LICENSES = {"ai_generated", "procedural_generated", "stock_licensed", "public_domain", "user_owned",
                    "licensed_third_party"}
EMBED_DIM = 384


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower(), re.U)


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    w = _words(text)
    return {tuple(w[i : i + n]) for i in range(max(0, len(w) - n + 1))}


def containment(candidate: str, reference: str, n: int = 5) -> float:
    """Share of the candidate's n-grams that also appear in the reference (0..1)."""
    a, b = shingles(candidate, n), shingles(reference, n)
    return len(a & b) / len(a) if a and b else 0.0


def embed(text: str) -> list[float]:
    """Feature-hashed bag of words/bigrams, L2-normalised. Cheap, deterministic, stored in pgvector."""
    vec = [0.0] * EMBED_DIM
    w = _words(text)
    for tok in w + [f"{a}_{b}" for a, b in zip(w, w[1:])]:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % EMBED_DIM] += 1.0 if (h >> 9) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 5) for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _term_hits(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return [t for t in terms if re.search(rf"(?<!\w){re.escape(t.lower())}(?!\w)", low)]


def check_script(db: Session, script: Script, idea: ContentIdea, channel: Channel) -> dict[str, Any]:
    auto = get_automation(db)
    max_sim = auto.max_similarity if auto else 0.35
    blocklist = list(dict.fromkeys(DEFAULT_TRADEMARK_BLOCKLIST + ((auto.trademark_blocklist if auto else None) or [])))
    scenes = db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all()
    full = script.body + " " + " ".join(s.visual_prompt + " " + s.on_screen_text for s in scenes)
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str, critical: bool = True, value: float | None = None):
        checks.append({"name": name, "passed": passed, "critical": critical, "detail": detail, "value": value})

    # 1. Reference (trending video/article) similarity
    trend = db.get(Trend, idea.trend_id) if idea.trend_id else None
    ref = f"{trend.title} {trend.description}" if trend else ""
    sim_ref = containment(script.body, ref, 4) if ref else 0.0
    add("reference_similarity", sim_ref <= max_sim, f"{sim_ref:.0%} of 4-grams shared with the trending reference", value=sim_ref)

    # 2. Research-source verbatim copying
    srcs = db.scalars(select(ResearchSource).where(ResearchSource.idea_id == idea.id)).all()
    sim_src = max((containment(script.body, s.snippet, 6) for s in srcs), default=0.0)
    add("source_verbatim_copy", sim_src <= max_sim, f"max {sim_src:.0%} of 6-grams copied from a single research source", value=sim_src)

    # 3. Repetitiveness vs this channel's previous scripts (inauthentic / mass-produced content policy)
    vec = embed(script.body)
    script.embedding = vec
    prev = db.scalars(
        select(Script).join(ContentIdea, ContentIdea.id == Script.idea_id)
        .where(ContentIdea.channel_id == channel.id, Script.id != script.id, Script.idea_id != idea.id, Script.embedding.is_not(None))
        .order_by(Script.id.desc()).limit(200)
    ).all()
    sim_prev = max((cosine(vec, p.embedding) for p in prev if p.embedding), default=0.0)
    tmpl_prev = max((containment(script.body, p.body, 5) for p in prev[:50]), default=0.0)
    add("not_repetitive", sim_prev < 0.92 and tmpl_prev < 0.30,
        f"closest previous script: cosine {sim_prev:.2f}, shared 5-grams {tmpl_prev:.0%}", value=max(sim_prev, tmpl_prev))

    # 4. Trademark / franchise imitation
    hits = _term_hits(full, blocklist)
    add("no_trademark_misuse", not hits, f"protected names found: {', '.join(hits)}" if hits else "none found")

    # 5. Child safety
    kids = channel.settings.made_for_kids or any(NICHE_BY_SLUG.get(n.slug, (0, 0, 0, False))[3] for n in channel.niches)
    if kids:
        bad = _term_hits(full, KIDS_BANNED_TERMS)
        add("child_safe_language", not bad, f"unsuitable terms: {', '.join(bad)}" if bad else "ok")

    # 6. Facts must be sourced
    add("research_backed", bool(idea.research_facts), f"{len(idea.research_facts)} sourced facts available", critical=False)

    originality = round(100 * (1 - max(sim_ref, sim_src, tmpl_prev)), 1)
    passed = all(c["passed"] for c in checks if c["critical"])
    report = {"stage": "script", "passed": passed, "originality_score": originality, "checks": checks}
    script.originality_score = originality
    script.max_similarity = round(max(sim_ref, sim_src, sim_prev), 3)
    script.compliance_report = report
    db.commit()
    return report


def check_assets(db: Session, video: Video) -> dict[str, Any]:
    """Asset provenance: every asset used must have a verified, allowed licence record."""
    checks: list[dict[str, Any]] = []
    assets = db.scalars(select(MediaAsset).where(MediaAsset.video_id == video.id)).all()
    problems = []
    for a in assets:
        lic = db.scalar(select(AssetLicense).where(AssetLicense.asset_id == a.id))
        if lic is None:
            problems.append(f"asset {a.id} ({a.kind}) has no licence record")
        elif lic.license_type not in ALLOWED_LICENSES:
            problems.append(f"asset {a.id} licence '{lic.license_type}' not allowed")
        elif not lic.verified:
            problems.append(f"asset {a.id} licence not verified")
    checks.append({"name": "asset_licences", "passed": not problems, "critical": True,
                   "detail": "; ".join(problems) or f"{len(assets)} assets with verified provenance"})
    voices = db.scalars(select(Voiceover).where(Voiceover.script_id == video.script_id)).all()
    vo_ok = all(v.license_note for v in voices) and bool(voices)
    checks.append({"name": "voice_licence", "passed": vo_ok, "critical": True,
                   "detail": f"{len(voices)} voice tracks; providers: {sorted({v.provider for v in voices})}"})
    music = [a for a in assets if a.kind == "music"]
    checks.append({"name": "music_licence", "passed": all(m.provider in ("ffmpeg_synth", "user_upload", "stock") for m in music),
                   "critical": True, "detail": "original synthesised music" if music else "no music track"})
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id))
    disclosed = bool(meta and meta.contains_synthetic_media)
    checks.append({"name": "ai_disclosure", "passed": disclosed, "critical": True,
                   "detail": "containsSyntheticMedia will be set on upload" if disclosed else "disclosure flag missing"})
    return {"stage": "assets", "passed": all(c["passed"] for c in checks if c["critical"]), "checks": checks}
