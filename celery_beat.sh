#!/bin/bash
set -e

echo "=> Waiting for services..."
sleep 8

echo "=> Starting Celery Beat (Scheduler)..."
exec celery -A app.tasks.email_tasks.celery_app beat \
    --loglevel=info \
    --schedule=/tmp/celerybeat-schedule
