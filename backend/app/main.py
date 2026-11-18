from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.routes import auth, channels, content, onboarding, publishing, system, trends, videos
from app.core.config import settings
from app.core.errors import BudgetExceeded, ProviderNotConfigured, StudioError
from app.core.logging import configure_logging
from app.database.session import SessionLocal, engine
from app.limiter import limiter

configure_logging()
log = logging.getLogger("app")

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.1, send_default_pii=False)


def init_db() -> None:
    """Dev convenience for SQLite: create tables + seed providers. PostgreSQL uses Alembic migrations."""
    from app.database.session import Base
    from app.integrations.registry import seed_providers
    import app.models  # noqa: F401

    if settings.is_sqlite:
        from pathlib import Path

        Path(settings.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_providers(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.task_mode == "inline" and settings.environment != "test":
        from app.workers.dispatch import runner

        runner.start()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Too many requests — slow down"}, status_code=429)


@app.exception_handler(BudgetExceeded)
async def budget(request: Request, exc: BudgetExceeded):
    return JSONResponse({"detail": str(exc), "code": "budget_exceeded"}, status_code=402)


@app.exception_handler(ProviderNotConfigured)
async def not_configured(request: Request, exc: ProviderNotConfigured):
    return JSONResponse({"detail": str(exc), "code": "provider_not_configured"}, status_code=400)


@app.exception_handler(StudioError)
async def studio_error(request: Request, exc: StudioError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


api = APIRouter(prefix="/api/v1")
for r in (auth.router, onboarding.router, channels.router, trends.router, content.router, videos.router,
          publishing.router, system.router, videos.media_router):
    api.include_router(r)
app.include_router(api)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    from app.workers.dispatch import worker_health
    from app.video_engine.ffmpeg import ffmpeg_exe

    checks = {}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {e}"
    try:
        ffmpeg_exe()
        checks["ffmpeg"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["ffmpeg"] = f"error: {e}"
    checks["worker"] = worker_health()
    ok = checks["database"] == "ok" and checks["ffmpeg"] == "ok"
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


try:  # Prometheus metrics at /metrics
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except Exception:  # noqa: BLE001  pragma: no cover
    log.warning("prometheus instrumentator unavailable")
