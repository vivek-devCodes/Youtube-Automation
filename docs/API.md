# REST API (v1)

Interactive OpenAPI docs: **http://localhost:8000/api/docs** (JSON at `/api/openapi.json`).

Auth: an httpOnly cookie `studio_session` is set by `/auth/login` or `/auth/register`. `Authorization: Bearer <token>` is also accepted. Roles: `viewer` (read) < `editor` (produce/approve) < `admin` (settings, providers, channels, users). Errors are `{"detail": "..."}` with 400/401/403/404/409/422/429. A budget refusal is 402 `{"code":"budget_exceeded"}`.

| Method & path | Role | Purpose |
|---|---|---|
| `GET /auth/status` | — | `needs_setup`, `google_oauth_configured` |
| `POST /auth/register` | — | First account only (becomes admin) |
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` | — | Session |
| `POST /auth/users?role=` | admin | Add a user |
| `POST /auth/google` | admin | Google consent URL |
| `GET /auth/youtube/callback` | — | OAuth redirect target (signed state) |
| `GET/PATCH /onboarding` · `GET /onboarding/summary` · `POST /onboarding/complete` | admin | Wizard state; completion requires `confirm: true` |
| `GET /channels` · `GET /channels/{id}` | viewer | Channels with settings, brand, niches |
| `POST /channels/connect` | admin | `{mode: "google"}` → consent URL; `{mode: "sandbox"}` → practice channel |
| `PATCH /channels/{id}` | admin | Settings / brand / niches / automation switch |
| `POST /channels/{id}/brand/{logo\|banner}` | admin | Upload brand art |
| `DELETE /channels/{id}` | admin | Disconnect + revoke Google tokens |
| `GET /trends?channel_id&status&niche&source&min_score` | viewer | Scored trends |
| `POST /trends/scan` | editor | Queue a scan |
| `POST /trends/{id}/approve` | editor | `{format, title, start_production, review_script}` → run |
| `POST /trends/{id}/reject` · `POST /trends/{id}/ideas` | editor | Reject / generate original angles |
| `POST /content/generate` | editor | From `trend_id` or a free `topic` |
| `GET /content` · `GET /content/{run_id}` | viewer | Runs; detail includes sources, scenes, assets, provenance, compliance |
| `PATCH /content/{run_id}` | editor | Edit scenes/metadata (resets only affected steps) |
| `POST /content/{run_id}/script-decision` · `/retry` · `/cancel` | editor | Human gates & recovery |
| `POST /videos/render` | editor | Re-render a run (reuses assets) |
| `GET /videos?format&status&channel_id` · `GET /videos/{id}` | viewer | Library, jobs, history, analytics |
| `POST /videos/{id}/quality-check` | editor | Re-run QA |
| `GET /media/{key}` | viewer | Authenticated media (video, images, audio, SRT) |
| `POST /publishing/upload` | editor | Approve + upload now `{video_id, privacy}` |
| `POST /publishing/schedule` | editor | Approve for public release `{video_id, publish_at?}` |
| `GET /publishing/history` · `GET /publishing/jobs` | viewer | Audit trail / jobs |
| `POST /publishing/jobs/{id}/retry` · `/cancel` | editor | Recovery |
| `GET /approvals` · `POST /approvals/{id}/decide` | viewer / editor | Approval queue |
| `GET /analytics/overview?days` · `/analytics/videos` · `/analytics/channels` | viewer | Charts & tables |
| `POST /analytics/collect` | editor | Collect now + optimise |
| `GET /automation/status` · `POST /automation/start` · `/pause` · `/resume` | viewer / admin / editor / admin | Global control |
| `GET/PATCH /settings` | viewer / admin | Budget, weights, thresholds, unattended publishing (needs `confirm_unattended`) |
| `GET /providers` · `PATCH /providers/{id}` · `POST /providers/{id}/test` | viewer / admin / editor | Provider config; keys write-only |
| `GET /usage` · `POST /usage/estimate` | viewer | Costs per provider/day/video; per-video estimate |
| `GET /notifications` · `POST /notifications/read` | viewer | In-app notifications |
| `GET /audit-logs` | admin | Audit trail |
| `GET /dashboard` · `GET /meta/catalog` | viewer / — | Dashboard & catalogs |
| `GET /health` · `GET /health/ready` · `GET /metrics` | — | Liveness, readiness, Prometheus |

All paths above are prefixed with `/api/v1`, except `/health*` and `/metrics`.
