"""All ORM models. Imported as a package so Alembic sees every table."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddingType(TypeDecorator):
    """pgvector `vector(384)` on PostgreSQL, JSON list elsewhere (SQLite dev/tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(384))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- 1. users
class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="admin")  # admin | editor | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------- 2. channels
class Channel(TimestampMixin, Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Sandbox channels never touch YouTube: uploads are simulated and clearly labelled.
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected|disconnected|token_error
    oauth_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted JSON
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    settings: Mapped["ChannelSettings"] = relationship(back_populates="channel", uselist=False, cascade="all, delete-orphan")
    brand: Mapped["ChannelBrand"] = relationship(back_populates="channel", uselist=False, cascade="all, delete-orphan")
    niches: Mapped[list["Niche"]] = relationship(back_populates="channel", cascade="all, delete-orphan")


# ---------------------------------------------------------------- 3. channel_settings
class ChannelSettings(TimestampMixin, Base):
    __tablename__ = "channel_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), unique=True)
    target_country: Mapped[str] = mapped_column(String(2), default="IN")
    primary_audience: Mapped[str] = mapped_column(String(200), default="General audience")
    language: Mapped[str] = mapped_column(String(10), default="en")
    voiceover_language: Mapped[str] = mapped_column(String(10), default="en")
    subtitle_languages: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["en"])
    youtube_category_id: Mapped[str] = mapped_column(String(5), default="27")  # Education
    content_style: Mapped[str] = mapped_column(String(50), default="educational")
    visual_style: Mapped[str] = mapped_column(String(50), default="motion_graphics")
    voice_style: Mapped[str] = mapped_column(String(50), default="female_warm")
    background_music: Mapped[bool] = mapped_column(Boolean, default=True)
    burn_subtitles: Mapped[bool] = mapped_column(Boolean, default=True)
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    short_duration_seconds: Mapped[int] = mapped_column(Integer, default=45)
    long_duration_range: Mapped[str] = mapped_column(String(10), default="5-8")
    shorts_per_day: Mapped[int] = mapped_column(Integer, default=1)
    long_per_week: Mapped[int] = mapped_column(Integer, default=0)
    publish_times: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["18:00"])
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    default_privacy: Mapped[str] = mapped_column(String(10), default="private")
    video_quality: Mapped[str] = mapped_column(String(10), default="1080p")  # 720p | 1080p

    channel: Mapped[Channel] = relationship(back_populates="settings")


# ---------------------------------------------------------------- 4. channel_brands
class ChannelBrand(TimestampMixin, Base):
    __tablename__ = "channel_brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), unique=True)
    brand_name: Mapped[str] = mapped_column(String(200), default="")
    tagline: Mapped[str] = mapped_column(String(300), default="")
    primary_color: Mapped[str] = mapped_column(String(9), default="#6D28D9")
    secondary_color: Mapped[str] = mapped_column(String(9), default="#F59E0B")
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    banner_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_identity: Mapped[str] = mapped_column(Text, default="")

    channel: Mapped[Channel] = relationship(back_populates="brand")


