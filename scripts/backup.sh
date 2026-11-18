#!/usr/bin/env bash
# Back up PostgreSQL + generated media from the Docker Compose stack into ./backups/<timestamp>/
set -euo pipefail
cd "$(dirname "$0")/.."
TS=$(date +%Y%m%d-%H%M%S); OUT="backups/$TS"; mkdir -p "$OUT"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-studio}" "${POSTGRES_DB:-studio}" | gzip > "$OUT/db.sql.gz"
VOL=$(docker volume ls -q | grep '_media$' | head -1)
docker run --rm -v "$VOL":/data -v "$PWD/$OUT":/b alpine tar czf /b/media.tgz -C /data .
echo "Backup written to $OUT (remember: ENCRYPTION_KEY is needed to restore tokens/keys)"
