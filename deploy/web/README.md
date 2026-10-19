# Единый вход OG1

Локальный адрес: `http://localhost:8080`. Nginx разделяет маршруты:

- `/api/v1/` → Gateway. Ошибки API не заменяются SPA HTML; proxy не повторяет POST.
- `/admin/` → Django с его собственной staff-сессией.
- `/static/` → volume, заполненный one-shot `collectstatic`, read-only в proxy.
- `/internal/` → `404`, private API не доступен через web.
- остальные адреса → frontend, deep links возвращают `index.html`.

`nginx.dev.conf` вместо static frontend проксирует Vite с WebSocket HMR.
Common forwarded headers находятся в `proxy-headers.conf`: клиентские значения
заменяются, не добавляются к доверенным. `Host` проверяется whitelist Nginx
(`localhost`, `127.0.0.1`) и Django. Service token остаётся серверным.

## Сборка и окружение

Frontend image: Node 24.19.0/pnpm 11.25.0 только на этапе сборки; в финальном
image Nginx 1.30.5 и static files. Входной web image — отдельный Nginx.
Фиксированные версии и lock обеспечивают повторяемость; перед обновлениями
проверяйте peer requirements, тесты и security advisories.

Все диагностические ports базового Compose привязаны к loopback. Override
`compose.production.yaml` сбрасывает их через `!reset []`, отключает source
mounts Backoffice и использует Gunicorn. Единственный host port — web 8080,
тоже loopback. Требуется Compose с `!reset`/`!override` (проверено CLI 5.5.1).
Не выставляйте upstream services напрямую: сейчас их защита предполагает Gateway.

## Перед публичным размещением

Эта конфигурация **не является завершённым HTTPS deployment**:

1. Завершить учебные Gateway auth/Origin/logout и admin-only upstream routes.
2. Настроить TLS на доверенном ingress и конкретный публичный hostname в Nginx,
   убрать generic/default-host доступ. Не доверять forwarded headers из Интернета.
3. Настроить Gateway `PUBLIC_ORIGIN=https://...`, `SECURE_COOKIES=True` после
   реализации этих settings; добавить тот же origin в Django trusted origins,
   allowed hosts и `BACKOFFICE_SECURE_COOKIES=True`.
4. Если TLS завершается на ingress, изменить **доверенную цепочку proxy**:
   текущий local Nginx всегда передаёт свой `$scheme` (HTTP). Нельзя просто
   включить `BACKOFFICE_TRUST_PROXY=True` и ожидать HTTPS — ingress должен быть
   единственным сетевым источником, а Nginx должен выставлять проверенное `https`.
5. Отдельно проверить Host/CSRF/Secure-cookie, DB/backups, журналирование без
   токенов, ограничения ресурсов и healthchecks. Только затем публиковать web.

Не добавляйте `VITE_*` с паролями/токенами: они могут попасть в browser bundle.
Не делайте `docker compose down -v` ради смены режима — данные должны сохраняться.

Источники: [Nginx proxy headers](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header),
[Compose merge/reset](https://docs.docker.com/reference/compose-file/merge/),
[Django static deployment](https://docs.djangoproject.com/en/6.1/howto/static-files/deployment/).
