"""Deterministic, offline LLM used for tests and for running the pipeline with no AI provider.

It does not "write" — it assembles structured output from the research facts it is given,
so its scripts are factual but plain. Configure Ollama/Gemini/Claude/OpenAI for real quality."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.integrations.llm.providers import LLMConfig, LLMProvider, LLMResult

HOOKS = [
    "Here's something most people never notice about {t}.",
    "{t} — explained in under a minute.",
    "Why does everyone suddenly care about {t}?",
    "Three things about {t} you probably didn't know.",
    "Stop scrolling: {t} is more surprising than it looks.",
]
CTAS = [
    "Follow for more short explainers like this.",
    "Which fact surprised you most? Tell me in the comments.",
    "Subscribe if you want part two.",
]


def _pick(seq: list[str], seed: str) -> str:
    return seq[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(seq)]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if 25 <= len(p.strip()) <= 260]


def _keywords(text: str, n: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    stop = {"that", "this", "with", "from", "have", "were", "which", "their", "about", "there", "they", "been",
            "also", "into", "more", "than", "when", "what", "your", "will", "would", "these", "those", "after"}
    freq: dict[str, int] = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:n]]


class MockLLM(LLMProvider):
    name = "mock"
    is_paid = False

    def __init__(self, cfg: LLMConfig | None = None):
        super().__init__(cfg or LLMConfig(name="mock", model="mock-template-v1"))

    def health(self):
        return True, "offline template generator (test/demo quality)"

    def generate_json(self, system: str, prompt: str, *, task: str, context: dict[str, Any]) -> LLMResult:
        handler = getattr(self, f"_{task}", None)
        data = handler(context) if handler else {}
        return LLMResult(data=data, input_tokens=len(prompt) // 4, output_tokens=200, model=self.cfg.model)

    # ----------------------------------------------------------------- tasks
    def _ideas(self, c: dict[str, Any]) -> dict[str, Any]:
        t = c.get("topic", "this topic")
        return {
            "ideas": [
                f"{t}: the 60-second explainer",
                f"The surprising history behind {t}",
                f"{t} — myths vs facts",
            ],
            "why_it_works": "High recent interest; an explainer angle adds value instead of repeating news.",
            "keywords": _keywords(t + " " + c.get("description", ""), 6),
        }

    def _research(self, c: dict[str, Any]) -> dict[str, Any]:
        facts: list[dict[str, str]] = []
        for src in c.get("sources", []):
            for s in _sentences(src.get("snippet", ""))[:3]:
                facts.append({"fact": s, "source_url": src.get("url", ""), "confidence": "medium"})
        return {
            "summary": " ".join(f["fact"] for f in facts[:4]) or f"Limited sources found for {c.get('topic')}.",
            "facts": facts[:12],
            "uncertain_claims": [],
            "angle": f"A clear, original explainer on {c.get('topic')} for {c.get('audience', 'a general audience')}.",
        }

    def _script(self, c: dict[str, Any]) -> dict[str, Any]:
        topic = c.get("topic", "this topic")
        target = float(c.get("target_seconds", 45))
        facts = [f["fact"] for f in c.get("facts", []) if f.get("fact")] or [
            f"{topic} has a longer story than most people realise.",
            f"Experts still debate several details about {topic}.",
        ]
        wps = 2.5
        budget_words = int(target * wps)
        hook = _pick(HOOKS, topic).format(t=topic)
        cta = _pick(CTAS, topic + "cta")
        scenes = [{"narration": hook, "on_screen_text": topic[:40], "visual_prompt": f"bold title card about {topic}"}]
        used = len(hook.split()) + len(cta.split())
        connectors = ["First up", "Next", "Here is the twist", "Also worth knowing", "And finally"]
        for n, f in enumerate(facts):
            # Placeholder narration built from keywords: never copies source sentences (the originality
            # agent would correctly reject verbatim copying). Real providers write proper prose.
            kws = _keywords(f, 4)
            if not kws:
                continue
            numbers = re.findall(r"\d[\d,.]*", f)[:1]
            line = f"{connectors[min(n, len(connectors) - 1)]}: {topic} and {', '.join(kws[:3])}" + (
                f" — the key number is {numbers[0]}." if numbers else ".")
            words = len(line.split())
            if used + words > budget_words and len(scenes) > 2:
                break
            scenes.append({"narration": line, "on_screen_text": " ".join(kws[:2]).title()[:40],
                           "visual_prompt": f"illustration of {' '.join(kws[:3])}, {topic}"})
            used += words
        scenes.append({"narration": cta, "on_screen_text": "Follow for more", "visual_prompt": "clean end card with subscribe icon"})
        body = " ".join(s["narration"] for s in scenes)
        return {
            "title": f"{topic}: what you should know"[:95],
            "hook": hook,
            "cta": cta,
            "scenes": scenes,
            "music": "calm ambient pad",
            "estimated_seconds": round(len(body.split()) / wps, 1),
        }

    def _seo(self, c: dict[str, Any]) -> dict[str, Any]:
        topic = c.get("topic", "Video")
        kws = _keywords(c.get("script", "") + " " + topic, 10)
        tags = [topic.lower()] + kws[:9]
        hashtags = ["#" + re.sub(r"[^A-Za-z0-9]", "", topic.title())[:28]] + ["#" + k for k in kws[:2]]
        if c.get("format") == "short":
            hashtags.append("#Shorts")
        summary = " ".join(c.get("script", "").split()[:45])
        return {
            "title": c.get("title") or f"{topic} explained",
            "description": f"{summary}…\n\nSources are listed below. This video uses AI-generated narration and visuals.",
            "tags": tags,
            "hashtags": hashtags[:5],
            "thumbnail_text": " ".join(topic.split()[:4]).upper(),
            "thumbnail_prompt": f"bold minimal thumbnail about {topic}",
        }

    def _factcheck(self, c: dict[str, Any]) -> dict[str, Any]:
        return {"issues": [], "verdict": "no checkable issues found by offline checker", "score": 80}
