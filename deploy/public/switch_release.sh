#!/bin/sh
# Переключает работающий сайт на указанный релиз-снимок одной командой.
# Использование: switch_release.sh release-YYYYMMDD
# Перед переключением снимает копию баз; откат — повторный вызов с прежним именем.
set -eu

NAME=${1:?укажите имя релиза, например release-20261120}
ROOT=/opt/online-gymnasium
RELEASES=/opt/online-gymnasium-releases
OVERRIDE=$ROOT/deploy/public/compose.release-current.yaml

test -d "$RELEASES/$NAME" || { echo "нет каталога $RELEASES/$NAME" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M)
echo "1/4: копия баз перед переключением..."
cd "$ROOT"
python3 tools/backup_postgres.py "/opt/online-gymnasium-backups/before-switch-$STAMP"

echo "2/4: override -> $NAME"
cat > "$OVERRIDE" <<YAML
services:
  frontend:
    volumes:
      - $RELEASES/$NAME/client:/usr/share/nginx/html:ro
  gateway-api:
    volumes:
      - $RELEASES/$NAME/services/gateway/src:/app/src:ro
  homework-api:
    volumes:
      - $RELEASES/$NAME/services/homework/src:/app/src:ro
  backoffice-api:
    volumes:
      - $RELEASES/$NAME/services/backoffice/src:/app/src:ro
  backoffice-static:
    volumes:
      - $RELEASES/$NAME/services/backoffice/src:/app/src:ro
YAML

echo "3/4: перезапуск стека..."
timeout 480 docker compose -f compose.yaml -f deploy/public/compose.public.yaml -f "$OVERRIDE" up -d

echo "4/4: проверка..."
sleep 10
curl -sSI https://online-education.fun/ -o /dev/null -w "сайт: %{http_code}\n"
echo "готово: $NAME. Откат: $0 прежнее-имя-релиза"
