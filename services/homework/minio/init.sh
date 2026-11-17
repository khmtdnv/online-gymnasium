#!/bin/sh
# Инициализирует приватный bucket и отдельного пользователя приложения.
set -eu

: "${MINIO_ENDPOINT:?required}"
: "${MINIO_ROOT_USER:?required}"
: "${MINIO_ROOT_PASSWORD:?required}"
: "${MINIO_ACCESS_KEY:?required}"
: "${MINIO_SECRET_KEY:?required}"
: "${MINIO_BUCKET:?required}"

case "$MINIO_BUCKET" in
  *[!a-z0-9-]*|''|-*|*-) echo 'Invalid bucket name' >&2; exit 1 ;;
esac
if [ "${#MINIO_BUCKET}" -lt 3 ] || [ "${#MINIO_BUCKET}" -gt 63 ]; then
  echo 'Invalid bucket length' >&2
  exit 1
fi
if [ "$MINIO_ROOT_USER" = "$MINIO_ACCESS_KEY" ]; then
  echo 'Application must not use root credentials' >&2
  exit 1
fi

policy_file=$(mktemp)
trap 'rm -f -- "$policy_file"' EXIT
# В минимальном образе mc нет sed; каждая строка шаблона содержит не более
# одного BUCKET_NAME. Разрешённый DNS bucket не может внедрить JSON-синтаксис.
while IFS= read -r line; do
  case "$line" in
    *BUCKET_NAME*) printf '%s%s%s\n' "${line%%BUCKET_NAME*}" "$MINIO_BUCKET" "${line#*BUCKET_NAME}" ;;
    *) printf '%s\n' "$line" ;;
  esac
done < /init/policy.json > "$policy_file"

mc alias set homework "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing "homework/$MINIO_BUCKET"
mc anonymous set none "homework/$MINIO_BUCKET"
mc admin user add homework "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc admin policy create homework homework-files "$policy_file"
mc admin policy attach homework homework-files --user "$MINIO_ACCESS_KEY"
