# Task: miniapp-regular-booking-materialization

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

В Mini App пользователь может отправить заявку на занятие с `mode="regular"`. Сейчас после согласования такая заявка утверждается как `record_dates.kind="regular"` на конкретную дату, но не материализуется в таблицу `regular_lessons`.

Это создаёт разрыв доменной модели:

- в day view первая дата выглядит как регулярное занятие
- в следующих неделях серия отсутствует
- `regular_lesson_exceptions` не виновата в этом поведении, потому что исключать просто нечего
- пользователь и администратор получают ложное ощущение, что регулярка создана, хотя фактически сохранён только один экземпляр занятия

Проблема подтверждена на production для сценария Mini App booking approval:

- заявка на `2026-03-08 20:00` была согласована и сохранена как `record_dates.kind="regular"`
- соответствующей записи в `regular_lessons` для этого пользователя и времени не появилось
- на `2026-03-15` занятие уже не отображается

## Цель

Сделать так, чтобы согласованная регулярная запись из Mini App всегда создавалась как полноценный шаблон в `regular_lessons`, а уже существующие “сиротские” регулярные записи в production были безопасно доведены до корректного состояния.

## Scope

В scope:

- исправить approve-flow для Mini App regular booking
- при согласовании `record_dates.kind="regular"` создавать или переиспользовать шаблон в `regular_lessons`
- не создавать дубли шаблонов для одного и того же пользователя, weekday, времени и длительности
- выполнить backfill для уже существующих approved regular записей без шаблона
- перед backfill сделать локальный backup production БД и зафиксировать путь
- обновить документацию по доменной модели регулярной записи

Вне scope:

- переработка UI Mini App для regular booking
- изменение механики single booking
- удаление legacy-state из `record_dates`
- полный рефакторинг всей модели согласования

## Ограничения

- Нельзя ломать уже работающие regular lessons, созданные через старые админские сценарии.
- Нельзя создавать дубликаты в `regular_lessons` при повторном согласовании или backfill.
- Нельзя терять production-данные; перед backfill нужен отдельный backup БД в локальную игнорируемую директорию проекта.
- Rollback должен быть реалистичным: возврат к предыдущему commit и восстановление БД из backup.
- Изменение должно быть совместимо с текущей моделью `regular_lesson_exceptions`.

## Текущее состояние

- `POST /api/user/book` сохраняет regular-заявку как pending `RecordDate`.
- `approve_pending_booking(...)` создаёт calendar event и переводит запись в `approved`.
- `approve_pending_booking(...)` не создаёт запись в `regular_lessons`, даже если `rec.kind == "regular"`.
- В результате согласованная “регулярка” существует только на одну дату.

## Предлагаемое изменение

### 1. Исправление approve-flow

При согласовании pending booking с `rec.kind == "regular"`:

- определить weekday по `rec.record_date`
- проверить, есть ли уже шаблон в `regular_lessons` для этого пользователя, weekday, времени и длительности
- если шаблон уже есть, не создавать дубль
- если шаблона нет, создать его в `regular_lessons`
- оставить текущую согласованную дату как фактическое первое занятие серии

### 2. Backfill production-данных

После исправления кода:

- найти approved `record_dates.kind="regular"`, для которых нет соответствующего шаблона в `regular_lessons`
- создать недостающие шаблоны
- не трогать single bookings, blocks, exceptions и legacy allow

### 3. Документация

Нужно явно зафиксировать в документации:

- `regular_lessons` является source of truth для регулярного шаблона
- `record_dates.kind="regular"` может хранить конкретные экземпляры/согласованные вхождения, но не заменяет шаблон
- Mini App regular approval обязан материализовать шаблон

## Затронутые области

- `database/transactions.py`
- `webapi/main.py`
- возможно `database/models.py`
- `docs/architecture.md`
- `docs/DEPLOYMENT.md`
- эта task spec

## Acceptance Criteria

- После согласования новой regular-заявки из Mini App в `regular_lessons` появляется шаблон, если его ещё не было.
- После согласования той же regular-заявки повторно не возникает дубликат шаблона.
- Регулярное занятие появляется на последующих неделях по своему дню недели и времени.
- Уже существующие approved regular-записи без шаблона получают корректный backfill.
- Single bookings, admin blocks и `regular_lesson_exceptions` продолжают работать без регрессии.
- Перед backfill production БД сделан локальный backup, и путь к нему сохранён в task notes или deployment docs.

## Verification

- Создать через Mini App новую regular-заявку, согласовать её и проверить наличие шаблона в `regular_lessons`.
- Проверить в календаре первую дату и следующую неделю для этой регулярки.
- Повторно согласовать аналогичный сценарий и убедиться, что дубль шаблона не создаётся.
- Выполнить backfill на production и проверить конкретный ранее сломанный кейс.
- Выполнить `python -m compileall database webapi utils handlers`.

## Rollback / Safety

- Перед backfill сделать локальный backup production БД в игнорируемую git директорию проекта.
- Если фикc даёт регрессию, откатиться на предыдущий commit и восстановить БД из локального backup.
- После rollout проверить конкретный кейс с регуляркой на первой и следующей неделе.

## Заметки

- Это bugfix доменной модели, а не изменение UX.
- Отдельной follow-up задачей может стать cleanup старых `record_dates.kind="regular"` и уточнение, какие именно экземпляры серии нужно хранить как materialized records.
- Локальный backup production БД перед backfill сохранён в:
  `backups/production-db/germany2-database_prod-20260308-130339.db`
- Backfill на `Germany2` создал `2` недостающих шаблона в `regular_lessons`.
