import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="studio-test-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "STORAGE_DIR": str(_TMP / "storage"),
    "SECRET_KEY": "test-secret",
    "TASK_MODE": "inline",
    "YOUTUBE_API_KEY": "",
    "GOOGLE_CLIENT_ID": "test-client",
    "GOOGLE_CLIENT_SECRET": "test-secret",
    "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.integrations.trends import sources  # noqa: E402

FAKE_WIKI = [{
    "url": "https://en.wikipedia.org/wiki/Moon", "title": "Moon", "publisher": "Wikipedia", "reliability": "medium",
    "published_at": None,
    "snippet": ("The Moon is Earth's only natural satellite and orbits at an average distance of 384,400 kilometres. "
                "It is moving away from Earth at about 3.8 centimetres per year because of tidal interactions. "
                "The Moon always shows the same face to Earth because it is tidally locked. "
                "Its surface gravity is about one sixth of Earth's gravity."),
}]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network in tests: research + trend sources return fixed data."""
    monkeypatch.setattr(sources, "wikipedia_sources", lambda q, lang="en", limit=3: [dict(s) for s in FAKE_WIKI])
    monkeypatch.setattr(sources, "google_news", lambda *a, **k: [])
    monkeypatch.setattr(sources, "news_trends", lambda *a, **k: [])
    monkeypatch.setattr(sources, "google_trends_daily", lambda geo: [])


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.integrations.registry import seed_providers

    s = SessionLocal()
    seed_providers(s)
    # Fast tests: silent TTS (the real system voice is covered by test_media).
    from app.models import AIProvider
    for p in s.query(AIProvider).filter(AIProvider.kind == "tts").all():
        p.is_default = p.name == "mock"
        p.enabled = True
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin(client):
    r = client.post("/api/v1/auth/register", json={"email": "admin@example.com", "password": "correct-horse-1", "name": "Admin"})
    assert r.status_code == 200, r.text
    return client


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
