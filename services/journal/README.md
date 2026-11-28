# Journal: классы, периоды и записи уроков

## Чтения Gateway для личного расписания

Входящий `GATEWAY_READ_SERVICE_TOKEN` — новая отдельная read-пара, которой
соответствует `JOURNAL_READ_SERVICE_TOKEN` в Gateway. Это не существующий
исходящий `GATEWAY_SERVICE_TOKEN` Journal для проверки пользователей.
Права нового principal: только `classes:read` и `student-current-class:read`.
Создавать классы, менять периоды или назначения этим токеном нельзя.
Совпадающие входящие сервисные секреты закрывают интеграцию с503.

`POST /internal/classes/lookup` получает уникальный пакет ID и возвращает классы
одним SQL-запросом. Текущий класс ученика читается через существующий endpoint
текущего периода. Копии пользователей и предметов в Journal не добавляются.

Первый срез электронного журнала: создание и список школьных классов,
текущий период ученика, его история и текущий состав класса.
Journal хранит классы в своей PostgreSQL-БД. Учётные записи принадлежат Gateway.

Команды, queries, результаты и данные событий — Pydantic DTO с проверкой при
создании. Доменные `Class` и `StudentClassPeriod` остаются независимыми dataclass.
[Общие правила DTO](../../DTO.md).
Хранение текущего членства и истории периодов описано отдельной миграцией.
Добавление, перевод и завершение периода доступны через закрытые служебные
ручки и Django Backoffice. Оценки и интерфейс периодов в учебном frontend
пока не реализованы. Чтения не обращаются к Gateway и не
доказывают существование или активность его учётной записи.

`study_year=2026` означает учебный год 2026/2027. Пара имени и года уникальна;
пробелы по краям имени удаляются; NUL в имени недопустим.
ID и время создания устанавливает PostgreSQL.

`student_class_periods` хранит `student_id` (UUID Gateway), `class_id` (локальный FK),
`joined_at` и nullable `left_at`. NULL у `left_at` означает открытый период.
Частичный уникальный индекс запрещает два открытых периода одного ученика
независимо от класса; CHECK запрещает выход раньше вступления. Закрытые строки
сохраняют историю: возвращение в прежний класс создаёт новый период.
FK не позволяет удалить класс, на который ссылается история; каскадного удаления
нет. Ссылки на БД Gateway нет: добавление проверяет существование, роль и
активность ученика через API владельца данных до открытия транзакции Journal.

Python-модели: `Class` / `ClassRow` для класса, `StudentClassPeriod` /
`StudentClassPeriodRow` для периода ученика. Файлы класса остаются
`school_class.py`, поскольку `class` — ключевое слово Python.

Ревизия `44fda21bc443` после `f98bb7a9333b` переименовывает таблицу
`class_memberships` в `student_class_periods`, индекс, ограничения и
последовательность ID. Она сохраняет историю и счётчик; downgrade возвращает
прежние имена. ORM и тесты используют новое имя: обнови БД перед чтением
периодов. Применённые ревизии не переписываем и данные не удаляем.

## Перевод и завершение периода

В Backoffice откройте «Пользователи», найдите ученика по ФИО или email и
нажмите «Класс ученика». Страница показывает текущий класс и исходный период.
Перевод требует целевого класса; завершение — отдельного подтверждения.
Имя читается из Gateway только для отображения, локальной копии users нет.

| Команда | Результат |
|---|---|
| POST `/internal/students/{student_id}/current-class-period/transfer`, JSON `target_class_id`, `expected_period_id` | 200 с новым периодом; тот же текущий класс и тот же открытый expected — 200 без изменения |
| DELETE `/internal/students/{student_id}/current-class-period?expected_period_id=...` | Пустой204 после закрытия; отсутствие открытого периода —204 без события |

Обе команды требуют прежние служебный Bearer-токен, право `class-periods:write`
и `X-Actor-ID`. Чужой/устаревший expected при наличии нового текущего периода
не меняет состояние и даёт409. Перевод дополнительно проверяет активного
ученика через Gateway; завершение не зависит от Gateway. Нет текущего периода
для перевода —409; неизвестный целевой класс —404.

