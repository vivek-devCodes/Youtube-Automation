# AI YouTube Studio

**Autonomous content creation & publishing platform.** It finds trending topics, researches them, writes an *original* script, generates voice, visuals and music, renders Shorts and long-form videos with FFmpeg, checks originality and quality, and uploads to YouTube. Publishing waits for your approval unless you explicitly switch that off.

> **Honest expectations.** This tool does not guarantee views, subscribers or income. YouTube's monetisation rules reject mass-produced, repetitive or reused content, so the platform is built to produce *fewer, original, useful* videos. Trending videos are used as research signals only. Nothing is downloaded, copied or re-uploaded.

---

## What works today

| Area | Status |
|---|---|
| First-run onboarding wizard (10 steps), multi-channel config | ✅ |
| Google OAuth 2.0 channel connection, encrypted token storage, refresh, revoke | ✅ code complete; tested against a mocked Google API (needs your OAuth credentials for a live test) |
| Sandbox channel (full pipeline with simulated uploads, no Google account) | ✅ tested end-to-end |
| Trend discovery: YouTube `mostPopular` + `search.list`, Google Trends RSS, Google News RSS, evergreen fallback | ✅ (YouTube sources need `YOUTUBE_API_KEY` or a connected channel) |
| Configurable 0–100 trend scoring with view-velocity snapshots | ✅ |
| Research agent (Wikipedia + news, sourced facts, unsourced claims downgraded) | ✅ |
| Script / SEO / fact-check via **Ollama, Gemini, Claude, OpenAI** adapters | ✅ adapters; **mock** generator used for tests |
| Originality & copyright gate (n-gram + embedding similarity, trademark & child-safety screens, asset licence provenance) | ✅ |
| Voice: system TTS (espeak-ng / Windows SAPI), Kokoro, Piper, OpenAI TTS | ✅ system voice tested; others are adapters |
| Visuals: procedural motion graphics (free), ComfyUI, OpenAI Images; ComfyUI video (Wan/LTX) | ✅ procedural tested; others are adapters |
| FFmpeg renderer: Ken Burns, timed captions, original synthesized music, −14 LUFS, H.264/AAC, 9:16 & 16:9, SRT, thumbnail | ✅ tested |
| QA agent (integrity, codecs, aspect, duration, loudness, black frames, silence, subtitles, fact-check, licences, disclosure, audience) | ✅ |
| Approval workflow, scheduling (`publishAt`), resumable + idempotent uploads, quota tracking | ✅ (sandbox + mocked API) |
| Analytics (Data API + Analytics API) and weekly optimisation feedback loop | ✅ (sandbox data; real API needs a channel) |
| Persisted, resumable workflow engine, retries with backoff, global pause/resume, budget guard | ✅ |
| Docker Compose (Postgres+pgvector, Redis, Celery worker + beat, Nginx, optional Prometheus/Grafana) | ✅ written; **not yet run** on this machine (Docker daemon was off) |

Full checklist: [docs/CHECKLIST.md](docs/CHECKLIST.md).

---

## Quick start — Windows, no Docker (simplest)

Requirements: **Python 3.12+**, **Node.js 20+**. FFmpeg is bundled through `imageio-ffmpeg`.

```powershell
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. Create your admin account, then follow the wizard. Pick **"Create a sandbox practice channel"** to try everything without a Google account. Or run `scripts\dev.ps1` to start both servers.

## Quick start — Linux / macOS

```bash
sudo apt install ffmpeg espeak-ng fonts-noto-core   # Debian/Ubuntu: real FFmpeg, multilingual voice, Indic fonts
./scripts/dev.sh
```

## Production-style stack — Docker

```bash
cp .env.example .env          # set SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD (python scripts/gen_keys.py)
docker compose up --build     # http://localhost
docker compose --profile monitoring up --build   # + Prometheus :9090, Grafana :3001
```

This runs the API (migrations run automatically), a Celery worker (rendering), Celery Beat (schedules), PostgreSQL with pgvector, Redis, the Next.js frontend and Nginx. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for HTTPS, backups and scaling.

---

## Connecting real services

| You want | Do this | Guide |
|---|---|---|
| Upload to your real channel | Create OAuth credentials, set `GOOGLE_CLIENT_ID/SECRET` | [docs/SETUP_GOOGLE.md](docs/SETUP_GOOGLE.md) |
| Real YouTube trend data | Set `YOUTUBE_API_KEY` | same guide |
| Good scripts for free | Install [Ollama](https://ollama.com), `ollama pull llama3.1:8b`, set it as the default LLM in **AI Configuration** | [docs/COSTS.md](docs/COSTS.md) |
| Best scripts | Add a Claude / Gemini / OpenAI key in **AI Configuration**. It's stored encrypted and never shown again | [docs/COSTS.md](docs/COSTS.md) |
| Natural voices | Run Kokoro-FastAPI (`docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu`) and set its URL | [docs/COSTS.md](docs/COSTS.md) |
| AI images / video clips | Run ComfyUI on an NVIDIA GPU and paste an API-format workflow | [docs/COSTS.md](docs/COSTS.md) |

Never paste secrets into chats or tickets. Put them in `.env` or in the encrypted fields in the UI.

## Documentation

- [Architecture](docs/ARCHITECTURE.md): diagram, agents, workflow engine, data model
- [User onboarding guide](docs/ONBOARDING_GUIDE.md): for non-technical users
- [Google / YouTube setup](docs/SETUP_GOOGLE.md): every key, and where to get it
- [API](docs/API.md): REST endpoints; live OpenAPI at `http://localhost:8000/api/docs`
- [Costs & hardware](docs/COSTS.md)
- [Deployment & backups](docs/DEPLOYMENT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Development checklist](docs/CHECKLIST.md)

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest      # unit, API, security, mocked-YouTube, media + full pipeline E2E
cd frontend && npm test && npm run typecheck      # component/auth/approval tests
cd frontend && npx playwright test                # browser E2E against a running stack
```

Mock providers (offline LLM, silent TTS, sandbox YouTube) let you run the whole pipeline without paying for APIs or uploading anything.

## License

MIT. See [LICENSE](LICENSE). You are responsible for the content you publish and for complying with YouTube's Terms, Community Guidelines and monetisation policies.
