# Development checklist

Legend: ✅ done & verified by automated tests or a live run · 🟡 implemented, verified only against mocks · ⏳ not started / needs your credentials or hardware

## Phase 1 — Foundation
- ✅ Project structure, config, structured logging, error model
- ✅ 29-table schema + Alembic migration (`alembic check` clean)
- ✅ Auth: first-run admin, login/logout, httpOnly JWT cookie, bcrypt, RBAC, rate limits, audit log
- ✅ Onboarding wizard (10 steps), verified in a real browser (Playwright)
- ✅ Multi-channel configuration (brand, audience, niches incl. custom, languages, formats, publishing)
- ✅ Dashboard UI (Next.js, React Query, Tailwind, shadcn-style components, Recharts)

## Phase 2 — Trend discovery
- 🟡 YouTube `mostPopular` + `search.list` + `videos.list` (needs `YOUTUBE_API_KEY`)
- ✅ Google Trends RSS, Google News RSS (live network), evergreen fallback
- ✅ Snapshots, view velocity, configurable weighted 0–100 score, feasibility penalties
- ✅ Trend page: filter, approve/reject, suggested original angles

## Phase 3 — AI content
- ✅ Research agent (Wikipedia + news, sourced facts)
- ✅ Script, SEO, fact-check agents via provider adapters
- 🟡 Ollama / Gemini / Claude / OpenAI adapters (code complete with health checks; need keys/servers to verify live)
- ✅ Originality & copyright gate with automatic rewrite (caught real verbatim copying during development)
- ✅ Budget guard + per-call usage logging + per-video cost attribution

## Phase 4 — Video
- ✅ System TTS (Windows SAPI verified; espeak-ng in Docker), mock TTS
- 🟡 Kokoro, Piper, OpenAI TTS adapters
- ✅ Procedural visuals; 🟡 ComfyUI / OpenAI Images; 🟡 ComfyUI Wan/LTX clips (needs a GPU)
- ✅ FFmpeg renderer, captions, SRT, original music, loudness normalisation, thumbnails
- ✅ QA agent with 16 checks and critical gates

## Phase 5 — YouTube
- 🟡 OAuth (consent URL, signed state, token exchange, refresh, revoke): unit-tested with mocked Google
- 🟡 Resumable upload with resume-after-interruption, quota errors: tested against mocked HTTP
- ✅ Sandbox uploads end-to-end (API + browser)
- ✅ Approval workflow, scheduling (`publishAt`), idempotency, retries, quota deferral
- ⏳ **Live upload to your channel**: needs your Google OAuth client (docs/SETUP_GOOGLE.md). Test with privacy = private first.

## Phase 6 — Analytics
- ✅ Snapshot collection (sandbox), windows, optimisation insights fed back into scoring/scripts
- 🟡 Data API + Analytics API collection for real channels
- ✅ Analytics dashboard

## Phase 7 — Production
- ✅ Dockerfiles, Compose (Postgres+pgvector, Redis, Celery worker/beat, Nginx, Prometheus/Grafana), health checks
- ⏳ `docker compose up --build` not yet executed here (Docker Desktop daemon was not running)
- ✅ CI workflow, backup script, deployment/troubleshooting/cost docs
- ⏳ HTTPS + domain: deployment-specific (docs/DEPLOYMENT.md)

## Known limitations
- The offline "template" LLM is for testing only. Real-quality scripts need Ollama or a cloud LLM.
- Spelling QA is a basic sanity check, not a dictionary spell-checker.
- YouTube Analytics exposes impressions/CTR only partially. CTR charts stay empty if unavailable.
- Thumbnails for Shorts are uploaded but YouTube may not display them on the Shorts shelf.
- The trend score is heuristic. Tune the weights in Settings once you have data.
