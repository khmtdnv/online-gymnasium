# Runbook: сервер online-education.fun

Краткая инструкция по операциям. Подробности устройства — в `README.md` рядом.

## Доступ

- SSH: `ssh ogadmin@31.77.222.136` (ключ) или `ssh root@31.77.222.136` (только ключ).
- Парольный вход SSH полностью отключён (`/etc/ssh/sshd_config.d/00-hermes-hardening.conf`).
- Консоль хостера — запасной путь; проверить её работу может только владелец аккаунта хостера.
- Откат SSH-настроек: `rm /etc/ssh/sshd_config.d/00-hermes-hardening.conf && systemctl reload ssh`
  (исходный бэкап: `/etc/ssh/sshd_config.bak-hermes`).

## Выпуск с изменёнными сервисами

1. Локально — тесты и сборка зелёные, изменения закоммичены. Перед первым выпуском сетки
   владелец повторяет drill восстановления на свежем nightly-дампе
   (раздел «Восстановление PostgreSQL» этого файла).
2. При подготовке снимка — загрузить его на сервер и записать в каталог снимка
   `RELEASE-CHANGED-SERVICES.txt`, детерминированный список изменённых сервисов.
   Загрузка (каталог `client/` — собранный фронтенд из `services/frontend/build/client`):
   `rsync -rc --exclude node_modules --exclude .git --exclude .venv --exclude __pycache__ --exclude .demo-data ./ ogadmin@31.77.222.136:/opt/online-gymnasium-releases/release-<дата>/`
   Список изменённых сервисов (команду выполняет владелец при сборке снимка):
   `git diff --name-only <коммит-предыдущего-релиза>..<коммит-нового> -- services/ > RELEASE-CHANGED-SERVICES.txt`
   Существующий `RELEASE-MANIFEST.txt` (идентификаторы образов текущего релиза) сохраняет
   своё значение и не меняется.
3. Сверка: каждый сервис из `RELEASE-CHANGED-SERVICES.txt` смонтирован в override
   (`compose.release-current.yaml` генерируется `switch_release.sh` на сервере
   и в git не хранится). Образы на сервере не пересобираются (docker.io
   недоступен), поэтому `switch_release.sh` дополнительно монтирует
   `services/schedule/migrations` в `schedule-migrations`: alembic-цепочка
   бежит из релиз-кода, а не из устаревшего образа. Одноразовые контейнеры
   (миграции, collectstatic) из ожидания готовности исключены: их успех
   проверяет compose через `depends_on`, а не цикл готовности.
4. Бэкап баз шагом скрипта (`before-switch-<метка>` создаёт сам `switch_release.sh`):
   на сервере `sudo /opt/online-gymnasium/deploy/public/switch_release.sh release-<дата>`
   — снимет копию баз, переключит override, перезапустит стек, дождётся готовности
   контейнеров и проверит https. Если планируется `--apply` переноса — до переключения
   снимок `before-grid-<дата>`:
   `python3 tools/backup_postgres.py /opt/online-gymnasium-backups/before-grid-<дата>`
   (раздел «Legacy-уроки» спецификации `docs/designs/stitch-migration.md`).
5. После `up -d` и health-ожидания — smoke через `https://online-education.fun`:
   `GET /` → 200; вход демо-учёткой преподавателя кнопкой «Учитель» на `/login`
   (`teacher01@demo.og.test`, публичный демо-пароль `DemoSchool2026!` — allowlist
   `.gitleaks.toml`; вход ≠ 200 → стоп, данные на проде не создаются
   и не изменяются) → 200; `GET /api/v1/my-schedule?week_start=<текущий понедельник>`
   → 200 и `periods.length === 7`. Перед первым выпуском с демо-входом — разовый
   шаг: сбросить пароли витринных демо-учёток (учитель/ученик/родитель) к
   `DemoSchool2026!` инструментом `tools/reset_demo_passwords.py` — он
   выполняется в контейнере gateway-api, отказывается трогать демо-админа
   и отзывает прежние сессии; `create_demo_data.py` пароли существующих
   учёток не меняет.
6. При неудаче после переключения — откат кода и данных одной процедурой:
   `switch_release.sh release-<прежняя>`; если в этом выпуске выполнялся `--apply` —
   восстановление баз из `before-grid-<дата>` (раздел «Восстановление PostgreSQL»);
   повтор smoke. Пост-проверка отката: вход → 200; `my-schedule` прежней версии → 200
   (если прежняя версия была до контракта периодов — поля `periods` в ответе нет;
   иначе `periods.length === 7`);
   `GET /api/v1/schedule/lessons?class_id=<демо-класс>&date=<школьная дата>`
   под администратором → непустой список. Результат фиксируется в отчёте выпуска.

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

## Обновление демо-данных (годовое расписание)

