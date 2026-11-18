"""Agent 10: Quality Assurance. Produces a 0-100 score; any failed *critical* check rejects the video."""
from __future__ import annotations

import re
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.compliance import check_assets
from app.core.storage import storage
from app.integrations.llm import service as llm
from app.integrations.registry import default_provider
from app.models import Channel, ContentIdea, Script, Subtitle, Thumbnail, Video, VideoMetadata
from app.services.catalog import KIDS_BANNED_TERMS, LONG_RANGES
from app.services.usage import get_automation
from app.video_engine import ffmpeg

WEIGHTS = {  # contribution to the 0-100 score
    "file_integrity": 10, "codecs": 5, "aspect_ratio": 8, "duration": 8, "audio_present": 8, "loudness": 7,
    "no_black_frames": 6, "no_long_silence": 8, "subtitles": 6, "text_sanity": 5, "factual_accuracy": 10,
    "thumbnail": 5, "copyright": 6, "originality": 4, "ai_disclosure": 2, "audience": 2,
}


def run_qa(db: Session, video: Video, channel: Channel, run_id: int | None = None) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, passed: bool, detail: str, critical: bool = False, partial: float | None = None):
        checks[name] = {"passed": passed, "critical": critical, "detail": detail,
                        "score": WEIGHTS.get(name, 0) * (partial if partial is not None else (1.0 if passed else 0.0))}

    path = storage.path(video.file_path) if video.file_path else None
    if not path or not path.exists() or path.stat().st_size < 10_000:
        add("file_integrity", False, "rendered file missing or truncated", critical=True)
        return _finish(db, video, checks, channel)
    try:
        p = ffmpeg.probe(path)
        decode_err = ffmpeg.analyze(["-v", "error", "-i", str(path)])
        add("file_integrity", not decode_err.strip(), "decodes cleanly" if not decode_err.strip() else decode_err[:300], critical=True)
    except Exception as e:  # noqa: BLE001
        add("file_integrity", False, f"cannot probe: {e}", critical=True)
        return _finish(db, video, checks, channel)

    add("codecs", p.video_codec == "h264" and p.audio_codec == "aac", f"video={p.video_codec} audio={p.audio_codec}", critical=True)
    want_vertical = video.format == "short"
    ratio_ok = bool(p.width and p.height) and ((p.height > p.width) == want_vertical) and \
        abs((p.width / p.height) - (9 / 16 if want_vertical else 16 / 9)) < 0.02
    add("aspect_ratio", ratio_ok, f"{p.width}x{p.height} (expected {'9:16' if want_vertical else '16:9'})", critical=True)

    idea = db.get(ContentIdea, video.idea_id) if video.idea_id else None
    target = idea.target_duration_seconds if idea else p.duration
    if video.format == "short":
        dur_ok, crit = p.duration <= 180, p.duration > 180
        detail = f"{p.duration:.1f}s (Shorts limit 180s, target {target}s)"
    else:
        lo, hi = LONG_RANGES.get(channel.settings.long_duration_range, (180, 1200))
        dur_ok, crit = lo * 0.6 <= p.duration <= hi * 1.4, p.duration < 60
        detail = f"{p.duration:.1f}s (target range {lo}-{hi}s)"
    closeness = max(0.0, 1 - abs(p.duration - target) / max(target, 1))
    add("duration", dur_ok, detail, critical=crit, partial=0.5 + 0.5 * closeness if dur_ok else 0)

    add("audio_present", p.has_audio, "audio stream present" if p.has_audio else "no audio", critical=True)
    loud_log = ffmpeg.analyze(["-i", str(path), "-af", "ebur128=peak=true", "-vn"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", loud_log)
    lufs = float(m[-1]) if m else None
    tts = default_provider(db, "tts").name
    if lufs is None:
        add("loudness", False, "could not measure loudness")
    else:
        ok = -17.0 <= lufs <= -11.0 or tts == "mock"
        add("loudness", ok, f"integrated {lufs} LUFS (target -14)", partial=1.0 if ok else max(0.0, 1 - abs(lufs + 14) / 10))

    black = ffmpeg.analyze(["-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.08", "-an"])
    black_secs = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", black))
    add("no_black_frames", black_secs < 1.0, f"{black_secs:.2f}s of black (>=0.5s segments)", critical=black_secs > p.duration * 0.2)

    sil = ffmpeg.analyze(["-i", str(path), "-af", "silencedetect=noise=-45dB:d=3", "-vn"])
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", sil)]
    long_sil = sum(silences)
    if tts == "mock":
        add("no_long_silence", True, "mock TTS in use: narration is intentionally silent (test mode)", partial=0.5)
    else:
        add("no_long_silence", long_sil < 3, f"{long_sil:.1f}s of silence >3s — narration may be missing", critical=long_sil > p.duration * 0.3)

    sub = db.scalar(select(Subtitle).where(Subtitle.video_id == video.id))
    if sub and storage.exists(sub.path):
        srt = storage.path(sub.path).read_text(encoding="utf-8")
        ends = [_t(x) for x in re.findall(r"--> (\d\d:\d\d:\d\d,\d\d\d)", srt)]
        starts = [_t(x) for x in re.findall(r"(\d\d:\d\d:\d\d,\d\d\d) -->", srt)]
        monotonic = all(a <= b for a, b in zip(starts, starts[1:]))
        in_range = bool(ends) and ends[-1] <= p.duration + 0.5
        add("subtitles", monotonic and in_range, f"{len(starts)} cues, last ends {ends[-1] if ends else 0:.1f}s of {p.duration:.1f}s")
    else:
        add("subtitles", False, "subtitle file missing")

    script = db.get(Script, video.script_id) if video.script_id else None
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id))
    text_issues = []
    if script:
        if re.search(r"\b(\w+) \1\b", script.body, re.I):
            text_issues.append("repeated word")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]|\uFFFD", script.body):
            text_issues.append("garbled characters")
        if re.search(r"\{\{|\}\}|TODO|lorem ipsum|\[insert", script.body, re.I):
            text_issues.append("template placeholder left in script")
    if meta and (len(meta.title) > 100 or not meta.title.strip()):
        text_issues.append("title length invalid")
    add("text_sanity", not text_issues, ", ".join(text_issues) or "no placeholder/garbled text; title valid",
        critical="template placeholder left in script" in text_issues)

    # Factual accuracy: LLM compares the script to the sourced facts.
    if script and idea and idea.research_facts:
        facts = "\n".join(f"- {f['fact']}" for f in idea.research_facts[:25])
        res = llm.generate(db, task="factcheck", channel_id=channel.id, workflow_run_id=run_id, expected_output_tokens=600,
                           system="You are a strict fact-checker. Compare the script against the verified facts only.",
                           prompt=f"VERIFIED FACTS:\n{facts}\n\nSCRIPT:\n{script.body}\n\n"
                                  'List claims in the script that are NOT supported by or contradict the facts. '
                                  'Return JSON: {"issues": [{"claim": str, "problem": str, "severity": "minor|major"}], "score": 0-100}',
                           context={"script": script.body})
        issues = [i for i in res.data.get("issues", []) if isinstance(i, dict)]
        major = [i for i in issues if i.get("severity") == "major"]
        fscore = float(res.data.get("score", 70)) / 100
        add("factual_accuracy", not major, f"{len(issues)} issue(s), {len(major)} major: "
            + "; ".join(i.get("claim", "")[:80] for i in major[:3]), critical=bool(major), partial=fscore)
    else:
        add("factual_accuracy", False, "no research facts available to verify against", partial=0.3)

    thumb = db.scalar(select(Thumbnail).where(Thumbnail.video_id == video.id, Thumbnail.is_selected.is_(True)))
    if thumb and storage.exists(thumb.path):
        tp = storage.path(thumb.path)
        with Image.open(tp) as im:
            size_ok = im.size == (1280, 720)
        add("thumbnail", size_ok and tp.stat().st_size < 2_000_000, f"{im.size[0]}x{im.size[1]}, {tp.stat().st_size // 1024} KB")
    else:
        add("thumbnail", False, "no thumbnail")

    if script and script.compliance_report:
        cr = script.compliance_report
        add("originality", cr.get("passed", False), f"originality {cr.get('originality_score')}", critical=not cr.get("passed", False),
            partial=(cr.get("originality_score") or 0) / 100)
    else:
        add("originality", False, "originality check did not run", critical=True)

    assets = check_assets(db, video)
    lic = [c for c in assets["checks"] if c["name"] != "ai_disclosure"]
    add("copyright", all(c["passed"] for c in lic), "; ".join(c["detail"] for c in lic), critical=not all(c["passed"] for c in lic))
    disc = next(c for c in assets["checks"] if c["name"] == "ai_disclosure")
    add("ai_disclosure", disc["passed"], disc["detail"], critical=True)

    kids = channel.settings.made_for_kids
    aud_ok = True
    detail = "general audience"
    if kids:
        bad = [t for t in KIDS_BANNED_TERMS if script and t in script.body.lower()]
        aud_ok = bool(meta and meta.made_for_kids) and not bad
        detail = f"made-for-kids flag={'set' if meta and meta.made_for_kids else 'MISSING'}; unsuitable terms: {bad or 'none'}"
    add("audience", aud_ok, detail, critical=not aud_ok)
    return _finish(db, video, checks, channel)


def _t(s: str) -> float:
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def _finish(db: Session, video: Video, checks: dict, channel: Channel) -> dict[str, Any]:
    auto = get_automation(db)
    min_score = auto.min_quality_score if auto else 85
    score = round(sum(c["score"] for c in checks.values()) * 100 / sum(WEIGHTS.values()), 1)
    critical_failures = [k for k, c in checks.items() if c["critical"] and not c["passed"]]
    passed = not critical_failures and score >= min_score
    report = {"score": score, "min_score": min_score, "passed": passed, "critical_failures": critical_failures, "checks": checks}
    video.quality_score = score
    video.qa_report = report
    video.status = "qa_passed" if passed else "qa_failed"
    db.commit()
    return report
