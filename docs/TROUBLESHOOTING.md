# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **"Connect with Google" is greyed out** | `GOOGLE_CLIENT_ID/SECRET` not set. See SETUP_GOOGLE.md, then restart the backend. |
| `redirect_uri_mismatch` from Google | The redirect URI in Cloud Console must equal `PUBLIC_BASE_URL/api/v1/auth/youtube/callback` exactly (scheme, host, port). |
| Channel must be reconnected every week | OAuth app is in *Testing* mode, where refresh tokens last 7 days. Publish the consent screen. |
| Uploaded videos are stuck private | Unaudited API projects can only upload private videos. Request a YouTube API audit (SETUP_GOOGLE.md). |
| "Thumbnail failed" in publishing history | Custom thumbnails need a phone-verified channel: youtube.com/verify. |
| "YouTube quota reached" | Daily quota is used up. Uploads auto-retry after 6 hours. Reduce scans/niches or request more quota. |
| Run failed at **research**: "No reliable sources" | The topic was too obscure, or there was no internet. Pick a clearer topic or retry. |
| Run failed at **originality** | The script stayed too close to a source/reference after 2 rewrites. Use a better LLM, or retry from `script`. |
| Run failed at **qa** | Open the run: the QA card lists each failed check. Common causes are missing narration (TTS not configured), silent audio, or wrong aspect ratio. |
| Scripts look like "First up: … and …" | You're on the **offline template generator** (test provider). Configure Ollama or a cloud LLM in AI Configuration. |
| Hindi/Tamil captions show boxes | The font isn't installed. Docker includes Noto fonts. On Linux run `apt install fonts-noto-core`. Windows uses Nirmala UI. |
| Robotic voice | The system voice is basic. Use Kokoro (free) or a cloud TTS. |
| Ollama test: "model not pulled" | Run `ollama pull <model>` and make sure the model name in AI Configuration matches. |
| From Docker, Ollama is unreachable | Use `http://host.docker.internal:11434` as the base URL. |
| "Paid generation paused: budget limit" | The monthly limit was reached. Raise it in Settings (paused runs resume) or wait for next month. |
| Dashboard "Worker down" | Inline mode: restart the backend. Celery: `docker compose logs worker`. |
| Nothing happens automatically | Automation is paused (top bar), the channel's Automation switch is off, or no topics are approved. |
| Reset everything (dev) | Stop the backend and delete `storage/studio.db` and `storage/videos`. |

Logs are JSON lines on stdout (`docker compose logs -f backend worker`). Each run's failing step shows its error and stack trace in Content Studio.
