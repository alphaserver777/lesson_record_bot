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

## Модули

### Telegram-бот

- Точка входа: `main.py`
- Инициализация бота: `loader.py`
- Регистрация handlers: `handlers/routers.py`
- Основная роль: пользовательские и административные взаимодействия внутри Telegram, callbacks, уведомления

### API Mini App

- Точка входа: `webapi/main.py`
- Основная роль: backend для Telegram Mini App, booking/admin endpoints, операции с расписанием
- В production развёрнут на сервере `Germany2.play2go.cloud`

### Frontend Mini App

- Расположение: `miniapp/`
- Стек: React + Vite
- Основная роль: пользовательский интерфейс внутри Telegram Mini App
- В production развёрнут на сервере `Germany2.play2go.cloud`

### Хранение данных и доменная логика

- DB session и engine: `database/connect.py`
- Модели и транзакции: `database/`
- Общая бизнес-логика: `utils/`

## Текущие ограничения

- Проект сейчас использует SQLite, поэтому конкурентные сценарии записи должны оставаться консервативными.
- Правила записи и расписания чувствительны и сейчас частично распределены между API и utility-модулями.
- Legacy admin flows всё ещё существуют в Telegram-боте и могут сосуществовать с Mini App flow на этапе миграции.

## Целевое направление

1. Держать правила расписания и записи централизованными.
2. Снижать скрытую связанность между handlers и слоем хранения.
3. Сделать локальную разработку на NixOS воспроизводимой через отдельный dev shell.
4. Вести изменения через документированные задачи, а не через ad hoc-правки.