Полная пересборка демо-школы на весь учебный год — спецификация
`docs/designs/demo-year-timetable.md`. Точка входа одна:
`python3 tools/create_demo_data.py --large --apply` из корня репозитория
(на сервере — `/opt/online-gymnasium`); годовой сценарий (очистка → запись →
проверки) выполняет `tools/rebuild_demo_timetable.py`: сценарии ДЗ → уроки
с ключами идемпотентности `demo-year-<год>-<класс>-<дата>-<период>` →
верификация пустоты → запись чанками класс-недель → `verify` по всему году.
Полная генерация — до 15 минут; на время очистки и записи школа пуста —
выбирать тихое окно. Отпечаток года (`{grid_version, calendar_version,
curriculum_hash, study_year}` в `.demo-data/expanded-school.json`) делает
повторный прогон без изменений пустым: уроки не трогаются, сценарии ДЗ
пересоздаются.

1. **Бэкап** до любых действий — существующим инструментом (как снимок
   `before-grid-<дата>` в шаге 4 раздела «Выпуск с изменёнными сервисами»):
   `cd /opt/online-gymnasium && python3 tools/backup_postgres.py /opt/online-gymnasium-backups/before-demo-year-<дата>`
   (восстановление — раздел «Восстановление PostgreSQL» этого файла).
2. **Наполнение** — один из двух вариантов; окончательный выбор за отдельной
   задачей, оба проходят одинаковую верификацию и smoke:
   - *Генерация года на целевом стеке*: на сервере
     `python3 tools/create_demo_data.py --large --apply`. Прогон создаёт
     ~52 тысячи уроков (51 565 после усечения коротких недель) и ~103 тысячи
     событий (2 события на урок); сценарии ДЗ и
     ответов пересоздаются поверх нового расписания. Сбой чанка записи
     останавливает прогон с отчётом незавершённых класс-недель — повторный
     запуск продолжает с места сбоя, а не начинает заново. Аналитика видит
     события всего года.
   - *Перенос дампа базы расписания*: снять на локальном стеке дамп базы
     Schedule (`pg_dump -Fc`, как в nightly-копиях) вместе с
     `.demo-data/expanded-school.json` (в нём отпечаток года), перенести на
     сервер, восстановить дамп в базу Schedule по разделу «Восстановление
     PostgreSQL», подчистить ключи дневного кэша расписания в Redis
     (класс-даты; те же, что удаляет режим `wipe` инструмента), затем
     запустить `python3 tools/create_demo_data.py --large --apply` — при
     совпадении отпечатка года это пустой прогон: уроки не трогаются,
     сценарии ДЗ пересоздаются на текущую учебную неделю. Быстрее и без
     всплеска ~90k событий, но аналитика не увидит историю года.
3. **Верификация**: `verify` по всему году входит в любой прогон инструмента
   (независимая проверка инвариантов по всем неделям года: конфликты
   учителей, «окна», точное совпадение периодов, пустые каникулы, дневные
   лимиты); после наполнения следить за потребителями событий, пока очередь
   outbox и лаги не обнулятся (норма — ≤ 10 минут, дольше — стоп-условие):
   `docker compose -f compose.yaml -f deploy/public/compose.public.yaml logs schedule-outbox-relay schedule-cache-invalidator analytics-worker`.
4. **Smoke** через `https://online-education.fun` (приёмы шага 5 раздела
   «Выпуск с изменёнными сервисами»): `GET /` → 200; вход демо-учёткой
   преподавателя кнопкой «Учитель» на `/login` (публичный демо-пароль
   `DemoSchool2026!`) → 200;
   `GET /api/v1/my-schedule?week_start=<текущий понедельник>` → 200,
   `periods.length === 7`, неделя преподавателя непуста — в любую учебную
   неделю года.
5. **Откат** — восстановление снимка из `before-demo-year-<дата>` (раздел
   «Восстановление PostgreSQL»), затем повтор smoke (шаг 4).

Ежегодный шаг (смена учебного года): обновить константы
`services/schedule/src/schedule_service/domain/school_calendar.py` на новый
учебный год (границы года, четверти, каникулы, праздники), поднять
`CALENDAR_VERSION` и перегенерировать год шагами 1–4 — изменившийся календарь
меняет отпечаток года, прогон сам уйдёт в полную пересборку.

Фикстура приёмки вне-сеточных уроков — только localhost (проверка
`REMAP_API_BASE` в самом инструменте; публичный стек она не трогает).
Порядок строгий, полная пересборка года — последней (иначе пересборка
удалит подсадку вместе со всеми уроками демо-классов):
`python3 tools/seed_legacy_offgrid_lessons.py` →
`python3 tools/remap_offgrid_lessons.py --dry-run` → `--apply` → `--check`
→ `python3 tools/seed_legacy_offgrid_lessons.py --clean` → только потом
полная пересборка года (шаги 1–4). Учётные записи и окружение вызова remap —
раздел «Legacy-уроки и `effective_from`» спецификации
`docs/designs/stitch-migration.md`.
