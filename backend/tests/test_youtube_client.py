"""YouTube integration tested against a mocked Google HTTP API (no real uploads)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import respx

from app.core.security import encrypt_secret
from app.integrations.youtube.client import API, TOKEN_URL, UPLOAD_API, TokenStore, YouTubeClient


def store(expired=False):
    exp = datetime.now(timezone.utc) + (timedelta(minutes=-1) if expired else timedelta(hours=1))
    tok = {"access_token": "old", "refresh_token": "r1", "expires_at": exp.isoformat()}
    saved = {}
    return TokenStore(encrypt_secret(json.dumps(tok)), lambda enc: saved.setdefault("enc", enc)), saved


@respx.mock
def test_token_refresh_on_expiry():
    s, saved = store(expired=True)
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600}))
    route = respx.get(f"{API}/channels").mock(return_value=httpx.Response(200, json={"items": [{"id": "UC1"}]}))
    yt = YouTubeClient(token_store=s)
    assert yt.my_channels()[0]["id"] == "UC1"
    assert route.calls[0].request.headers["Authorization"] == "Bearer new"
    assert "enc" in saved  # refreshed token persisted (encrypted)


@respx.mock
def test_resumable_upload_resumes_after_interruption(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x" * 300)
    s, _ = store()
    charges = []
    yt = YouTubeClient(token_store=s, charge=lambda u, op: charges.append((op, u)))
    respx.post(f"{UPLOAD_API}/videos").mock(return_value=httpx.Response(200, headers={"Location": "https://upload.example/session1"}))
    calls = {"n": 0}

    def put(request):
        calls["n"] += 1
        rng = request.headers["Content-Range"]
        if rng.startswith("bytes */"):  # status query after interruption
            return httpx.Response(308, headers={"Range": "bytes=0-99"})
        if rng.startswith("bytes 0-"):
            return httpx.Response(308, headers={"Range": "bytes=0-99"})  # server only kept 100 bytes
        return httpx.Response(200, json={"id": "VID123", "status": {"uploadStatus": "uploaded"}})

    respx.put("https://upload.example/session1").mock(side_effect=put)
    session = yt.start_resumable_upload({"snippet": {"title": "t"}, "status": {"privacyStatus": "private"}}, 300)
    received, done = yt.upload_status(session, 300)
    assert received == 100 and done is None
    res = yt.upload_chunks(session, f, received, lambda n: None, chunk_size=1024)
    assert res["id"] == "VID123"
    assert ("videos.insert", 1600) in charges


@respx.mock
def test_quota_error_is_not_retried():
    import pytest

    from app.core.errors import QuotaExceeded

    s, _ = store()
    respx.get(f"{API}/channels").mock(return_value=httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}],
                                                                                       "message": "quota"}}))
    with pytest.raises(QuotaExceeded) as e:
        YouTubeClient(token_store=s).my_channels()
    assert e.value.retryable is False
