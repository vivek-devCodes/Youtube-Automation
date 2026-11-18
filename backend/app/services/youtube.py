from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ProviderNotConfigured
from app.integrations.youtube.client import TokenStore, YouTubeClient
from app.models import Channel


def token_store(db: Session, channel: Channel) -> TokenStore:
    def save(enc: str) -> None:
        channel.oauth_token_enc = enc
        db.commit()

    return TokenStore(channel.oauth_token_enc, save)


def youtube_for_channel(db: Session, channel: Channel, *, charge: Callable[[int, str], None] | None = None,
                        read_only: bool = False) -> YouTubeClient:
    """Authorised client for a real channel; for read-only use, the API key is enough."""
    if channel.is_sandbox:
        if read_only and settings.youtube_api_key:
            return YouTubeClient(api_key=settings.youtube_api_key, charge=charge)
        raise ProviderNotConfigured("Sandbox channel: no YouTube credentials (set YOUTUBE_API_KEY for real trend data)")
    if channel.oauth_token_enc and settings.google_oauth_configured:
        return YouTubeClient(token_store=token_store(db, channel), api_key=settings.youtube_api_key or None, charge=charge)
    if read_only and settings.youtube_api_key:
        return YouTubeClient(api_key=settings.youtube_api_key, charge=charge)
    raise ProviderNotConfigured("Channel is not authorised with Google — reconnect it")