Транзакция блокирует исходный период через `SELECT FOR UPDATE`, закрывает его,
создаёт новый с общей датой границы и сохраняет событие outbox. Время закрытия
назначает PostgreSQL через `clock_timestamp()` после ожидания блокировки.
Повтор перевода со старым expected —409, не сохранённый replay-ответ.
При таймауте результат неизвестен: Backoffice предлагает перечитать состояние,
не повторяет команду автоматически и не подменяет expected свежим значением.

События `transferred` содержат previous/current, `removed` — previous/current=null;
формат `added` не изменён. Публикацию outbox в Kafka выполняет воркер
`journal-outbox-relay` (compose), события аудит-журнала потребляет Analytics —
доставка включена в стек, отдельного шага не требует.

## Записи урока (дневник)

Посещаемость и оценки за урок — домен дневника. Таблицы:
`lesson_attendance` (одна строка на урок-ученика) и `lesson_grades`
(одна на урок-ученик-тип). `lesson_id` — ID урока Schedule без внешнего
ключа: класс, предмет и школьная дата (Asia/Yekaterinburg) денормализуются
в строку контекстом команды, статус урока проверяет Gateway до проксирования.
Уникальность `(lesson_id, student_id)` и `(lesson_id, student_id, kind)`;
индексы `(student_id, lesson_date)`, `(class_id, lesson_date)` и
`(student_id, subject_id, lesson_date)` закрывают чтения окна и средних.
Колонка `generator` помечает строки демо-генератора, `author_id` —
учителя-владельца на момент записи; CHECK держит оценку в 2–5.

Запись — пакет-замена одной транзакцией: строки урока, отсутствующие в
пакете, удаляются, оценки учеников с посещаемостью ≠ `present` удаляются,
«не более двух оценок на ученика» — явная проверка обработчика. Обработчик
сверяет учителя контекста с `X-User-ID`, дату урока с текущей четвертью
(не будущее, не закрытая), состав класса на дату по `student_class_periods`
и оценку только присутствовавшему. Чужой автор — 409, неверное
тело/окно/будущее — 422; повтор сети безопасен — замена сходится без
дублей. Записи **не эмитируют outbox-события** — намеренное отступление от
правила сервиса публиковать события (прецедент: назначения `teacher_classes`).

Четверти — версия-копия `QUARTERS`/`VACATIONS`/`CALENDAR_VERSION` из
`school_calendar.py` Schedule (`domain/study_quarters.py`; рантайм-импорт
соседнего сервиса запрещён); синхронность копии с оригиналом проверяет
`tools/test_study_quarters_sync.py`. Окно чтения — не длиннее четверти.
Средние и четвертные нигде не хранятся — считаются при чтении (SQL `AVG`,
округление half-up на слое приложения).

| Ручка | Право | Результат |
|---|---|---|
| POST `/internal/lessons/{lesson_id}/entries` | `lesson-records:write` | пакет-замена записей урока, полное состояние после неё |
| GET `/internal/lessons/{lesson_id}/entries` | `lesson-entries:read` | записи урока для формы правки |
| GET `/internal/students/{student_id}/diary-entries?date_from&date_to` | `diary:read` | посещаемость и оценки ученика окном дат |
| GET `/internal/students/{student_id}/subject-averages?quarter=` | `diary:read` | средние, число оценок и четвертные по предметам |
| GET `/internal/students/{student_id}/last-entry-date` | `diary:read` | якорь дневника: дата последней записи и четверть |

Write-принципал `lesson-records:write` приходит от Gateway отдельной парой
`JOURNAL_WRITE_SERVICE_TOKEN` (в Journal — `GATEWAY_WRITE_SERVICE_TOKEN`),
не равной read- и backoffice-токенам; чтения дневника идут через read-пару
с правом `diary:read`. Демо-историю пишет
`tools/balance_demo_diary_db.py` (шаги runbook публичного стенда).

## Запуск процессов

Все команды — из корня репозитория. Настройки контейнеров находятся в
`services/journal/.env` и `.postgres.env`; секреты не коммитим.
Для нового окружения скопируй соответствующие `.example`-файлы, задай реальные
значения и согласуй пароль PostgreSQL с `DATABASE_URL`.
URL внутри контейнера использует `journal-postgres:5432`.

```bash
docker compose up --build -d journal-api
docker compose ps journal-api journal-postgres
curl -i http://127.0.0.1:8005/health/live
curl -i http://127.0.0.1:8005/health/ready
```

