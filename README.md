# Online Gymnasium Core

Имя каталога и Docker Compose-проекта: `online-gymnasium`.
Для **нового checkout без существующих env-файлов и Docker-томов** один раз
подготовьте локальные настройки. Команда генерирует разные парные секреты,
не выводит их и не перезаписывает существующие файлы:

```bash
python3 tools/init_local_env.py
```

Не запускайте её для замены настроек существующей установки: новые пароли не
изменяют пароли в уже созданных базах. После подготовки из корня проекта весь
стек запускается командой:

```bash
docker compose up --build -d
```

Портал: http://localhost:8080. Имя Compose-проекта задано явно в `compose.yaml`,
поэтому переименование родительского каталога не переключает хранилища.

## Текущее состояние демо

Проект объединяет портал на React и сервисы Gateway, Backoffice, Schedule,
Journal, Homework, Analytics, Pen, Billing, Documents и Notifications.
У сервисов собственные процессы и хранилища; пользователи работают через портал,
а сотрудники также используют Django-админку. Для явно связанных аккаунтов
переход из портала в админку не требует повторного входа; отдельный локальный
вход Django сохранён как резервный.

Основной сценарий: сотрудник назначает ученика в класс, преподаватель задаёт
домашнюю работу к уроку, ученик сдаёт её, преподаватель проверяет и выставляет
оценку. Есть файлы, уведомления, учебная умная ручка, PDF-документы, отчёт
успеваемости и общий журнал событий.

В проекте реализован адаптер **тестовой** ЮKassa. Для настоящей проверки нужны
ключи тестового магазина; без них успешный платёж и возврат не подтверждены.
Текущая конфигурация рассчитана на локальный запуск и не готова для открытого
доступа из интернета. Подробности: [запуск и ограничения](deploy/web/README.md).

Локальная демо-школа описана в `.demo-data/README.md`, если данные уже созданы.
Для расширенного набора (классы 1–11 А–Д, по 10 учеников и расписание на
текущую и следующую учебные недели) при запущенных сервисах выполните:

```bash
python3 tools/create_demo_data.py --large          # посмотреть план
python3 tools/create_demo_data.py --large --apply  # добавить недостающие данные
```

Скрипт не удаляет существующие записи и не меняет пароли; при конфликте с
существующим назначением ученика он останавливается. Результат и демо-логины
записываются в `.demo-data/expanded-school.json`. Тестовые аккаунты и пароль
предназначены только для локальной разработки, не для открытого сервера.
Преподаватели предметов распределены между несколькими классами с проверкой
пересечений; адреса перечислены в `subject_teachers` отчёта. Демо-уроки прежней
версии скрипта обновляются с сохранением ID и отправкой событий изменения;
изменённые вручную уроки скрипт пропускает.
Проверить запущенные роли и основные чтения можно из корня проекта:

```bash
poetry -C services/gateway run python ../../tools/verify_portfolio.py
```

При проверке создаются и затем отзываются только собственные тестовые сессии.
Разделы ниже частично сохраняют исторические инструкции отдельных этапов и могут
описывать прежнее состояние, а не все возможности текущего приложения.

Добавлен React/TypeScript frontend в `services/frontend`: русский портал,
расписание, нагрузка и справки в палитре «бирюза и персик». Единый локальный
вход — `http://localhost:8080`; [запуск и границы](deploy/web/README.md).
Gateway реализует logout и проверку Origin для входа и обновления сессии.
Browser UI-тесты с тестовыми API не заменяют проверку полного стека.

## Journal: классы

Journal хранит школьные классы и предоставляет защищённые служебные ручки
создания и списка. Запуск: `docker compose up --build -d journal-api`;
локальный API: `http://127.0.0.1:8005`.
Состав классов и назначения преподавателей используются порталом и Backoffice;
проверенные оценки собираются в отчёт Analytics.

## Gateway и Backoffice: текущий срез

Gateway владеет пользователями учебной платформы, refresh-токенами и связями
родителей с учениками. Backoffice хранит сотрудников Django и журнал их действий;
продуктовых пользователей создаёт только через закрытый HTTP API Gateway.

Реализованы:

- вход, проверка текущего пользователя и одноразовая ротация refresh JWT;
- Argon2-хеши паролей, access JWT в JSON, refresh JWT в HttpOnly-cookie;
- закрытые команды создания/чтения пользователей и привязки родителя к ученику;
- страницы Django Admin для создания пользователя и привязки, журнал действий;
- переиспользуемая проверка разрешённых ролей, проверенная на тестовом маршруте;
- отдельные базы данных, миграционные контейнеры, проверки здоровья Gateway.

