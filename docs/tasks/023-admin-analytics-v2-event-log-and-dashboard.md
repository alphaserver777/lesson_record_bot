# 023. Admin Analytics v2: event-log и новый dashboard

Статус: Done

## Что сделано

- Добавлена новая таблица `analytics_events` как source of truth для:
  - `booked`
  - `approved`
  - `rejected`
  - `canceled_by_admin`
  - `canceled_by_client`
  - `rescheduled_from`
  - `rescheduled_to`
  - `presence_yes`
  - `presence_no`
  - `lesson_closed_paid`
  - `lesson_closed_unpaid`
  - `lesson_closed_canceled`
- Встроена запись событий в основные flow:
  - user cancel из Mini App
  - admin cancel/delete/reschedule через Mini App
  - legacy admin cancel/reschedule в bot-flow
  - presence reply
  - lesson close / payment status
- Добавлен агрегирующий endpoint `GET /api/admin/analytics/overview-v2`
- Analytics tab в admin Mini App расширен до нового dashboard:
  - revenue drivers
  - LTV leaderboard
  - repeat booking conversion
  - retention 2/4/8 weeks
  - occupancy by weekday
  - occupancy by hour
  - load heatmap
  - cancel / no-show cards
  - regular vs single comparison

## Ограничения первой версии

- Исторический backfill для `analytics_events` не делался.
- Поэтому cancel/no-show/reschedule аналитика считается полноценно только с момента выката этой версии.
- LTV, retention, revenue share и repeat booking считаются по `payments` и доступны для старых данных.
- `regular vs single` определяется по текущему состоянию `record_dates` / `regular_lessons` и payment history, без отдельного snapshot-table.

## Acceptance

- analytics endpoint v2 отвечает без падений на `week|month|quarter`
- вкладка `Аналитика` в admin Mini App загружается без краша
- cancel/no-show секция явно показывает ограничение historical coverage
- новые booking/cancel/reschedule/presence/close actions пишутся в `analytics_events`

## Проверка

- `python -m py_compile` для backend и затронутых handlers
- ручной smoke-test аналитики в admin Mini App
- отдельная проверка на проде после выката:
  - наличие записей в `analytics_events`
  - загрузка `overview-v2`
  - визуальная проверка новых секций dashboard