# ---------------------------------------------------------------- 5. niches
class Niche(TimestampMixin, Base):
    __tablename__ = "niches"
    __table_args__ = (UniqueConstraint("channel_id", "slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    youtube_category_id: Mapped[str | None] = mapped_column(String(5), nullable=True)
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)

    channel: Mapped[Channel] = relationship(back_populates="niches")


# ---------------------------------------------------------------- 6. trends
class Trend(TimestampMixin, Base):
    __tablename__ = "trends"
    __table_args__ = (
        UniqueConstraint("channel_id", "source", "external_id", name="uq_trend_source"),
        Index("ix_trends_channel_score", "channel_id", "score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    niche: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(30))  # youtube | google_trends | news | mock
    external_id: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    source_channel: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(5), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    region: Mapped[str | None] = mapped_column(String(2), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_velocity: Mapped[float] = mapped_column(Float, default=0.0)  # views per hour
    competition: Mapped[float] = mapped_column(Float, default=0.5)  # 0 low .. 1 high
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_ideas: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new|approved|rejected|used
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- 7. trend_snapshots
class TrendSnapshot(Base):
    __tablename__ = "trend_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    trend_id: Mapped[int] = mapped_column(ForeignKey("trends.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- 8. content_ideas
class ContentIdea(TimestampMixin, Base):
    __tablename__ = "content_ideas"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    trend_id: Mapped[int | None] = mapped_column(ForeignKey("trends.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    angle: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(10), default="short")  # short | long
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=45)
    language: Mapped[str] = mapped_column(String(10), default="en")
    research_summary: Mapped[str] = mapped_column(Text, default="")
    research_facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)


# ---------------------------------------------------------------- 9. research_sources
class ResearchSource(TimestampMixin, Base):
    __tablename__ = "research_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("content_ideas.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(800))
    title: Mapped[str] = mapped_column(String(500), default="")
    publisher: Mapped[str] = mapped_column(String(200), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    reliability: Mapped[str] = mapped_column(String(10), default="medium")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- 10. scripts
class Script(TimestampMixin, Base):
    __tablename__ = "scripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("content_ideas.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(300))
    hook: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")  # full voiceover text
    cta: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    estimated_duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    music_suggestion: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|rejected
    originality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    compliance_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(40), default="")
    llm_model: Mapped[str] = mapped_column(String(80), default="")

    scenes: Mapped[list["Scene"]] = relationship(order_by="Scene.idx", cascade="all, delete-orphan")


# ---------------------------------------------------------------- 11. scenes
class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("script_id", "idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text)
    on_screen_text: Mapped[str] = mapped_column(String(200), default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    visual_type: Mapped[str] = mapped_column(String(20), default="image")
    estimated_seconds: Mapped[float] = mapped_column(Float, default=5)


# ---------------------------------------------------------------- 15. videos
class Video(TimestampMixin, Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("content_ideas.id", ondelete="SET NULL"), nullable=True)
    script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True)
    format: Mapped[str] = mapped_column(String(10), default="short")
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qa_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    youtube_url: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meta: Mapped["VideoMetadata"] = relationship(uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------- 12. media_assets
class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True)
    script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), nullable=True, index=True)
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # image|video_clip|music|sfx|logo
    path: Mapped[str] = mapped_column(String(600))
    provider: Mapped[str] = mapped_column(String(40))
    prompt: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    license: Mapped["AssetLicense"] = relationship(uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------- 13. asset_licenses
class AssetLicense(TimestampMixin, Base):
    __tablename__ = "asset_licenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True)
    # ai_generated | procedural_generated | stock_licensed | public_domain | user_owned | licensed_third_party
    license_type: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    attribution: Mapped[str] = mapped_column(String(500), default="")
    terms_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- 14. voiceovers
class Voiceover(TimestampMixin, Base):
    __tablename__ = "voiceovers"
    __table_args__ = (UniqueConstraint("script_id", "scene_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    voice: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    path: Mapped[str] = mapped_column(String(600))
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    license_note: Mapped[str] = mapped_column(String(300), default="")


# ---------------------------------------------------------------- 16. video_metadata
class VideoMetadata(TimestampMixin, Base):
    __tablename__ = "video_metadata"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    category_id: Mapped[str] = mapped_column(String(5), default="27")
    language: Mapped[str] = mapped_column(String(10), default="en")
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    contains_synthetic_media: Mapped[bool] = mapped_column(Boolean, default=True)
    privacy_status: Mapped[str] = mapped_column(String(10), default="private")
    thumbnail_text: Mapped[str] = mapped_column(String(60), default="")
    thumbnail_prompt: Mapped[str] = mapped_column(Text, default="")
    playlist_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------- 17. thumbnails
class Thumbnail(TimestampMixin, Base):
    __tablename__ = "thumbnails"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(600))
    text: Mapped[str] = mapped_column(String(100), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------- 18. subtitles
class Subtitle(TimestampMixin, Base):
    __tablename__ = "subtitles"
    __table_args__ = (UniqueConstraint("video_id", "language", "format"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(10))
    format: Mapped[str] = mapped_column(String(5), default="srt")
    path: Mapped[str] = mapped_column(String(600))
    burned_in: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- 19. publishing_jobs
class PublishingJob(TimestampMixin, Base):
    __tablename__ = "publishing_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    privacy_status: Mapped[str] = mapped_column(String(10), default="private")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # YouTube publishAt
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # when we upload
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_session_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes_uploaded: Mapped[int] = mapped_column(Integer, default=0)
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


# ---------------------------------------------------------------- 20. publishing_history
class PublishingHistory(Base):
    __tablename__ = "publishing_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("publishing_jobs.id", ondelete="SET NULL"), nullable=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------- 21. analytics_snapshots
class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (Index("ix_analytics_video_time", "video_id", "captured_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    window: Mapped[str] = mapped_column(String(10), default="lifetime")  # 24h|48h|7d|28d|lifetime|channel
    views: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    watch_time_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_view_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_view_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscribers_gained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscribers_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="data_api")
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------- 22. ai_providers
class AIProvider(TimestampMixin, Base):
    __tablename__ = "ai_providers"
    __table_args__ = (UniqueConstraint("kind", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # llm | tts | image | video
    name: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted, never returned
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")  # ok|error|unknown
    health_message: Mapped[str] = mapped_column(Text, default="")
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- 23. model_configurations
class ModelConfiguration(TimestampMixin, Base):
    __tablename__ = "model_configurations"
    __table_args__ = (UniqueConstraint("provider_id", "task"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"))
    task: Mapped[str] = mapped_column(String(30), default="default")  # default|script|research|seo
    model_name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_per_1k_input: Mapped[float] = mapped_column(Float, default=0.0)
    cost_per_1k_output: Mapped[float] = mapped_column(Float, default=0.0)
    cost_per_unit: Mapped[float] = mapped_column(Float, default=0.0)  # per image / per 1k chars / per second


# ---------------------------------------------------------------- 24. api_usage
class ApiUsage(Base):
    __tablename__ = "api_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # llm|tts|image|video|youtube_quota
    model: Mapped[str] = mapped_column(String(120), default="")
    task: Mapped[str] = mapped_column(String(40), default="")
    units: Mapped[float] = mapped_column(Float, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    workflow_run_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------- 25. automation_settings
class AutomationSettings(TimestampMixin, Base):
    __tablename__ = "automation_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    budget_mode: Mapped[str] = mapped_column(String(10), default="free")  # free|low|balanced|premium
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    trend_scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=150)
    analytics_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    min_quality_score: Mapped[int] = mapped_column(Integer, default=85)
    trend_weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    # Global gate: unattended *public* publishing requires an explicit, timestamped opt-in.
    unattended_publishing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    unattended_publishing_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_similarity: Mapped[float] = mapped_column(Float, default=0.35)
    # When on, the planner may pick high-scoring topics without a human approving each one.
    auto_select_topics: Mapped[bool] = mapped_column(Boolean, default=False)
    min_trend_score: Mapped[float] = mapped_column(Float, default=55.0)
    trademark_blocklist: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=180)
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    optimization_insights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_trend_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_analytics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_optimization_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- 26. approval_requests
class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # video_publish | budget | script
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- 27. audit_logs
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------- 28. notifications
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info|warning|critical
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------- workflow persistence
class WorkflowRun(TimestampMixin, Base):
    """One end-to-end production run (idea -> published video). Steps are persisted so a
    crashed or failed run resumes from the last successful step without redoing work."""

    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("content_ideas.id", ondelete="CASCADE"))
    script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    # pending|running|waiting_approval|paused|succeeded|failed|cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    current_step: Mapped[str | None] = mapped_column(String(30), nullable=True)
    steps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    review_script: Mapped[bool] = mapped_column(Boolean, default=False)  # pause after script for editing