Это описание ограничено Gateway и Backoffice. Домашние задания и чтение данных
ребёнка родителем реализованы отдельно; справочники `academic_groups` и
`feature_flags` в Backoffice в минимальное демо не входят.

## Локальный запуск Gateway и Backoffice

Нужны Docker Compose и Poetry. Для локальных Python-команд используйте Python
3.14 и отдельное окружение каждого проекта. Не запускайте установку одного сервиса
из активированного окружения другого.

Из корня репозитория создайте отсутствующие локальные env-файлы по примерам:

```bash
cp -n services/gateway/.env.example services/gateway/.env
cp -n services/gateway/.postgres.env.example services/gateway/.postgres.env
cp -n services/backoffice/.env.example services/backoffice/.env
cp -n services/backoffice/.postgres.env.example services/backoffice/.postgres.env
```

Заполните приватные значения в редакторе:

- Gateway: длинный случайный `JWT_SECRET` и отдельный `BACKOFFICE_SERVICE_TOKEN`.
- Backoffice: приватный `BACKOFFICE_SECRET_KEY`; значение
  `BACKOFFICE_GATEWAY_SERVICE_TOKEN` должно совпадать с токеном Gateway.
- Адрес Gateway из Backoffice: `http://gateway-api:8000`.
- `BACKOFFICE_DB_*` должны соответствовать `.postgres.env` Backoffice;
  контейнерный host — `backoffice-postgres`, port — `5432`.
- `DATABASE_URL` Gateway в `.env` содержит готовый контейнерный адрес
  `gateway-postgres:5432`. Пользователь, пароль и имя БД должны совпадать с
  `.postgres.env`. Локальный адрес PostgreSQL с хоста — `127.0.0.1:5434`.

Compose читает общий файл конфигурации, включая env-файлы остальных сервисов.
Если это новый checkout, проще сначала выполнить `python3 tools/init_local_env.py`
из инструкции выше: Compose проверяет env-файлы всех сервисов, а сервисные
токены и пароли баз должны совпадать у обеих сторон. Скрипт не предназначен для
частично настроенной установки и при обнаружении любого env-файла остановится.

Env-файлы не коммитятся. Пароли примеров предназначены только для локальной
разработки. Изменение `POSTGRES_PASSWORD` в env не меняет пароль в уже созданной
базе: не удаляйте тома ради перенастройки без проверки сохранённых данных.

```bash
docker compose config --quiet
docker compose up --build -d gateway-api backoffice-api
docker compose ps -a gateway-postgres gateway-migrations gateway-api backoffice-postgres backoffice-migrations backoffice-api
curl -i http://127.0.0.1:8003/health/live
curl -i http://127.0.0.1:8003/health/ready
docker compose exec backoffice-api poetry run python manage.py createsuperuser
```

Успешные миграционные контейнеры завершаются с кодом 0; API продолжают работать.
`/health/live` проверяет ответ HTTP-процесса, `/health/ready` — доступность БД.

Откройте `http://127.0.0.1:8010/admin/` и войдите сотрудником Django. На главной
есть ссылки `/admin/create-user/` и `/admin/link-parent-student/`.
Создайте тестовых teacher, student и parent. Получите ID без чтения хешей паролей:

```bash
docker compose exec gateway-postgres psql -U gateway -d gateway -c \
  "SELECT id, email, role FROM users ORDER BY created_at DESC LIMIT 10;"
```

Отправьте привязку parent/student дважды. Первый результат — `created`, второй —
`already_exists`. В журнале Backoffice обе попытки успешны, а в Gateway одна пара:

```bash
docker compose exec gateway-postgres psql -U gateway -d gateway -c \
  "SELECT parent_id, student_id FROM parent_student_links;"
```

## Правило конфигурации сервисов

В env-файлах приложения хранятся готовые адреса внутри Docker-сети:
`schedule-postgres:5432`, `gateway-postgres:5432`, `document-postgres:5432`,
`journal-postgres:5432`, `schedule-redis:6379`, `schedule-kafka:19092`.
Команды приложения в Compose только запускают процесс — не собирают URL и не
подменяют настройки. Env-файлы инфраструктуры (`.postgres.env`, `.kafka.env`,
`.minio.env`, `.rabbitmq.env`, `.clickhouse.env`) задают настройки её контейнеров.
Учётные данные ClickHouse также передаются клиентам Analytics через env-файл.

Schedule и Analytics получают дополнительные настройки воркеров из `.worker.env`.
В новом checkout создайте файл Schedule из `.worker.env.example`. API Schedule
не получает этот файл: Kafka нужна его воркерам, а не HTTP-процессу.

