#!/usr/bin/env sh
# VIAHIND Vision backup: database dump + evidence snapshots, with retention.
#
#   sh deploy/backup.sh [backup dir]            (default ./backups, keeps 14 days)
#   cron (daily 02:30):  30 2 * * * cd /opt/viahind_vision && sh deploy/backup.sh /mnt/backup >> backups.log 2>&1
#
# Copy the backup directory off this machine as well (another disk, NAS or cloud storage):
# a backup on the same disk does not survive a disk failure or theft of the machine.
#
# Restore:
#   gunzip -c db-<stamp>.sql.gz | docker compose exec -T db psql -U viahind -d viahind_vision
#   docker compose exec -T backend tar xzf - -C /app < storage-<stamp>.tar.gz
set -eu

DEST="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

mkdir -p "$DEST"
echo "[$(date)] backup to $DEST"

$COMPOSE exec -T db pg_dump -U viahind -d viahind_vision --clean --if-exists | gzip > "$DEST/db-$STAMP.sql.gz"
# Evidence snapshots and trained ML artefacts (model weights are in ./models and re-copied on deploy).
$COMPOSE exec -T backend tar czf - -C /app storage > "$DEST/storage-$STAMP.tar.gz"

# backend/.env holds SECRET_KEY: without it, stored mail/Telegram settings cannot be decrypted.
cp backend/.env "$DEST/backend-env-$STAMP" && chmod 600 "$DEST/backend-env-$STAMP"

find "$DEST" -name 'db-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'storage-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'backend-env-*' -mtime +"$KEEP_DAYS" -delete
echo "[$(date)] done: $(du -sh "$DEST" | cut -f1) in $DEST"
