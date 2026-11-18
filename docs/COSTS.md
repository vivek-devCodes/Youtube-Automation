# Costs, providers & hardware

Prices are **estimates** stored per model in *AI Configuration*, where you can edit them. Actual token counts are recorded whenever a provider reports them (`api_usage.estimated = false`). The budget guard checks the estimate **before** each paid call and refuses calls that would exceed your monthly limit.

## Modes

| Mode | LLM | Voice | Images | AI video | Typical cost per 45s Short |
|---|---|---|---|---|---|
| **A — Free / open-source** | Ollama (local) | espeak-ng / SAPI, Kokoro, Piper | Procedural motion graphics, ComfyUI | none / ComfyUI | $0 (your electricity) |
| **B — Low-cost hybrid** | Gemini Flash | system / Kokoro | procedural | none | ≈ $0.002–0.01 |
| **C — Balanced** | Claude (`claude-opus-5-5` default; switch to `claude-sonnet-5-5` or `claude-haiku-5-5` to save) | OpenAI TTS | OpenAI Images | none | ≈ $0.15–0.40 |
| **D — Premium** | Claude | OpenAI TTS | OpenAI Images | ComfyUI Wan/LTX (self-hosted GPU) | ≈ $0.30–0.60 + GPU |

A Short makes about 5 LLM calls (ideas, research, script, SEO, fact-check). Use **Estimate before producing** in AI Configuration for a figure based on your current providers.

## Hardware for local (free) generation

| Component | Minimum | Comfortable |
|---|---|---|
| Rendering (FFmpeg) | any 4-core CPU, 8 GB RAM (~5–20s render per 10s of video at 1080p) | 8 cores |
| Ollama 8B model | 8 GB free RAM (CPU, slow: 1–5 min per script) | 16 GB RAM or a 8 GB VRAM GPU |
| ComfyUI SDXL / Flux images | NVIDIA 8 GB VRAM | 12–16 GB |
| Wan 2.x / LTX-Video clips | NVIDIA 12 GB VRAM (small models, slow) | 24 GB VRAM |
| Kokoro TTS | CPU | — |

**On a laptop with integrated graphics** (like the one this was developed on), use procedural visuals and system/Kokoro voice, plus a cloud LLM or a small Ollama model. AI video clips are not practical there.

## Quick provider setups

- **Ollama**: install from https://ollama.com → `ollama pull llama3.1:8b` (or `qwen2.5:7b` for better Hindi) → AI Configuration → Ollama → Base URL `http://localhost:11434` (from Docker: `http://host.docker.internal:11434`) → Test → Use as default.
- **Kokoro**: `docker run -d -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu` → Base URL `http://localhost:8880`. English voices are best; check the voice list for other languages.
- **Piper**: `pip install piper-tts[http]` and `python -m piper.http_server -m en_US-lessac-medium` → Base URL `http://localhost:5000`. Each voice model has its own licence; check the model card.
- **ComfyUI**: build a workflow, use *Save (API format)*, replace the prompt/size/seed values with `{{prompt}}`, `{{width}}`, `{{height}}`, `{{seed}}` (and `{{frames}}` for video), then paste it into the provider card.
- **Claude / Gemini / OpenAI**: paste the API key into the provider card. It is encrypted and never displayed again.

## YouTube API
Free within the daily quota (see SETUP_GOOGLE.md). No money is charged. The quota is tracked separately from the AI budget.
