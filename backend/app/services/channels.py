from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import encrypt_secret
from app.integrations.youtube import client as yt
from app.models import Channel, ChannelBrand, ChannelSettings, Niche
from app.services import usage
from app.services.catalog import NICHE_BY_SLUG


def ensure_children(db: Session, ch: Channel) -> Channel:
    if not ch.settings:
        ch.settings = ChannelSettings()
    if not ch.brand:
        ch.brand = ChannelBrand(brand_name=ch.title)
    return ch


def connect_from_oauth(db: Session, user_id: int, code: str) -> list[Channel]:
    tok = yt.exchange_code(code)
    enc = encrypt_secret(json.dumps(tok))
    store = yt.TokenStore(enc, lambda _: None)
    client = yt.YouTubeClient(token_store=store, charge=lambda u, op: usage.charge_youtube_quota(db, u, op, settings.youtube_daily_quota))
    out = []
    for item in client.my_channels():
        sn, st = item.get("snippet", {}), item.get("statistics", {})
        ch = db.scalar(select(Channel).where(Channel.youtube_channel_id == item["id"]))
        if ch is None:
            ch = Channel(user_id=user_id, youtube_channel_id=item["id"], title=sn.get("title", "My channel"))
            db.add(ch)
        ch.title = sn.get("title", ch.title)
        ch.handle = sn.get("customUrl")
        ch.description = sn.get("description", "")
        ch.thumbnail_url = (sn.get("thumbnails", {}).get("default") or {}).get("url")
        ch.subscriber_count = int(st.get("subscriberCount", 0))
        ch.view_count = int(st.get("viewCount", 0))
        ch.video_count = int(st.get("videoCount", 0))
        ch.oauth_token_enc = enc
        ch.token_expires_at = datetime.fromisoformat(tok["expires_at"])
        ch.scopes = tok.get("scope", "").split()
        ch.status = "connected"
        ch.is_sandbox = False
        ensure_children(db, ch)
        out.append(ch)
    db.commit()
    return out


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80] or "custom"


def set_niches(db: Session, ch: Channel, slugs: list[str], custom: list[dict] | None = None) -> None:
    keep = set()
    for slug in slugs:
        if slug not in NICHE_BY_SLUG:
            continue
        _, name, cat, kids, kws = NICHE_BY_SLUG[slug]
        keep.add(slug)
        if not any(n.slug == slug for n in ch.niches):
            ch.niches.append(Niche(slug=slug, name=name, youtube_category_id=cat, is_kids=kids, keywords=kws))
    for c in custom or []:
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        slug = slugify(name)
        keep.add(slug)
        existing = next((n for n in ch.niches if n.slug == slug), None)
        kws = [k.strip() for k in c.get("keywords", []) if str(k).strip()] or [name]
        if existing:
            existing.keywords = kws
        else:
            ch.niches.append(Niche(slug=slug, name=name, is_custom=True, keywords=kws, youtube_category_id=c.get("category_id")))
    ch.niches[:] = [n for n in ch.niches if n.slug in keep]
    if ch.settings and ch.niches:
        first = ch.niches[0]
        ch.settings.youtube_category_id = first.youtube_category_id or ch.settings.youtube_category_id
        if any(n.is_kids for n in ch.niches):
            ch.settings.made_for_kids = True
    db.flush()
