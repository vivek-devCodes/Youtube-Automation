from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, require, to_dict
from app.core.config import settings
from app.core.security import decrypt_secret
from app.core.storage import storage
from app.database.session import get_db
from app.integrations.youtube.client import build_auth_url, revoke
from app.models import Channel, User
from app.services.audit import audit
from app.services.catalog import LANGUAGES
from app.services.channels import ensure_children, set_niches

router = APIRouter(prefix="/channels", tags=["channels"])


def channel_out(ch: Channel) -> dict:
    d = to_dict(ch)
    d["settings"] = to_dict(ch.settings) if ch.settings else None
    d["brand"] = to_dict(ch.brand) if ch.brand else None
    d["niches"] = [to_dict(n) for n in ch.niches]
    d["authorized"] = bool(ch.oauth_token_enc) or ch.is_sandbox
    return d


@router.get("")
def list_channels(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    return [channel_out(c) for c in db.scalars(select(Channel).order_by(Channel.id)).all()]


class ConnectBody(BaseModel):
    mode: str = Field(pattern="^(google|sandbox)$")
    title: str = "My Sandbox Channel"


@router.post("/connect")
def connect(body: ConnectBody, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    """google → returns the OAuth consent URL. sandbox → creates a local practice channel that never touches YouTube."""
    if body.mode == "google":
        if not settings.google_oauth_configured:
            raise HTTPException(400, "Google OAuth is not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env "
                                     "(see docs/SETUP_GOOGLE.md), then restart the backend.")
        return {"auth_url": build_auth_url(user.id)}
    ch = Channel(user_id=user.id, title=body.title[:200], is_sandbox=True, status="connected")
    ensure_children(db, ch)
    db.add(ch)
    db.flush()
    audit(db, "channel.sandbox_create", user_id=user.id, entity_type="channel", entity_id=ch.id)
    db.commit()
    return channel_out(ch)


@router.get("/{channel_id}")
def get_channel(channel_id: int, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    return channel_out(get_or_404(db, Channel, channel_id))


class ChannelPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    automation_enabled: bool | None = None
    settings: dict | None = None
    brand: dict | None = None
    niches: list[str] | None = None
    custom_niches: list[dict] | None = None


SETTINGS_FIELDS = {
    "target_country", "primary_audience", "language", "voiceover_language", "subtitle_languages", "youtube_category_id",
    "content_style", "visual_style", "voice_style", "background_music", "burn_subtitles", "made_for_kids",
    "short_duration_seconds", "long_duration_range", "shorts_per_day", "long_per_week", "publish_times", "timezone",
    "require_approval", "auto_publish", "default_privacy", "video_quality",
}
BRAND_FIELDS = {"brand_name", "tagline", "primary_color", "secondary_color", "brand_identity"}


@router.patch("/{channel_id}")
def update_channel(channel_id: int, body: ChannelPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo

    ch = ensure_children(db, get_or_404(db, Channel, channel_id))
    if body.title is not None:
        ch.title = body.title[:200]
    if body.description is not None:
        ch.description = body.description
    if body.automation_enabled is not None:
        ch.automation_enabled = body.automation_enabled
    if body.settings:
        s = body.settings
        if "language" in s and s["language"] not in LANGUAGES:
            raise HTTPException(400, "unsupported language")
        if "timezone" in s:
            try:
                ZoneInfo(s["timezone"])
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, "invalid timezone") from e
        if "publish_times" in s:
            for t in s["publish_times"]:
                hh, _, mm = str(t).partition(":")
                if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                    raise HTTPException(400, f"invalid publish time {t}")
        if s.get("short_duration_seconds") and int(s["short_duration_seconds"]) > 180:
            raise HTTPException(400, "Shorts can be at most 180 seconds")
        for k, v in s.items():
            if k in SETTINGS_FIELDS:
                setattr(ch.settings, k, v)
        if ch.settings.auto_publish and ch.settings.require_approval:
            ch.settings.auto_publish = False  # approval wins; auto publishing needs approval switched off explicitly
    if body.brand:
        for k, v in body.brand.items():
            if k in BRAND_FIELDS:
                setattr(ch.brand, k, v)
    if body.niches is not None or body.custom_niches is not None:
        set_niches(db, ch, body.niches or [n.slug for n in ch.niches if not n.is_custom], body.custom_niches)
    audit(db, "channel.update", user_id=user.id, entity_type="channel", entity_id=ch.id,
          detail=json.loads(body.model_dump_json(exclude_none=True)))
    db.commit()
    db.refresh(ch)
    return channel_out(ch)


@router.post("/{channel_id}/brand/{asset}")
async def upload_brand_asset(channel_id: int, asset: str, file: UploadFile = File(...),
                             user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if asset not in ("logo", "banner"):
        raise HTTPException(400, "asset must be logo or banner")
    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(400, "PNG, JPEG or WebP only")
    data = await file.read()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(400, "max 6 MB")
    ch = ensure_children(db, get_or_404(db, Channel, channel_id))
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[file.content_type]
    key = f"channels/{ch.id}/{asset}.{ext}"
    storage.path(key).write_bytes(data)
    setattr(ch.brand, f"{asset}_path", key)
    db.commit()
    return {"path": key}


@router.delete("/{channel_id}")
def disconnect(channel_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    """Disconnect: revoke Google tokens and stop automation. Content history is kept."""
    ch = get_or_404(db, Channel, channel_id)
    raw = decrypt_secret(ch.oauth_token_enc)
    if raw:
        tok = json.loads(raw)
        revoke(tok.get("refresh_token") or tok.get("access_token", ""))
    ch.oauth_token_enc = None
    ch.status = "disconnected"
    ch.automation_enabled = False
    audit(db, "channel.disconnect", user_id=user.id, entity_type="channel", entity_id=ch.id)
    db.commit()
    return channel_out(ch)
