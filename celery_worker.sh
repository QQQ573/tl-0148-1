#!/bin/bash
set -e

echo "=> Waiting for services..."
sleep 5

echo "=> Starting Celery Worker..."
exec celery -A app.tasks.email_tasks.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    -Q celery \
    --pool=prefork
