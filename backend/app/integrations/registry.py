"""Resolves which provider instance to use for each capability, from the ai_providers table
(with environment-variable fallbacks for keys), and seeds the default provider rows."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models import AIProvider, ModelConfiguration

# name -> (kind, display, is_paid, default model, $/1k in, $/1k out, $/unit, base_url setting)
CATALOG: list[dict] = [
    # LLMs (prices are estimates per 1k tokens; edit them in AI Configuration)
    dict(kind="llm", name="mock", display="Offline template generator (testing)", paid=False, model="mock-template-v1"),
    dict(kind="llm", name="ollama", display="Ollama (local, free)", paid=False, model="llama3.1:8b", base="ollama_base_url"),
    dict(kind="llm", name="gemini", display="Google Gemini", paid=True, model="gemini-2.5-flash", cin=0.0003, cout=0.0025, env="gemini_api_key"),
    dict(kind="llm", name="anthropic", display="Anthropic Claude", paid=True, model="claude-opus-5-5", cin=0.004, cout=0.02, env="anthropic_api_key"),
    dict(kind="llm", name="openai", display="OpenAI", paid=True, model="gpt-4.1-mini", cin=0.0004, cout=0.0016, env="openai_api_key"),
    # TTS ($ per 1k characters)
    dict(kind="tts", name="mock", display="Silent track (testing)", paid=False, model="silence"),
    dict(kind="tts", name="system", display="System voice (espeak-ng / Windows SAPI, free)", paid=False, model="default"),
    dict(kind="tts", name="kokoro", display="Kokoro TTS (self-hosted, free)", paid=False, model="af_heart", base="kokoro_base_url"),
    dict(kind="tts", name="piper", display="Piper TTS (self-hosted, free)", paid=False, model="default", base="piper_base_url"),
    dict(kind="tts", name="openai", display="OpenAI TTS", paid=True, model="gpt-4o-mini-tts", unit=0.015, env="openai_api_key"),
    # Images ($ per image)
    dict(kind="image", name="procedural", display="Procedural motion graphics (free, offline)", paid=False, model="pillow"),
    dict(kind="image", name="comfyui", display="ComfyUI / Stable Diffusion (self-hosted)", paid=False, model="workflow", base="comfyui_base_url"),
    dict(kind="image", name="openai", display="OpenAI Images", paid=True, model="gpt-image-1", unit=0.04, env="openai_api_key"),
    # Video clips ($ per clip)
    dict(kind="video", name="none", display="No AI video clips (animate stills)", paid=False, model="kenburns"),
    dict(kind="video", name="comfyui", display="ComfyUI video workflow (Wan / LTX, needs GPU)", paid=False, model="workflow", base="comfyui_base_url"),
]

DEFAULTS = {"llm": "mock", "tts": "system", "image": "procedural", "video": "none"}


def seed_providers(db: Session) -> None:
    for item in CATALOG:
        row = db.scalar(select(AIProvider).where(AIProvider.kind == item["kind"], AIProvider.name == item["name"]))
        if row:
            continue
        base = getattr(settings, item["base"], "") if item.get("base") else None
        row = AIProvider(
            kind=item["kind"], name=item["name"], display_name=item["display"], is_paid=item["paid"],
            base_url=base or None, enabled=not item["paid"], is_default=DEFAULTS[item["kind"]] == item["name"],
        )
        db.add(row)
        db.flush()
        db.add(ModelConfiguration(
            provider_id=row.id, task="default", model_name=item["model"],
            cost_per_1k_input=item.get("cin", 0.0), cost_per_1k_output=item.get("cout", 0.0), cost_per_unit=item.get("unit", 0.0),
        ))
    db.commit()


def api_key_for(row: AIProvider) -> str | None:
    key = decrypt_secret(row.api_key_enc)
    if key:
        return key
    item = next((c for c in CATALOG if c["kind"] == row.kind and c["name"] == row.name), None)
    return getattr(settings, item["env"], "") or None if item and item.get("env") else None


def model_config(db: Session, row: AIProvider, task: str = "default") -> ModelConfiguration | None:
    cfg = db.scalar(select(ModelConfiguration).where(ModelConfiguration.provider_id == row.id, ModelConfiguration.task == task))
    return cfg or db.scalar(select(ModelConfiguration).where(ModelConfiguration.provider_id == row.id, ModelConfiguration.task == "default"))


def default_provider(db: Session, kind: str) -> AIProvider:
    row = db.scalar(select(AIProvider).where(AIProvider.kind == kind, AIProvider.is_default.is_(True), AIProvider.enabled.is_(True)))
    if row is None:
        row = db.scalar(select(AIProvider).where(AIProvider.kind == kind, AIProvider.name == DEFAULTS[kind]))
    if row is None:
        seed_providers(db)
        return default_provider(db, kind)
    return row


def provider_by_name(db: Session, kind: str, name: str) -> AIProvider | None:
    return db.scalar(select(AIProvider).where(AIProvider.kind == kind, AIProvider.name == name))


def mark_health(db: Session, row: AIProvider, ok: bool, message: str) -> None:
    row.health_status = "ok" if ok else "error"
    row.health_message = message[:1000]
    row.health_checked_at = datetime.now(timezone.utc)
    db.commit()
