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

Рабочая VM: `vm-robots-dev1` (`192.168.122.10`).

| Компонент | Production container | Роль |
|---|---|---|
| PostgreSQL | `postgres-postgres-1` | canonical data store |
| Telegram bot | `cabinet-bot-1` | один Telegram poller, scheduler уведомлений |
| API | `cabinet-api-1` | web API и доменные операции |
| Frontend | `cabinet-frontend-1` | `/cabinet/` UI |

Публичный TLS и доменные маршруты обслуживает Traefik на хосте `robots-dev1`.
Полная схема и путь запросов описаны в
[`PLAN/14-production-infrastructure.md`](../../Marketing_proffessor_it/PLAN/14-production-infrastructure.md).

Germany2 — legacy-контур. Его контейнеры и SQLite не используются как рабочие
сервисы и не являются источником runtime-настроек.

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

Кабинет на `crm.befa-robotics.com/cabinet/` — единый web-интерфейс. Telegram
только подтверждает identity и открывает его во встроенном браузере.

### Данные и доменная модель

- DB session и engine: `database/connect.py`;
- модели и транзакции: `database/`;
- rules и integrations: `utils/`.

Каноническая связь данных:

```text
Contact → Opportunity → Student profile → Lessons → Payments → LTV
                    ↘ source / campaign / marketing spend
```

`contacts` — один человек; Telegram — опциональная identity; `opportunities` —
коммерческая работа; уроки и платежи связаны с тем же `contact_id`. Имя,
телефон и Telegram ID не должны копироваться в новые сущности.

## Операционные правила

- production timezone: `Europe/Moscow` для календаря, финансов и scheduler;
- `CALENDAR_TIMEZONE=Europe/Moscow` должен быть задан у API и bot;
- background jobs не используют shared ORM session на весь runtime;
- активный bot health endpoint: `http://127.0.0.1:8081/ready` внутри контейнера;
- Twenty CRM архивирован и исключён из рабочего контура.
