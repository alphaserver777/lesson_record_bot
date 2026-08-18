# Архитектура Proffessor IT platform

## Обзор

Платформа состоит из четырёх работающих частей:

1. Telegram-бот — авторизация, уведомления, сводка на день и напоминания.
2. API кабинета — бизнес-логика CRM, расписания, финансов и маркетинга.
3. React/Vite frontend — ученический кабинет и админ-панель.
4. PostgreSQL — единый источник истины для всех рабочих данных.

Маркетинговый лендинг `professorit.ru` является отдельным статическим сервисом
и не хранит клиентские данные. Его CTA направляют в Telegram-бот и кабинет.

## Production-размещение

Рабочая VM: `professorit-web`, VM 201 (`192.168.50.111`) в российском
Proxmox-контуре.

| Компонент | Production container | Роль |
|---|---|---|
| PostgreSQL | `postgres-postgres-1` | canonical data store |
| Telegram bot | `professorit-bot` | один Telegram poller, scheduler уведомлений |
| API | `professorit-api` | web API и доменные операции |
| Frontend | `professorit-frontend` | `/cabinet/` UI |

Публичный TLS и доменные маршруты обслуживает Traefik в CT 202
`edge-proxy` (`192.168.50.112`).
Полная схема и путь запросов описаны в
[`PLAN/14-production-infrastructure.md`](../../Marketing_proffessor_it/PLAN/14-production-infrastructure.md).

Germany2 — выключенный legacy-контур. Его miniapp/API-контейнеры остановлены,
SQLite сохранена только для аудита и не является источником runtime-данных.
Старые ссылки `/miniapp` перенаправляются на канонический кабинет, а legacy API
не принимает записи.

## Модули

### Telegram-бот

- точка входа: `main.py`;
- инициализация: `loader.py`;
- routes: `handlers/routers.py`;
- background scheduler: `utils/restart_services.py`;
- reminders и утренняя сводка: `utils/misc/reminder.py`.

Бот не является самостоятельной базой: он работает с той же PostgreSQL, что API
и админ-панель. В production одновременно разрешён только `cabinet-bot-1`.

### API и frontend

- API entrypoint: `main_webapi.py` / `webapi/`;
- frontend source: `miniapp/`;
- user view: `miniapp/src/features/user/UserView.jsx`;
- admin view: `miniapp/src/features/admin/AdminView.jsx`.

Кабинет на `crm.professorit.ru/cabinet/` — единый web-интерфейс. Telegram
только подтверждает identity и открывает его во встроенном браузере.

### Данные и доменная модель

- DB session и engine: `database/connect.py`;
- модели и транзакции: `database/`;
- rules и integrations: `utils/`.

Каноническая связь данных:

```text
Contact → Opportunity → Student profile → RecordDate ← Payment → LTV
                    ↘ source / campaign / marketing spend
```

Точное размещение маркетинговой ссылки хранится отдельно от кампании:

```text
MarketingSource → MarketingCampaign → MarketingTrackingLink
                                      ↓
                              WebAnalyticsEvent
                                      ↓ visitor_id
                              Contact → Opportunity → Payment
```

`GET /r/{public_token}` фиксирует открытие до загрузки клиентского JavaScript
и делает redirect только на разрешённый внутренний маршрут. `tracking_ref`
передаётся между частями лид-магнита и в форму; backend разрешает токен в
`tracking_link_id` и канонический `campaign_id`. Ссылка обозначает размещение,
а не гарантированную личность посетителя.

`contacts` — один человек; Telegram — опциональная identity; `opportunities` —
коммерческая работа; уроки и платежи связаны с тем же `contact_id`. Имя,
телефон и Telegram ID не должны копироваться в новые сущности.

`record_dates.id` — постоянный идентификатор экземпляра занятия. Текущее
финансовое решение связано с ним через `payments.lesson_id`; дата и время в
`payments` являются только историческим snapshot. Регулярный шаблон
материализуется в `record_dates` до финансового закрытия. Подробности — в
[ADR-003](adr/ADR-003-canonical-lesson-financial-status.md).

## Операционные правила

- production timezone: `Europe/Moscow` для календаря, финансов и scheduler;
- `CALENDAR_TIMEZONE=Europe/Moscow` должен быть задан у API и bot;
- background jobs не используют shared ORM session на весь runtime;
- активный bot — только `professorit-bot`, его health endpoint:
  `http://127.0.0.1:8081/ready` внутри контейнера;
- production разворачивается воспроизводимо через `infra/ansible` в
  `/srv/professorit-app`;
- Twenty CRM архивирован и исключён из рабочего контура.
