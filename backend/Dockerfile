FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# ffmpeg: rendering/QA · espeak-ng: free multilingual TTS · Noto fonts: Indic/Arabic captions
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng fonts-noto-core fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 studio && mkdir -p /data/storage && chown -R studio /data /app
USER studio
ENV STORAGE_DIR=/data/storage
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["api"]
