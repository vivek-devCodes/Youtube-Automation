"""YouTube Data API v3 + YouTube Analytics API v2 + Google OAuth 2.0.

Quota costs follow Google's published table (videos.insert is configurable via
YOUTUBE_UPLOAD_QUOTA_COST because Google has changed it over time)."""
from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.core.errors import ProviderNotConfigured, QuotaExceeded, YouTubeError
from app.core.security import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"

QUOTA = {"videos.list": 1, "search.list": 100, "videoCategories.list": 1, "channels.list": 1,
         "playlistItems.list": 1, "playlistItems.insert": 50, "thumbnails.set": 50, "videos.update": 50}


def scopes() -> list[str]:
    s = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
    if settings.enable_playlist_scope:
        s.append("https://www.googleapis.com/auth/youtube")
    if settings.enable_monetary_analytics:
        s.append("https://www.googleapis.com/auth/yt-analytics-monetary.readonly")
    return s


# ------------------------------------------------------------------ OAuth
def build_auth_url(user_id: int) -> str:
    if not settings.google_oauth_configured:
        raise ProviderNotConfigured("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env")
    state = jwt.encode({"uid": user_id, "n": secrets.token_urlsafe(8),
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, settings.secret_key, algorithm="HS256")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes()),
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def verify_state(state: str) -> int:
    try:
        return int(jwt.decode(state, settings.secret_key, algorithms=["HS256"])["uid"])
    except jwt.PyJWTError as e:
        raise YouTubeError("Invalid or expired OAuth state", retryable=False) from e


