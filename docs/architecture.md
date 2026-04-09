# Архитектура Lesson Record Bot

## Обзор

Система разделена на четыре логические области:

1. Telegram-бот
2. API для Mini App
3. frontend Mini App
4. слой хранения данных и доменная логика

## Размещение

Текущее production-размещение Mini App подтверждено на сервере `Germany2.play2go.cloud`.

На этом сервере запущены как минимум следующие контейнеры проекта:

- `bot_service_appointment_prod` — основной Telegram-бот
- `bot_service_appointment_miniapi_prod` — backend Mini App
- `bot_service_appointment_miniapp_front_prod` — frontend Mini App

Подтверждение было получено через `docker ps` на `Germany2`.

Production checkout расположен в:

- `/root/bot_service_appointment`
- это git-managed checkout, который должен соответствовать конкретному commit из `origin/dev`

Production stack должен подниматься через:

- `docker-compose.prod.yml`
- production timezone для calendar/schedule/finance flows должна быть зафиксирована как `Europe/Moscow`

Ручной запуск production-контейнеров через отдельные `docker run` больше не является основным способом деплоя.

## Модули

### Telegram-бот

- Точка входа: `main.py`
- Инициализация бота: `loader.py`
- Регистрация handlers: `handlers/routers.py`
- Основная роль: пользовательские и административные взаимодействия внутри Telegram, callbacks, уведомления
- В notification-only режиме бот также держит закрепляемую точку входа в Mini App:
  - один bot entry-message
  - только Telegram `web_app` кнопка
  - без браузерной ссылки

### API Mini App

- Точка входа: `webapi/main.py`
- Основная роль: backend для Telegram Mini App, booking/admin endpoints, операции с расписанием
- В production развёрнут на сервере `Germany2.play2go.cloud`
- Для production time-based flow используется `CALENDAR_TIMEZONE=Europe/Moscow`

### Frontend Mini App

- Расположение: `miniapp/`
- Стек: React + Vite
- Основная роль: пользовательский интерфейс внутри Telegram Mini App
- В production развёрнут на сервере `Germany2.play2go.cloud`
- `miniapp/src/App.jsx` теперь используется как тонкий composition-root:
  - Telegram auth
  - выбор admin/user view
  - верхний error/toast layer
- Основные feature-экраны вынесены в отдельные модули:
  - `miniapp/src/features/user/UserView.jsx`
  - `miniapp/src/features/admin/AdminView.jsx`
- Общие frontend boundaries вынесены в shared-слой:
  - `miniapp/src/shared/ui/`
  - `miniapp/src/shared/hooks/`
  - `miniapp/src/shared/lib/`
- Это не финальная модульность frontend, но уже устраняет главный монолитный anti-pattern “весь Mini App живёт в одном App.jsx”

### Хранение данных и доменная логика

- DB session и engine: `database/connect.py`
- Модели и транзакции: `database/`
- Общая бизнес-логика: `utils/`
- Для long-lived процессов проекта запрещено держать одну shared ORM session на весь runtime.
- Session lifecycle должен быть привязан к короткоживущему unit of work: HTTP request, bot update или отдельная background job iteration.
- Для профилей учеников `student_profiles.first_name` и `student_profiles.last_name` считаются источником истины для имени.
- `student_profiles.full_name` хранится как производное поле в формате `Фамилия Имя`, а не как независимое свободное значение.

Дополнительно для регулярных занятий:

- `regular_lessons` хранит шаблон повторения
- `regular_lesson_exceptions` хранит исключения на конкретные даты
- согласованная regular-заявка из Mini App должна материализоваться в `regular_lessons`, а не оставаться только `record_dates.kind="regular"` на одну дату
- разовая отмена одного регулярного занятия больше не должна моделироваться как основной сценарий через `allow`

Дополнительно для доступности расписания:

- недельный график остаётся базовым источником доступности
- `date_availability_overrides` хранит разовые дополнительные окна доступности на конкретную дату (`extra_open`)
- итоговые свободные слоты считаются как базовый график + `extra_open` окна на дату - занятые и подавленные слоты

## Текущие ограничения

- Проект сейчас использует SQLite, поэтому конкурентные сценарии записи должны оставаться консервативными.
- Правила записи и расписания чувствительны и сейчас частично распределены между API и utility-модулями.
- Legacy admin flows всё ещё существуют в Telegram-боте и могут сосуществовать с Mini App flow на этапе миграции.
- В системе всё ещё может существовать legacy-state на базе `allow`, который поддерживается как переходная совместимость.

## Целевое направление

1. Держать правила расписания и записи централизованными.
2. Снижать скрытую связанность между handlers и слоем хранения.
3. Сделать локальную разработку на NixOS воспроизводимой через отдельный dev shell.
4. Вести изменения через документированные задачи, а не через ad hoc-правки.
