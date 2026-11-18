# Deployment

## Single server (VPS) with Docker
1. A Linux VM with 4+ vCPU and 8 GB RAM (rendering is CPU-bound; one worker renders one video at a time).
2. Install Docker Engine + the Compose plugin. Clone the repo.
3. `cp .env.example .env`, then set:
   - `ENVIRONMENT=production`
   - `SECRET_KEY` and `ENCRYPTION_KEY` (`python scripts/gen_keys.py`). **Back up `ENCRYPTION_KEY`**: without it, stored tokens and keys cannot be decrypted.
   - `POSTGRES_PASSWORD`, `PUBLIC_BASE_URL=https://your-domain.com`, Google credentials.
4. `docker compose up -d --build`
5. **HTTPS**: put a TLS terminator in front of Nginx. The simplest option is Caddy on the host:
   ```
   your-domain.com {
     reverse_proxy localhost:80
   }
   ```
   With HTTPS, `ENVIRONMENT=production` marks the session cookie `Secure`.
6. Update the OAuth redirect URI in Google Cloud to the HTTPS domain.

## Scaling
- More renders in parallel: `docker compose up -d --scale worker=3`. Runs are leased per row, so no double processing.
- GPU workloads (ComfyUI) run as a separate service. Point the provider's base URL at it.
- Splitting into services: the render worker can move to its own host unchanged, since it only needs DB, Redis and storage. Set `STORAGE_BACKEND=s3` so finished videos are mirrored to R2/S3.

## Backups
```bash
./scripts/backup.sh            # pg_dump + media tarball into ./backups/<timestamp>/
```
Schedule it daily with cron (`0 3 * * * cd /opt/studio && ./scripts/backup.sh`) and copy `backups/` off the server. Restore:
```bash
gunzip -c backups/<ts>/db.sql.gz | docker compose exec -T postgres psql -U studio studio
docker run --rm -v youtube-automation_media:/data -v $PWD/backups/<ts>:/b alpine tar xzf /b/media.tgz -C /data
```

## Monitoring
- `GET /health` (liveness) and `GET /health/ready` (DB, FFmpeg, worker).
- Prometheus metrics at `/metrics` (blocked publicly by Nginx; scraped internally). `docker compose --profile monitoring up -d` starts Prometheus (:9090) and Grafana (:3001). Add Prometheus as a Grafana data source (`http://prometheus:9090`).
- Set `SENTRY_DSN` for error tracking (no PII is sent).
- Structured JSON logs on stdout.

## CI
`.github/workflows/ci.yml` runs backend tests, frontend typecheck/tests/build, and a Docker build on every push.

## Migrations
The API container runs `alembic upgrade head` on start. After changing models:
`cd backend && alembic revision --autogenerate -m "describe change"`.

## Frontend on Vercel (optional)
Vercel can host the **Next.js dashboard only**. The backend needs FFmpeg, long-running render workers, PostgreSQL and Redis, so run it on a VPS (Docker Compose above).

1. Import the GitHub repo in Vercel and set **Root Directory** to `frontend`.
2. Add the environment variable `BACKEND_URL=https://<your-backend-domain>` and redeploy. It is read at build time by the `/api` rewrite.
3. Set `PUBLIC_BASE_URL` on the backend to the Vercel domain so OAuth redirects land on the dashboard. Add `<vercel-domain>/api/v1/auth/youtube/callback` as an authorized redirect URI in Google Cloud.

**Hobby plan gotcha:** for private repos, Vercel blocks deployments of commits whose author is not the Vercel account owner ("commit author did not have contributing access"). Commit with the GitHub identity linked to Vercel, e.g. repo-local `git config user.email <id>+<user>@users.noreply.github.com`, make the repo public, or upgrade to Pro.

**Deployment Protection:** new Vercel projects require a Vercel login to view deployments. Disable *Vercel Authentication* under Settings → Deployment Protection to make the dashboard public.
