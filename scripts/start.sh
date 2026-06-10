#!/usr/bin/env bash
set -e

echo "==> A aplicar migrações..."
python manage.py migrate --noinput

echo "==> A recolher ficheiros estáticos..."
python manage.py collectstatic --noinput

echo "==> A iniciar Gunicorn na porta ${PORT:-8000}..."
exec gunicorn core.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
