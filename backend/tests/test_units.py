from datetime import datetime, timedelta, timezone

import pytest

from app.agents.compliance import containment, cosine, embed
from app.core.errors import BudgetExceeded
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations.llm.providers import extract_json
from app.services import usage
from app.services.settings import ensure_automation


def test_containment_detects_copying():
    src = "The Moon is moving away from Earth at about 3.8 centimetres per year because of tidal interactions."
    assert containment(src, src, 5) == 1.0
    assert containment("Every year our satellite drifts a little further — roughly the width of a fingertip.", src, 5) == 0.0


def test_embedding_similarity():
    a = embed("how compound interest grows your savings over time")
    b = embed("how compound interest grows your savings over many years")
    c = embed("the offside rule in football explained simply")
    assert cosine(a, b) > cosine(a, c)


def test_encryption_roundtrip():
    enc = encrypt_secret("sk-secret-value")
    assert enc and "sk-secret" not in enc
    assert decrypt_secret(enc) == "sk-secret-value"


def test_extract_json_tolerates_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"b": [1,2]} done') == {"b": [1, 2]}


def test_budget_guard(db):
    auto = ensure_automation(db)
    auto.budget_mode, auto.monthly_budget_usd = "free", 10
    db.commit()
    with pytest.raises(BudgetExceeded):
        usage.guard(db, 0.01, "test")  # free mode forbids paid calls
    auto.budget_mode = "low"
    db.commit()
    usage.guard(db, 0.5, "test")
    usage.record(db, provider="x", kind="llm", cost_usd=9.8)
    db.commit()
    with pytest.raises(BudgetExceeded):
        usage.guard(db, 0.5, "test")


def test_youtube_quota_guard(db):
    from app.core.errors import QuotaExceeded

    usage.charge_youtube_quota(db, 9000, "x", 10000)
    with pytest.raises(QuotaExceeded):
        usage.charge_youtube_quota(db, 1600, "videos.insert", 10000)


def test_trend_scoring_prefers_fresh_fast_relevant(db):
    from app.agents.trends import score_trend
    from app.models import Channel, Trend, User
    from app.services.channels import ensure_children, set_niches

    u = User(email="u@example.com", password_hash="x")
    db.add(u)
    db.flush()
    ch = Channel(user_id=u.id, title="t", is_sandbox=True)
    ensure_children(db, ch)
    db.add(ch)
    db.flush()
    set_niches(db, ch, ["cricket"])
    now = datetime.now(timezone.utc)
    hot = Trend(channel_id=ch.id, source="youtube", external_id="a", topic="IPL cricket final analysis", title="IPL cricket final analysis",
                niche="cricket", view_count=2_000_000, like_count=90_000, comment_count=8000, published_at=now - timedelta(hours=5))
    stale = Trend(channel_id=ch.id, source="youtube", external_id="b", topic="Official music video", title="Official Music Video",
                  niche="cricket", view_count=50_000, like_count=500, comment_count=10, published_at=now - timedelta(days=9),
                  category_id="10")
    db.add_all([hot, stale])
    db.flush()
    score_trend(db, hot, ch, None)
    score_trend(db, stale, ch, None)
    assert hot.score > stale.score
    assert stale.score_breakdown["feasibility"] == 0.2


def test_scheduled_upload_body(db):
    from app.agents.publishing import _body
    from app.models import PublishingJob, VideoMetadata

    meta = VideoMetadata(video_id=1, title="T", description="D", tags=["a"], category_id="27", language="en",
                         made_for_kids=False, contains_synthetic_media=True)
    when = datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc)
    body = _body(meta, PublishingJob(privacy_status="public", scheduled_for=when))
    assert body["status"]["privacyStatus"] == "private"  # YouTube requires private + publishAt
    assert body["status"]["publishAt"] == "2030-01-02T03:04:00.000Z"
    assert body["status"]["containsSyntheticMedia"] is True
