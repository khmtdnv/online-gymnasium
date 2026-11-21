#!/bin/sh
# Ночная резервная копия: PostgreSQL, ClickHouse и файлы MinIO.
# Запускается cron'ом от root (см. deploy/public/README-runbook.md).
# Результат: /opt/online-gymnasium-backups/nightly/<дата>/, хранение 7 дней.
set -eu

LOG=/var/log/online-gymnasium-backup.log
ROOT=/opt/online-gymnasium
DAY=$(date +%F)
DIR=/opt/online-gymnasium-backups/nightly/$DAY

echo "=== $(date -Is) старт копии $DIR" >> "$LOG"
mkdir -p /opt/online-gymnasium-backups/nightly
# Повторный запуск в тот же день начинает с чистого каталога
rm -rf "$DIR"
cd "$ROOT"

python3 tools/backup_postgres.py "$DIR" >> "$LOG" 2>&1

CH_NAME="nightly-$(date +%Y%m%d)"
python3 tools/backup_clickhouse.py "$CH_NAME" >> "$LOG" 2>&1
# ClickHouse пишет в backups/backups/<имя>.zip (путь File() относительно корня копий)
docker cp "online-gymnasium-analytics-clickhouse-1:/var/lib/clickhouse/backups/backups/$CH_NAME.zip" "$DIR/clickhouse-$CH_NAME.zip" >> "$LOG" 2>&1
docker exec "online-gymnasium-analytics-clickhouse-1" rm "/var/lib/clickhouse/backups/backups/$CH_NAME.zip" >> "$LOG" 2>&1

for volume in online-gymnasium_homework_minio_data online-gymnasium_document_minio_data; do
    docker run --rm -v "$volume":/data:ro -v "$DIR":/backup caddy:2 \
        tar czf "/backup/$volume.tar.gz" -C / data >> "$LOG" 2>&1
done

find /opt/online-gymnasium-backups/nightly -maxdepth 1 -mindepth 1 -mtime +6 -type d -exec rm -rf {} +

echo "=== $(date -Is) готово; файлы:" >> "$LOG"
ls -lh "$DIR" >> "$LOG"
df -h / | tail -1 >> "$LOG"