Полный URL БД дублирует учётные данные из `.postgres.env`. При смене пользователя,
пароля или имени БД согласуйте оба файла. Спецсимволы в пользователе и пароле URL
нужно percent-encode; обычные поля `.postgres.env` остаются без URL-кодирования.

Для разовой локальной проверки не переписывайте `.env`: заменяйте только хост и
порт в настройках текущего процесса. Например, в Python используйте
`make_url(settings.database_url).set(host="127.0.0.1", port=5436)` для Journal,
затем `render_as_string(hide_password=False)` для передачи URL в engine.
Не выводите этот URL в терминал: он содержит пароль.

Shell-команды healthcheck и создания бакета MinIO остаются: это операции с
инфраструктурой, а не сборка настроек Python-приложения. `$$` в них защищает
переменные от подстановки Compose — значения читает shell внутри контейнера.
Dev/production overrides могут явно менять флаги режима, например Django DEBUG.

## Проверка login → me → refresh → replay

Ниже команды для Fish, из корня репозитория. Сначала установите зависимости
Gateway через `poetry -C services/gateway install`, если окружения ещё нет.
Не публикуйте сохранённые cookie, access JWT и ответы login/refresh.

```fish
set auth_dir (mktemp -d)

poetry -C services/gateway run python -c \
  'import json,sys,getpass; sys.stderr.write("Email: "); email=input(); print(json.dumps({"email":email,"password":getpass.getpass("Пароль: ")}))' \
  | curl -sS -H "Content-Type: application/json" \
      -H "Origin: http://localhost:8080" --data-binary @- \
      -c "$auth_dir/old.cookies" -o "$auth_dir/login.json" \
      -w "Login: %{http_code}\n" \
      http://127.0.0.1:8003/api/v1/auth/login
```

Введите данные тестового ученика в приглашениях. Пароль не записывается в саму
команду. Продолжайте только после `Login: 200`:

```fish
set access_token (poetry -C services/gateway run python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' \
  "$auth_dir/login.json")

curl -sS -H "Authorization: Bearer $access_token" \
  -w "\nMe: %{http_code}\n" http://127.0.0.1:8003/api/v1/auth/me

curl -sS -X POST -b "$auth_dir/old.cookies" \
  -H "Origin: http://localhost:8080" \
  -c "$auth_dir/new.cookies" -o "$auth_dir/refresh.json" \
  -w "Refresh: %{http_code}\n" http://127.0.0.1:8003/api/v1/auth/refresh

curl -sS -X POST -b "$auth_dir/old.cookies" \
  -H "Origin: http://localhost:8080" \
  -w "\nReplay: %{http_code}\n" http://127.0.0.1:8003/api/v1/auth/refresh
```

Ожидаем `Me: 200`, `Refresh: 200`, `Replay: 401`. Старый файл cookie намеренно
не перезаписываем. Для проверки БД замените `STUDENT_UUID` на ID из `/me`:

```bash
docker compose exec gateway-postgres psql -U gateway -d gateway -c \
  "SELECT id, created_at, expires_at, consumed_at FROM refresh_tokens
   WHERE user_id = 'STUDENT_UUID' ORDER BY created_at;"
```

После одного login и refresh появятся две записи: старая с `consumed_at`, новая
без него. Отклонённый replay не добавляет запись. Если ученик входил ранее,
записей может быть больше. Этот сценарий подтверждён пользователем на реальных
контейнерах 2026-10-02: HTTP 200/200/200/401 и две соответствующие строки БД.

После проверки удалите секретные временные файлы и сам пустой каталог:

```fish
rm "$auth_dir/login.json" "$auth_dir/refresh.json" "$auth_dir/old.cookies" "$auth_dir/new.cookies"
rmdir "$auth_dir"
set -e access_token
set -e auth_dir
```

## Автоматические проверки

```bash
poetry -C services/gateway run pytest -q
poetry -C services/gateway run ruff check .
poetry -C services/gateway run ruff format --check .
poetry -C services/backoffice run pytest -q
poetry -C services/backoffice run ruff check .
poetry -C services/backoffice run ruff format --check .
docker compose config --quiet
```

Backoffice-тесты используют SQLite и заменяют HTTP-транспорт Gateway; они не
доказывают работу реального PostgreSQL или сетевого соединения. Для этого нужен
описанный выше сценарий Compose.

Текущий Compose — локальный учебный режим, не production deployment: базовый
Backoffice запускается через Gunicorn, dev override — через runserver с hot reload.
HTTPS и Secure-cookie для публичного размещения ещё не настроены. Служебный токен защищает private API;
скрытие маршрутов из OpenAPI само по себе защитой не является.