Compose сначала ждёт healthy PostgreSQL, затем успешное применение миграций,
после этого запускает API. `live` проверяет HTTP-процесс; `ready` выполняет
`SELECT 1`, возвращая 503 при недоступности базы или таймауте в три секунды.
При остановке lifespan закрывает созданный HTTP-клиент Gateway, затем пул
соединений через `engine.dispose()`, даже если закрытие клиента завершилось ошибкой.

Для автоматической перезагрузки кода:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build -d journal-api
```

В dev исходники монтируются из репозитория, Uvicorn работает с `--reload`.
В обычном режиме код и готовые миграции включены в образ. Production override
убирает прямые опубликованные порты API и PostgreSQL; это не заменяет TLS,
управление секретами и сетевую изоляцию при реальном deployment.

## Служебный HTTP API

`POST /internal/classes` и `GET /internal/classes` требуют
`Authorization: Bearer <BACKOFFICE_SERVICE_TOKEN>`. Это отдельный секрет
Journal, не JWT пользователя и не служебный секрет Gateway. Backoffice использует
права чтения/записи классов, периодов и назначений. Homework с отдельным
HOMEWORK_SERVICE_TOKEN получает только teacher-classes:read и
student-current-class:read. Последнее разрешает существующий GET
`/internal/students/{student_id}/current-class-period`, но не историю,
составы или запись. Backoffice сохраняет доступ к этой ручке.
История и составы по-прежнему требуют classes:read.
Health-ручки открыты; внутренние ручки скрыты из OpenAPI, но защищены токеном
и проверкой права, а не скрытием из документации.

Пример для fish (не публикуй значение токена):

```fish
set journal_token (poetry -C services/journal run python -c 'from journal_service.config import JournalSettings; print(JournalSettings().backoffice_service_token)')

curl -i -X POST http://127.0.0.1:8005/internal/classes \
    -H "Authorization: Bearer $journal_token" \
    -H 'Content-Type: application/json' \
    -d '{"name":"7А","study_year":2026}'

curl -i 'http://127.0.0.1:8005/internal/classes?study_year=2026&limit=50&offset=0' \
    -H "Authorization: Bearer $journal_token"
set -e journal_token
```

Создание: 201; повтор той же пары: 409; неверные данные: 422;
неверный/отсутствующий токен: 401 с `WWW-Authenticate: Bearer`;
недостаточное право: 403. Список сортируется по ID; без фильтра возвращает все
годы. `limit`: 1–100 (по умолчанию 50), `offset`: 0–9223372036854775807
(диапазон PostgreSQL BIGINT).
Ошибка содержит `error.code`, `error.message`, `error.request_id`;
тот же ID присутствует в `X-Request-ID`. В ответе 500 нет внутренних деталей.

## Чтение периодов

Все три GET-ручки требуют служебный Bearer-токен. Текущий период требует
`student-current-class:read`, история и состав — `classes:read`.
Ручки скрыты из OpenAPI; роль пользователя или JWT Gateway не заменяют
служебную аутентификацию. Поля ответа: `id`, `student_id`, `class_id`,
`joined_at`, `left_at`.

| GET-путь | Результат |
|---|---|
| `/internal/students/{student_id}/current-class-period` | 200 с открытым периодом; 404, если его нет |
| `/internal/students/{student_id}/class-periods` | 200 со страницей истории по `joined_at`, затем `id`; пустой список допустим |
| `/internal/classes/{class_id}/current-periods` | 200 с открытыми периодами по `id`; пустой список для существующего пустого класса, 404 для неизвестного класса |

Списки принимают `limit=50` (1–100) и `offset=0` (0–9223372036854775807).
`student_id` — UUID, `class_id` — 1–2147483647. Неверный параметр даёт 422.
Новые сценарии собраны в `application/class_periods.py` и `api/class_periods.py`;
`ClassRepository` хранит и читает классы через `uow.classes`, а
`StudentClassPeriodRepository` читает периоды через `uow.class_periods`.
Порты находятся в `application/ports/`, SQLAlchemy-реализации — в
`infrastructure/class_repository.py` и `infrastructure/student_class_period_repository.py`.
Оба репозитория получают одну сессию от Unit of Work: commit, rollback и
закрытие сессии общие. Разделение не меняет схему БД и не требует миграции.

После изменений исходников пересобери API, если работаешь без dev mounts:

```bash
docker compose up --build -d journal-api
```

Пример чтения состава из обычного shell; подставь служебный токен Journal:

```bash
curl -i 'http://127.0.0.1:8005/internal/classes/1/current-periods?limit=50&offset=0' \
    -H 'Authorization: Bearer YOUR_JOURNAL_SERVICE_TOKEN'
