#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${API_WORKERS:-2}
    ;;
  worker)
    exec celery -A app.workers.celery_app worker -l info -Q default,render --concurrency ${WORKER_CONCURRENCY:-1}
    ;;
  beat)
    exec celery -A app.workers.celery_app beat -l info --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
