# Runbook: сервер online-education.fun

Краткая инструкция по операциям. Подробности устройства — в `README.md` рядом.

## Доступ

- SSH: `ssh ogadmin@31.77.222.136` (ключ) или `ssh root@31.77.222.136` (только ключ).
- Парольный вход SSH полностью отключён (`/etc/ssh/sshd_config.d/00-hermes-hardening.conf`).
- Консоль хостера — запасной путь; проверить её работу может только владелец аккаунта хостера.
- Откат SSH-настроек: `rm /etc/ssh/sshd_config.d/00-hermes-hardening.conf && systemctl reload ssh`
  (исходный бэкап: `/etc/ssh/sshd_config.bak-hermes`).

## Обновление сайта

1. Локально: тесты зелёные, изменения закоммичены.
2. Загрузить новый снимок:
   `rsync -rc --exclude node_modules --exclude .git --exclude .venv --exclude __pycache__ --exclude .demo-data ./ ogadmin@31.77.222.136:/opt/online-gymnasium-releases/release-<дата>/`
   (каталог `client/` — собранный фронтенд из `services/frontend/build/client`).
3. На сервере: `sudo /opt/online-gymnasium/deploy/public/switch_release.sh release-<дата>`
   — снимет копию баз, переключит override, перезапустит стек и проверит https.
4. Откат: `switch_release.sh release-прежняя-дата`.

Журнал релизов: `/opt/online-gymnasium-releases/RELEASES.log`,
идентификаторы образов текущего релиза: `RELEASE-MANIFEST.txt` в каталоге релиза.

## Резервные копии

- Ежедневно 03:30 MSK (`/etc/cron.d/online-gymnasium-backup`, скрипт `nightly-backup.sh`):
  дампы всех PostgreSQL, архив ClickHouse, tar файловых томов MinIO.
- Локация: `/opt/online-gymnasium-backups/nightly/<дата>/`, хранение 7 дней.
- Лог: `/var/log/online-gymnasium-backup.log`.
- Вне сервера: машина разработчика забирает `nightly/` по своему cron'у
  (`~/khmtdnv-hub/backups/online-gymnasium/`).

## Восстановление PostgreSQL (проверено 2026-11-20)

Дампы в формате pg_dump -Fc со созданием базы. Проверка в отдельном контейнере:

    docker run -d --name restore-drill -e POSTGRES_USER=gateway -e POSTGRES_PASSWORD=x postgres:18
    # дождаться стабильного pg_isready (образ перезапускается после initdb!)
    cat gateway-postgres.dump | docker exec -i restore-drill pg_restore -U gateway -C -d postgres -c
    docker exec restore-drill psql -U gateway -d gateway -tAc "select count(*) from users"
    docker rm -f restore-drill

Результат пробы 2026-11-20: 1169 пользователей восстановлено, 0 ошибок.

## Автозапуск

- `online-gymnasium-stack.service` (enabled) поднимает стек после перезагрузки,
  `online-gymnasium-public-route.service` восстанавливает исходящий адрес.
- Проверено реальной перезагрузкой 2026-11-20.
- После перезагрузки ClickHouse поднимается несколько минут: analytics-сервисы
  в это время перезапускаются — это норма.

## Мониторинг (что уже есть)

- UFW: снаружи открыты только 22, 80, 443.
- Сертификат Let's Encrypt обновляет Caddy автоматически (volume `public_caddy_data`).
- Проверка вручную: `curl -sI https://online-education.fun/`, логи `docker logs <имя>-1`.
- Внешний мониторинг доступности (UptimeRobot и т.п.) — не настроен, нужен аккаунт владельца.

## Что требует владельца

- 2FA на аккаунтах хостера, регистратора домена и GitHub.
- Проверка аварийной консоли хостера; после неё можно полностью запретить
  вход root (`PermitRootLogin no` вместо `prohibit-password`).
- Внешний мониторинг доступности и уведомления.
- Продление домена и оплата VPS.
