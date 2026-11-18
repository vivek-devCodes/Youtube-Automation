"""Application settings. Every secret comes from the environment (or .env), never from code."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    app_name: str = "AI YouTube Studio"
    environment: str = "development"  # development | staging | production
    debug: bool = False

    # --- Database / queue -------------------------------------------------
    # SQLite is used for zero-dependency local dev; Docker Compose sets PostgreSQL.
    database_url: str = f"sqlite:///{(PROJECT_DIR / 'storage' / 'studio.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    # "inline" runs jobs in an in-process scheduler (no Redis needed);
    # "celery" dispatches to Celery workers + Celery Beat.
    task_mode: str = "inline"

    # --- Security ---------------------------------------------------------
    secret_key: str = "dev-insecure-change-me"  # JWT signing key
    # Fernet key used to encrypt OAuth tokens and provider API keys at rest.
    encryption_key: str = ""
    session_hours: int = 24 * 7
    cors_origins: str = "http://localhost:3000"
    public_base_url: str = "http://localhost:3000"  # where the browser reaches the app

    # --- Storage ----------------------------------------------------------
    storage_backend: str = "local"  # local | s3
    storage_dir: str = str(PROJECT_DIR / "storage")
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # set for Cloudflare R2
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"

    # --- Google / YouTube ---------------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    youtube_api_key: str = ""  # read-only Data API key used for trend discovery
    youtube_daily_quota: int = 10000
    youtube_upload_quota_cost: int = 1600  # units charged per videos.insert (check your console)
    enable_playlist_scope: bool = False  # adds the broad `youtube` scope for playlist assignment
    enable_monetary_analytics: bool = False  # adds yt-analytics-monetary.readonly for revenue

    # --- AI providers (optional; can also be stored encrypted via the UI) ---
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    kokoro_base_url: str = ""  # e.g. http://localhost:8880 (Kokoro-FastAPI)
    piper_base_url: str = ""  # e.g. http://localhost:5000 (piper http server)
    comfyui_base_url: str = ""  # e.g. http://localhost:8188

    # Identifies this install to public sources (Wikimedia requires a contact URL or email in the
    # User-Agent and rejects anonymous bots). Set to your site or an ops email.
    research_contact: str = ""

    # --- Behaviour ----------------------------------------------------------
    trend_scan_interval_minutes: int = 150
    pipeline_tick_seconds: int = 60
    min_quality_score: int = 85

    # --- Monitoring ---------------------------------------------------------
    sentry_dsn: str = ""
    log_level: str = "INFO"

    rate_limit: str = Field(default="120/minute")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/v1/auth/youtube/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