def exchange_code(code: str) -> dict[str, Any]:
    r = httpx.post(TOKEN_URL, timeout=30, data={
        "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "redirect_uri": settings.oauth_redirect_uri, "grant_type": "authorization_code",
    })
    if r.status_code != 200:
        raise YouTubeError(f"Token exchange failed: {r.text[:300]}", retryable=False)
    tok = r.json()
    tok["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)).isoformat()
    return tok


def revoke(token: str) -> None:
    try:
        httpx.post(REVOKE_URL, data={"token": token}, timeout=15)
    except httpx.HTTPError:
        log.warning("token revoke failed (ignored)")


class TokenStore:
    """Wraps a channel's encrypted token blob; refreshes transparently."""

    def __init__(self, encrypted: str | None, on_update: Callable[[str], None]):
        raw = decrypt_secret(encrypted)
        self.tok: dict[str, Any] = json.loads(raw) if raw else {}
        self.on_update = on_update

    def access_token(self) -> str:
        if not self.tok:
            raise YouTubeError("Channel is not authorised — reconnect it", retryable=False)
        exp = datetime.fromisoformat(self.tok.get("expires_at", "1970-01-01T00:00:00+00:00"))
        if exp <= datetime.now(timezone.utc):
            self.refresh()
        return self.tok["access_token"]

    def refresh(self) -> None:
        rt = self.tok.get("refresh_token")
        if not rt:
            raise YouTubeError("No refresh token stored — reconnect the channel", retryable=False)
        r = httpx.post(TOKEN_URL, timeout=30, data={"client_id": settings.google_client_id,
                                                   "client_secret": settings.google_client_secret,
                                                   "refresh_token": rt, "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise YouTubeError(f"Token refresh failed ({r.status_code}): reconnect the channel", retryable=False)
        new = r.json()
        self.tok["access_token"] = new["access_token"]
        self.tok["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(new.get("expires_in", 3600)) - 60)).isoformat()
        self.on_update(encrypt_secret(json.dumps(self.tok)) or "")


# ------------------------------------------------------------------ API client
class YouTubeClient:
    def __init__(self, token_store: TokenStore | None = None, api_key: str | None = None,
                 charge: Callable[[int, str], None] | None = None):
        self.tokens = token_store
        self.api_key = api_key or settings.youtube_api_key or None
        self.charge = charge or (lambda units, op: None)
        if not self.tokens and not self.api_key:
            raise ProviderNotConfigured("Set YOUTUBE_API_KEY or connect a channel to read YouTube data")

    def _auth(self, params: dict, headers: dict, require_oauth: bool = False) -> None:
        if self.tokens:
            headers["Authorization"] = f"Bearer {self.tokens.access_token()}"
        elif require_oauth:
            raise YouTubeError("This call needs an authorised channel", retryable=False)
        else:
            params["key"] = self.api_key

    @staticmethod
    def _raise(r: httpx.Response, op: str) -> None:
        if r.status_code < 400:
            return
        try:
            err = r.json().get("error", {})
            reason = (err.get("errors") or [{}])[0].get("reason", "")
            msg = err.get("message", r.text[:200])
        except ValueError:
            reason, msg = "", r.text[:200]
        if reason in ("quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"):
            raise QuotaExceeded(f"{op}: YouTube quota/upload limit reached ({reason})")
        raise YouTubeError(f"{op} failed ({r.status_code} {reason}): {msg}", retryable=r.status_code >= 500 or r.status_code == 429)

    def get(self, resource: str, params: dict, require_oauth: bool = False, api_key_ok: bool = True) -> dict:
        op = f"{resource}.list"
        self.charge(QUOTA.get(op, 1), op)
        headers: dict[str, str] = {}
        params = dict(params)
        if api_key_ok and self.api_key and not require_oauth:
            params["key"] = self.api_key
        else:
            self._auth(params, headers, require_oauth)
        r = httpx.get(f"{API}/{resource}", params=params, headers=headers, timeout=30)
        self._raise(r, op)
        return r.json()

    # -- read
    def most_popular(self, region: str, category_id: str | None = None, max_results: int = 25) -> list[dict]:
        p = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": region, "maxResults": max_results}
        if category_id:
            p["videoCategoryId"] = category_id
        return self.get("videos", p).get("items", [])

    def search_recent(self, query: str, region: str, language: str | None, days: int = 7, max_results: int = 15) -> list[dict]:
        after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p = {"part": "snippet", "q": query, "type": "video", "order": "viewCount", "regionCode": region,
             "publishedAfter": after, "maxResults": max_results}
        if language:
            p["relevanceLanguage"] = language
        ids = [i["id"]["videoId"] for i in self.get("search", p).get("items", []) if i.get("id", {}).get("videoId")]
        return self.videos(ids)

    def videos(self, ids: list[str], part: str = "snippet,statistics,contentDetails") -> list[dict]:
        out = []
        for i in range(0, len(ids), 50):
            out += self.get("videos", {"part": part, "id": ",".join(ids[i : i + 50])}).get("items", [])
        return out

    def my_channels(self) -> list[dict]:
        return self.get("channels", {"part": "snippet,statistics,contentDetails", "mine": "true"},
                        require_oauth=True, api_key_ok=False).get("items", [])

    def categories(self, region: str) -> list[dict]:
        return self.get("videoCategories", {"part": "snippet", "regionCode": region}).get("items", [])

    # -- write
    def start_resumable_upload(self, body: dict, file_size: int) -> str:
        self.charge(settings.youtube_upload_quota_cost, "videos.insert")
        headers = {"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(file_size),
                   "X-Upload-Content-Type": "video/mp4"}
        self._auth({}, headers, require_oauth=True)
        r = httpx.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                       headers=headers, json=body, timeout=60)
        self._raise(r, "videos.insert(init)")
        loc = r.headers.get("Location")
        if not loc:
            raise YouTubeError("YouTube did not return an upload session URL")
        return loc

    def upload_status(self, session_url: str, file_size: int) -> tuple[int, dict | None]:
        """Ask YouTube how many bytes it has. Returns (bytes_received, finished_resource_or_None)."""
        headers = {"Content-Range": f"bytes */{file_size}", "Content-Length": "0"}
        self._auth({}, headers, require_oauth=True)
        r = httpx.put(session_url, headers=headers, timeout=60)
        if r.status_code in (200, 201):
            return file_size, r.json()
        if r.status_code == 308:
            rng = r.headers.get("Range")
            return (int(rng.split("-")[1]) + 1 if rng else 0), None
        if r.status_code == 404:
            raise YouTubeError("Upload session expired; a new session will be started", retryable=True)
        self._raise(r, "videos.insert(status)")
        return 0, None

    def upload_chunks(self, session_url: str, path: Path, start: int, on_progress: Callable[[int], None],
                      chunk_size: int = 8 * 1024 * 1024) -> dict:
        size = path.stat().st_size
        offset = start
        with open(path, "rb") as f:
            while offset < size:
                f.seek(offset)
                data = f.read(chunk_size)
                end = offset + len(data) - 1
                headers = {"Content-Range": f"bytes {offset}-{end}/{size}", "Content-Length": str(len(data))}
                self._auth({}, headers, require_oauth=True)
                r = httpx.put(session_url, headers=headers, content=data, timeout=600)
                if r.status_code in (200, 201):
                    on_progress(size)
                    return r.json()
                if r.status_code == 308:
                    rng = r.headers.get("Range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                    on_progress(offset)
                    continue
                self._raise(r, "videos.insert(chunk)")
        received, resource = self.upload_status(session_url, size)
        if resource:
            return resource
        raise YouTubeError(f"Upload incomplete ({received}/{size} bytes)")

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        self.charge(QUOTA["thumbnails.set"], "thumbnails.set")
        headers = {"Content-Type": "image/jpeg"}
        self._auth({}, headers, require_oauth=True)
        r = httpx.post(f"{UPLOAD_API}/thumbnails/set", params={"videoId": video_id}, headers=headers,
                       content=image.read_bytes(), timeout=120)
        self._raise(r, "thumbnails.set")

    def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self.charge(QUOTA["playlistItems.insert"], "playlistItems.insert")
        headers: dict[str, str] = {}
        self._auth({}, headers, require_oauth=True)
        r = httpx.post(f"{API}/playlistItems", params={"part": "snippet"}, headers=headers, timeout=30, json={
            "snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        self._raise(r, "playlistItems.insert")

    # -- analytics
    def analytics_report(self, start: str, end: str, metrics: list[str], dimensions: str | None = None,
                         filters: str | None = None) -> dict:
        headers: dict[str, str] = {}
        self._auth({}, headers, require_oauth=True)
        p = {"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(metrics)}
        if dimensions:
            p["dimensions"] = dimensions
        if filters:
            p["filters"] = filters
        r = httpx.get(ANALYTICS_API, params=p, headers=headers, timeout=60)
        self._raise(r, "youtubeAnalytics.reports.query")
        return r.json()


# ------------------------------------------------------------------ Sandbox (no Google account)
class SandboxYouTube:
    """Stands in for YouTube on sandbox channels: nothing leaves the machine. Every ID is prefixed
    `sandbox-` and the UI labels these videos as simulated."""

    def __init__(self, root: Path):
        self.root = root / "sandbox_youtube"
        self.root.mkdir(parents=True, exist_ok=True)

    def upload(self, path: Path, body: dict, on_progress: Callable[[int], None]) -> dict:
        vid = "sandbox-" + secrets.token_hex(5)
        dest = self.root / f"{vid}.mp4"
        size = path.stat().st_size
        with open(path, "rb") as src, open(dest, "wb") as dst:
            copied = 0
            while chunk := src.read(4 * 1024 * 1024):
                dst.write(chunk)
                copied += len(chunk)
                on_progress(copied)
        (self.root / f"{vid}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        assert dest.stat().st_size == size
        return {"id": vid, "status": {"uploadStatus": "processed", **body.get("status", {})}, "snippet": body.get("snippet", {})}

    def stats(self, video_id: str, age_hours: float) -> dict:
        seed = int.from_bytes(video_id.encode()[-4:], "big") % 97 + 3
        views = int(seed * (age_hours ** 0.8))
        return {"views": views, "likes": views // 25, "comments": views // 180, "watch_minutes": round(views * 0.42, 1),
                "avg_view_duration": 18 + seed % 20, "subscribers_gained": views // 300}

    def delete_all(self) -> None:
        for p in self.root.glob("sandbox-*"):
            os.remove(p)
