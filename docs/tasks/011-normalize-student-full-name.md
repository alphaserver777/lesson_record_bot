# Task: normalize-student-full-name

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

В production обнаружен клиент, у которого:

- `first_name` и `last_name` заполнены корректно
- `student_profiles.full_name` содержит legacy-значение `vv`

Из-за этого в части admin flow отображается мусорное имя:

- карточка клиента показывает нормальное имя, потому что использует display-name из `last_name + first_name`
- список `Записи на день` показывает `vv`, потому что опирается на `student_profiles.full_name`

Проблема доменная:

- `full_name` сейчас иногда ведёт себя как произвольное поле
- хотя фактически оно должно быть производным от `first_name` и `last_name`

## Цель

Сделать `student_profiles.full_name` нормализованным производным полем и убрать legacy-рассинхрон имени в отображении записей, финансов и других admin flow.

## Scope

В scope:

- зафиксировать правило: `full_name = last_name + " " + first_name`
- выполнить мягкий backfill профилей, где `first_name/last_name` уже есть, а `full_name` устаревший или мусорный
- обновить инициализацию БД так, чтобы нормализация выполнялась автоматически
- задокументировать правило в архитектуре
- сделать production backup БД перед rollout

Вне scope:

- полная переработка схемы профилей
- отдельная миграционная система
- изменение формата имени на `first_name + last_name`
- массовая чистка неразобранных имён без `first_name/last_name`

## Ограничения

- Нельзя затирать профиль, если `first_name` и `last_name` оба пусты.
- Нельзя ломать поиск, reminders, финансы и schedule display.
- Изменение должно быть совместимым с текущей SQLite-схемой без отдельной ручной миграции.

## Текущее состояние

- `upsert_student_profile(...)` уже умеет пересобирать `full_name`, если обновляются `first_name` или `last_name`
- но legacy-профили со старым `full_name` продолжают жить в БД
- часть backend flow читает `StudentProfile.full_name` напрямую

## Предлагаемое изменение

### 1. Нормализация профилей

Добавить мягкий backfill:

- если у профиля есть `first_name` или `last_name`
- вычислить каноническое `full_name`
- если оно отличается от stored `full_name`, обновить `full_name`

### 2. Источник истины

Считать источником истины:

- `first_name`
- `last_name`

А `full_name` хранить как производное, а не как независимое поле.

### 3. Production rollout

Перед rollout:

- сохранить локальный backup production БД

После rollout:

- проверить конкретный кейс клиента, который раньше отображался как `vv`

## Затронутые области

- `database/transactions.py`
- `docs/architecture.md`
- `docs/DEPLOYMENT.md`

## Acceptance Criteria

- Для профилей с заполненными `first_name/last_name` поле `full_name` нормализуется в формат `Фамилия Имя`.
- Клиент, который раньше отображался как `vv`, начинает отображаться нормальным именем в `Записях`.
- Production rollout сопровождается backup БД.
- Поведение карточки клиента и schedule display становится консистентным.

## Verification

- Выполнить `python -m compileall webapi database utils handlers`.
- Проверить в БД до/после нормализацию `student_profiles.full_name`.
- Проверить отображение конкретного клиента в `Управление -> Клиенты` и `Записи`.
- Проверить production deploy на `Germany2`.

## Rollback / Safety

- Хранить локальный backup production БД до rollout.
- Если нормализация заденет нежелательные профили, откатить commit и восстановить backup БД.

## Результат

- `student_profiles.full_name` нормализуется автоматически из `first_name/last_name` при инициализации БД.
- Legacy-профили с мусорным `full_name` больше не должны всплывать в расписании и admin flow после rollout.
