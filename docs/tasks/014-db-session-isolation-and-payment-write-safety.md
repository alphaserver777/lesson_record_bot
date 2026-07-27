# Task: db-session-isolation-and-payment-write-safety

## Проверка Контекста Перед Работой

Перед написанием этой задачи или началом её реализации нужно освежить в памяти:

- `docs/WORKFLOW.md`
- `docs/constitution.md`
- `docs/architecture.md`
- `docs/devplan.md`
- `docs/DEPLOYMENT.md`
- релевантные ADR
- связанные task specs

Если задача затрагивает только часть системы, нужно перечитать как минимум документы, относящиеся к этой части.

## Status

Done

## Контекст

30 марта 2026 года production Mini App на `Germany2.play2go.cloud` перестал открываться, хотя frontend и `miniapi` оставались доступными по сети.

Фактическая цепочка сбоя была такой:

- в `miniapi` упал admin flow закрытия урока через `POST /api/admin/lessons/close`
- в логах зафиксирован `sqlite3.IntegrityError: UNIQUE constraint failed: payments.id`
- после этого общая SQLAlchemy session процесса перешла в состояние `PendingRollbackError`
- все последующие запросы в том же процессе, включая `POST /api/webapp/auth/telegram`, начали отвечать `500`
- пользователь видел это как “Mini App перестал открываться”

Проблема была усугублена архитектурным решением:

- в `database/connect.py` использовалась одна долгоживущая shared session на весь процесс
- функции в `database/transactions.py` и части `webapi/main.py` опирались на неё как на глобальное состояние
- сбой одной транзакции отравлял весь backend-процесс до ручного рестарта контейнера

## Цель

Гарантировать, что ошибка одной DB-операции не ломает весь process-level runtime Mini App API или бота, а запись оплат остаётся устойчивой к локальным коллизиям и rollback-сценариям.

## Scope

В scope:

- изоляция DB session по request/task вместо одной общей process-wide session
- явный rollback/cleanup сессии после ошибок
- защита payment write flow от локальных `payments.id` конфликтов
- фиксация архитектурного правила для long-lived Python процессов проекта
- проверка production rollout на `Germany2`

Вне scope:

- полный рефакторинг всех transaction helpers в repository/service слои
- миграция с SQLite на PostgreSQL
- полный redesign payment domain model

## Ограничения

- Проект продолжает работать на SQLite, поэтому решение должно быть консервативным по конкурентной записи.
- Нельзя допускать, чтобы failure в admin flow снова ломал auth flow Mini App.
- Изменение должно быть совместимо и с `bot_service_appointment_prod`, и с `bot_service_appointment_miniapi_prod`.

## Текущее состояние

До исправления проект использовал shared async session, импортируемую из `database/connect.py`.

Это означало:

- один rollback-sensitive session object жил дольше отдельного запроса или update handling
- после `IntegrityError` или другой ошибки записи сессия оставалась в невалидном состоянии
- последующие чтения и записи в том же процессе могли падать с `PendingRollbackError`
- Mini App runtime становился хрупким по отношению к сбою в совершенно другом flow

## Предлагаемое изменение

1. Изолировать SQLAlchemy session по request/task.

- shared process-wide session не должна использоваться как source of truth для runtime state
- backend и bot должны работать с task-local/per-request session lifecycle

2. Добавить обязательный rollback и cleanup.

- если request или handler падает на DB-ошибке, его session должна быть откатана и удалена
- следующий запрос не должен наследовать повреждённую транзакцию

3. Укрепить payment insert flow.

- локальные конфликты по `payments.id` не должны приводить к отравлению процесса
- запись оплаты должна либо успешно завершаться, либо чисто откатываться без side effect на другие flows

4. Зафиксировать архитектурное правило.

- long-lived процессы проекта не должны держать одну shared ORM session на весь runtime
- session lifecycle должен быть привязан к единице работы: HTTP request, bot update, background job iteration или другой короткоживущий unit of work

## Затронутые области

- `database/connect.py`
- `database/transactions.py`
- `webapi/main.py`
- runtime lifecycle `miniapi`
- runtime lifecycle основного Telegram-бота
- `docs/architecture.md`
- production deploy на `Germany2.play2go.cloud`

## Acceptance Criteria

- Ошибка в `POST /api/admin/lessons/close` не переводит весь `miniapi` в состояние, при котором `POST /api/webapp/auth/telegram` начинает отвечать `500`.
- После локальной DB-ошибки следующий независимый запрос продолжает обслуживаться нормально без рестарта контейнера.
- В коде отсутствует зависимость от одной process-wide shared ORM session как долгоживущего runtime state.
- В архитектурной документации явно зафиксировано правило per-request/per-task session lifecycle.
- После production rollout `miniapi` снова отвечает корректно и Mini App открывается без массовых `500` на auth.

## Verification

- На production проверить:
  - `docker logs --tail 100 bot_service_appointment_miniapi_prod`
  - `curl -i https://axtar-b2b.ru/miniapi/health`
- Выполнить контролируемый запрос auth без валидного `initData` и убедиться, что backend отвечает штатным `401`, а не `500`.
- Открыть Mini App в Telegram и подтвердить успешный auth flow.
- Проверить, что после rollout контейнеры `bot_service_appointment_prod` и `bot_service_appointment_miniapi_prod` находятся в `Up`.

## Rollback / Safety

- Backup изменённых production-файлов должен сохраняться перед hotfix rollout.
- Если исправление ведёт к regressions, можно вернуть backup-файлы и пересобрать `app` и `miniapp-api`.
- После rollout нужно мониторить логи на предмет новых `IntegrityError`, `PendingRollbackError` и повторных `500` на `/api/webapp/auth/telegram`.

## Результат

- DB session lifecycle изолирован по task/request, а не разделяется на весь runtime процесса.
- `miniapi` больше не отравляется глобально после единичной ошибки записи.
- Вставка `payments` не оставляет сервис в сломанном состоянии даже при локальном конфликте.
- Инцидент 30 марта 2026 года оформлен как задокументированная задача, а не как неявный operational fix.

## Заметки

- Это закрывает production incident и вводит минимально безопасное правило session isolation.
- Более глубокий follow-up всё ещё возможен: вынести transaction boundaries и unit-of-work pattern в отдельный application/persistence слой.
