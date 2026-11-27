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
  schedule-api:
    volumes:
      - $RELEASES/$NAME/services/schedule/src:/app/src:ro
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
# Готовность ждём только у сервисов из только что сгенерированного override
# (не весь стек: медленный ClickHouse не должен блокировать переключение).
# Список берём из самого override, а не вторым захардкоженным перечнем.
SERVICES=$(python3 - "$OVERRIDE" <<'PY'
import re
import sys

names = []
in_services = False
with open(sys.argv[1], encoding="utf-8") as fh:
    for line in fh:
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9._-]+):\s*$", line)
        if m:
            names.append(m.group(1))
        elif line.strip() and not line.startswith(" "):
            break
print(" ".join(names))
PY
)
[ -n "$SERVICES" ] || { echo "не найдены сервисы в $OVERRIDE" >&2; exit 1; }
echo "ожидание готовности (до 300 c, шаг 10 c): $SERVICES"

# Готовность: State == running и, если у сервиса определён healthcheck,
# Health == healthy. Таймаут 300 c, шаг 10 c; при истечении — ненулевой
# выход со списком неготовых сервисов.
WAITED=0
NOT_READY=""
while [ "$WAITED" -lt 300 ]; do
    PS_JSON=$(docker compose -f compose.yaml -f deploy/public/compose.public.yaml -f "$OVERRIDE" ps --format json)
    NOT_READY=$(SERVICES="$SERVICES" PS_JSON="$PS_JSON" python3 <<'PY'
import json
import os


def pick(entry, key):
    if key in entry:
        return entry[key]
    return entry.get(key.lower())


wanted = os.environ.get("SERVICES", "").split()
raw = os.environ.get("PS_JSON", "").strip()
entries = []
try:
    if raw:
        parsed = json.loads(raw)
        # новые версии docker compose дают массив объектов,
        # старые — по одному объекту JSON на строку
        entries = parsed if isinstance(parsed, list) else [parsed]
except ValueError:
    try:
        entries = [json.loads(part) for part in raw.splitlines() if part.strip()]
    except ValueError:
        entries = []

state = {}
for entry in entries:
    if isinstance(entry, dict):
        name = pick(entry, "Service")
        if name:
            state[name] = entry

not_ready = []
for svc in wanted:
    entry = state.get(svc)
    if entry is None:
        not_ready.append(svc + ": нет в docker compose ps")
        continue
    container_state = pick(entry, "State")
    health = pick(entry, "Health")
    # Health нет или пуст — healthcheck не определён; иначе ждём healthy.
    if container_state != "running":
        not_ready.append(svc + ": State=" + str(container_state))
    elif health not in (None, "", "healthy"):
        not_ready.append(svc + ": Health=" + str(health))
print("\n".join(not_ready))
PY
)
    if [ -z "$NOT_READY" ]; then
        break
    fi
    WAITED=$((WAITED + 10))
    if [ "$WAITED" -lt 300 ]; then
        sleep 10
    fi
done

if [ -n "$NOT_READY" ]; then
    echo "готовность не достигнута за 300 c, не готовы:" >&2
    printf '%s\n' "$NOT_READY" >&2
    exit 1
fi

curl -sSI https://online-education.fun/ -o /dev/null -w "сайт: %{http_code}\n"
echo "готово: $NAME. Откат: $0 прежнее-имя-релиза"
