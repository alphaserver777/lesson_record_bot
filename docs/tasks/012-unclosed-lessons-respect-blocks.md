# Task: unclosed-lessons-respect-blocks

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

На production выявлено расхождение между:

- `Записи на день`
- `Управление -> Финансы -> Незакрытые занятия`

На дату `2026-03-08` стоял admin block `14:00-18:50`, и в `Записях на день` корректно отображалось только:

- admin block
- занятие с Полиной в `19:00`

Но в `Незакрытых занятиях` ошибочно появились регулярные занятия на `14:00`, `15:00`, `16:00`.

Причина:

- `viewing_recordings_day_db()` уважает `block`
- `lessons_for_date()` для regular lessons учитывает `skip` и legacy `allow`, но не учитывает `block`

Из-за этого finance flow живёт по другой read-model, чем admin calendar.

## Цель

Сделать так, чтобы `Незакрытые занятия` не показывали занятия, которые доменно подавлены admin block'ом на эту дату.

## Scope

В scope:

- исправить `lessons_for_date()` для regular lessons
- привести unclosed finance flow к той же логике подавления, что и `Записи на день`
- проверить production на кейсе `2026-03-08`
- обновить task spec

Вне scope:

- переработка всей financial read model
- изменение payment model
- новые статусы решения по занятию

## Ограничения

- Нельзя скрыть реально проведённые одиночные занятия.
- Нельзя сломать already fixed timezone behavior.
- Нельзя сломать `skip` и legacy `allow`.

## Текущее состояние

- `viewing_recordings_day_db()` исключает регулярки в слотах, перекрытых `block`
- `lessons_for_date()` этого не делает
- `GET /api/admin/lessons/unclosed` строится именно от `lessons_for_date()`

## Предлагаемое изменение

### 1. Единая логика подавления

В `lessons_for_date()` для regular lessons учитывать:

- `skip`
- legacy `allow`
- `block`

### 2. Консистентность read-model

`Незакрытые занятия` не должны возвращать урок, если в day view этот слот подавлен блоком и не существует как реальная одиночная approved запись.

## Затронутые области

- `database/transactions.py`
- возможно `webapi/main.py`

## Acceptance Criteria

- Регулярки, перекрытые admin block, не попадают в `Незакрытые занятия`.
- Кейс `2026-03-08` в production больше не показывает `14:00`, `15:00`, `16:00` в finance unclosed list.
- Single lessons и реальные approved записи продолжают попадать в unclosed flow корректно.

## Verification

- Выполнить `python -m compileall webapi database utils handlers`.
- Проверить production-кейс `2026-03-08`.
- Проверить, что `19:00` с Полиной остаётся в unclosed flow при отсутствии решения по занятию.

## Rollback / Safety

- Изменение изолированное и не требует schema change.
- Если unclosed flow начнёт скрывать реальные занятия, откатить commit.

## Результат

- `lessons_for_date()` теперь уважает `block` для regular lessons.
- Finance `unclosed` flow синхронизирован с доменной логикой admin day schedule.