```

Новые классы имеют пустой состав до добавления ученика через закрытый PUT.
Сквозные тесты чтения и добавления используют отдельную явно выбранную
тестовую БД, а не рабочие данные.

## Миграции

Применить готовые ревизии:

```bash
docker compose run --rm journal-migrations
```

Создать новую ревизию в разработке (файл остаётся в репозитории):

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm journal-migrations \
    /app/.venv/bin/alembic revision --autogenerate -m "describe schema change"
```

Проверяй сгенерированный файл перед применением. Новые миграции создаются в
разработке; при deployment применяются уже проверенные файлы из Git/образа.

## Подготовка чтения пользователей Gateway

Gateway предоставляет закрытый GET `/internal/users/{user_id}`, возвращающий
только ID, роль и активность. Доступ требует отдельного Bearer-секрета:
`JOURNAL_SERVICE_TOKEN` в Gateway соответствует `GATEWAY_SERVICE_TOKEN` в
Journal, но не совпадает с секретами Backoffice или пользовательскими JWT.
`GATEWAY_BASE_URL` внутри Compose — `http://gateway-api:8000`.

В Journal реализованы port `GatewayUserReader`, DTO `GatewayUserInfo`,
Pydantic-контракт и HTTP-клиент `HttpGatewayUserReader`. Добавление ученика
использует этот клиент; существующие чтения не требуют Gateway. Lifespan
создаёт один AsyncClient при непустых `GATEWAY_BASE_URL` и `GATEWAY_SERVICE_TOKEN`.
Исходящий токен должен совпасть с `JOURNAL_SERVICE_TOKEN` в Gateway; это не
входящий секрет `BACKOFFICE_SERVICE_TOKEN` Journal. Без настроенной интеграции
PUT возвращает 503, а чтения и health продолжают работать.
Клиент получает данные, но не решает, можно
ли добавить пользователя в класс. 404 означает отсутствие пользователя;
сеть/ошибочный ответ означают невозможность проверки, а не отсутствие.

## Проверки

### Добавление ученика в класс

Подготовлены запись периода, таблица `journal_event_outbox`, репозиторий outbox
и общая транзакция трёх репозиториев. Новая ревизия
`d79431f0c9b2` создаёт только outbox, не изменяя историю учеников.
Доставку сохранённых событий в Kafka выполняет `journal-outbox-relay`
(compose), потребитель — аудит Analytics.

`PUT /internal/students/{student_id}/current-class-period` принимает только
`{"class_id": 10}`. Обязательны `Authorization: Bearer <BACKOFFICE_SERVICE_TOKEN>`
и `X-Actor-ID: 42`: положительный десятичный ID сотрудника Django без ведущих
нулей, до 9223372036854775807. Проверяются доверенный Backoffice и право
`class-periods:write`. Backoffice должен брать ID из `request.user.pk`, не из формы.
Источник инициатора задаётся сервером; request_id генерирует Journal.

- 201: создан период и одно событие `journal.student_class.changed` в outbox.
- 200: ученик уже в том же классе, возвращён прежний период без новых записей.
- 409: ученик уже в другом классе; автоматического перевода нет.
- 404: Gateway подтвердил отсутствие ученика либо класс отсутствует в Journal.
- 422: неверные данные, отсутствующий/неверный actor, неактивный пользователь
  или роль, отличная от student.
- 503: Gateway не настроен, недоступен или вернул недостоверный ответ.

Успешные ответы содержат ровно `id`, `student_id`, `class_id`, `joined_at`,
`left_at`. Неизвестные поля тела запрещены, `class_id` не преобразуется из
строки или bool. Проверка Gateway выполняется до транзакции: её результат
описывает состояние на момент ответа, а не общую транзакцию двух сервисов.

При гонке проигравшая вставка откатывается, обработчик в новом UoW читает
период победителя: тот же класс даёт 200, другой/исчезнувший период — 409.
Idempotency-Key не нужен для этого no-op; воспроизведение исходного ответа
после будущего перевода этим не гарантируется.

Внедрённый в `create_app(..., gateway_user_reader=...)` reader принадлежит
вызывающему коду и приложением не закрывается. Формы Backoffice включены;
доставка событий в Kafka/Analytics работает через relay-воркер compose.

Для полной PostgreSQL-проверки нужен тот же отдельный
`JOURNAL_TEST_DATABASE_URL`; без него интеграционные тесты пропускаются.
Тесты доказывают общий commit, rollback при нарушении PK outbox, повтор и
конфликт при конкурентных вызовах обработчика, а также HTTP→Gateway reader→БД.

```bash
poetry -C services/journal run pytest -q
poetry -C services/journal run ruff check .
poetry -C services/journal run ruff format --check .
docker compose config --quiet
```

Интеграционные тесты пропускаются без `JOURNAL_TEST_DATABASE_URL`.
Им нужна отдельная существующая БД с именем `journal_test_*`, драйвер
`postgresql+asyncpg` и права применения миграций. Не указывай рабочую БД:
тесты удаляют `teacher_classes`, `journal_event_outbox`, `student_class_periods`, затем `classes`
перед каждой проверкой.
Guard проверяет URL также непосредственно перед очисткой. Не запускай эти
тесты параллельно на одной БД.

```fish
set -lx JOURNAL_TEST_DATABASE_URL 'postgresql+asyncpg://journal:YOUR_PASSWORD@127.0.0.1:5436/journal_test_local'
poetry -C services/journal run pytest tests/integration -q
set -e JOURNAL_TEST_DATABASE_URL
```

Проверяются настоящие миграции, транзакции, фильтрация, пагинация, ограничения
имени/года и конкурентное создание: один успех, один конфликт, одна запись.
Дополнительно проверяются серверные поля членства, текущий состав и история,
конкурентное открытие членства (один победитель), FK, CHECK, запрет удаления
класса с историей и три периода при возврате 7А → 7Б → 7А.

## Преподаватели и классы

Таблица `teacher_classes` хранит текущее закрепление: `teacher_id` UUID из
Gateway и `class_id` из Journal. Составной PK запрещает дубли пары; FK защищает
ссылку на локальный класс. История назначений/новые события аудита не добавлены.

- `PUT /internal/teachers/{teacher_id}/classes/{class_id}`: пустой201 при
  создании, пустой204 при повторе; требует Backoffice, `teacher-classes:write`
  и `X-Actor-ID` с действительным форматом Django ID.
- `DELETE` того же адреса: пустой204 даже при отсутствии связи. Gateway не нужен.
- `GET /internal/teachers/{teacher_id}/classes?limit=50&offset=0`:200 список
  классов по ID; отдельное право `teacher-classes:read`, actor не требуется.

PUT проверяет существование и активную роль teacher в Gateway и класс в Journal.
404 — преподаватель/класс не найден;422 — роль/активность/ввод;503 — проверка
Gateway недоступна. Между сервисами нет общей транзакции. Снятие назначения
доступно и для уже неактивного пользователя. Само чтение назначений не является
проверкой всей авторизации будущего Homework.

Backoffice: `/admin/teacher-classes/` → поиск активного учителя по ФИО/email,
назначение/снятие, список текущих классов. Через общий поиск «Пользователи»
можно открыть назначения неактивного преподавателя для очистки. Все действия
проходят через staff-сессию/CSRF; actor берётся из request.user.pk. Локальный
AdminActionRecord сохраняет ID и подтверждённый либо неизвестный исход, без ФИО.
Ошибка локального аудита не откатывает уже совершённый запрос к Journal.

Новая миграция `a27b35d19e80` создаёт только таблицу назначений, предыдущие
миграции/пользователи/классы не меняются. Для живой среды применять отдельно
после проверки: `docker compose run --rm --build journal-migrations`, затем
пересобрать journal-api/backoffice-api. Не запускать тесты против рабочей БД.

Сквозной `tests/integration/test_teacher_class_http_flow.py` запускает настоящие
Gateway/Journal HTTP-приложения и Django-проверку в окружении Backoffice.
Нужны установленные Poetry dev-окружения всех трёх служб. Journal использует
одноразовую PostgreSQL, Django — SQLite в памяти, Gateway — тестовый порт
хранилища пользователей в памяти (не рабочую БД). Тест не меняет реальные env.
