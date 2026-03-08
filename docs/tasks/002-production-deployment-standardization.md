# Task: production-deployment-standardization

## Проверка Контекста Перед Работой

Перед написанием этой задачи или началом её реализации нужно освежить в памяти:

- `docs/WORKFLOW.md`
- `docs/constitution.md`
- `docs/architecture.md`
- `docs/devplan.md`
- релевантные ADR
- связанные task specs

Если задача затрагивает только часть системы, нужно перечитать как минимум документы, относящиеся к этой части.

## Status

Done

## Контекст

Production-размещение на `Germany2.play2go.cloud` работает, но сейчас оно не полностью воспроизводимо из репозитория.

Наблюдаемое состояние:

- основной бот поднимается через `docker-compose.prod.yml`
- `miniapi` и `miniapp_front` фактически запускались отдельно от compose
- имена live-контейнеров и их реальные параметры нужно было восстанавливать через `docker inspect`
- недавний деплой потребовал ручного исправления entrypoint для `miniapi`

Это повышает риск регрессий при следующих выкатах.

## Цель

Сделать production deployment на `Germany2` воспроизводимым из репозитория и явно задокументированным.

## Scope

В scope:

- привести `docker-compose.prod.yml` к фактическому production-стеку
- включить туда bot, Mini App API и Mini App frontend
- зафиксировать корректные container names, volumes, ports и entrypoint
- описать пошаговый deploy/verify/rollback для `Germany2`
- задокументировать актуальную схему production-размещения

Вне scope:

- миграция с Docker на NixOS services
- автоматический CI/CD pipeline
- замена SQLite
- вынос secrets в новый секрет-менеджер

## Ограничения

- Нельзя ломать текущие production container names, если на них завязана внешняя маршрутизация.
- Нельзя полагаться на незафиксированные ручные знания о сервере.
- Новый способ выката должен работать с текущей структурой проекта на `Germany2`.

## Текущее состояние

- production checkout находится в `/root/bot_service_appointment`
- production server: `Germany2.play2go.cloud`
- bot container: `bot_service_appointment_prod`
- miniapi container: `bot_service_appointment_miniapi_prod`
- miniapp frontend container: `bot_service_appointment_miniapp_front_prod`

## Предлагаемое изменение

- Обновить `docker-compose.prod.yml`, чтобы он описывал весь production-стек.
- Добавить отдельный deployment document с командами deploy, verify и rollback.
- Обновить общие архитектурные документы, чтобы production map был явно зафиксирован.

## Затронутые области

- `docker-compose.prod.yml`
- `docs/architecture.md`
- `docs/WORKFLOW.md`
- новый deployment document

## Acceptance Criteria

- Весь production-стек описан в одном compose-файле.
- Повторный deploy на `Germany2` не требует ручного восстановления параметров контейнеров.
- В docs есть явное описание production deployment path.
- После выката контейнеры bot, miniapi и miniapp_front находятся в рабочем состоянии.

## Verification

- Проверить `docker compose -f docker-compose.prod.yml config`
- Выполнить deploy на `Germany2`
- Проверить `docker ps`
- Проверить HTTP-ответ Mini App API
- Проверить, что frontend Mini App поднят

## Rollback / Safety

- Перед выкатом сохранить backup checkout на сервере.
- В случае проблем откатиться к backup-копии и пересобрать контейнеры из прежнего состояния.

## Заметки

- Нужно явно указать, что `miniapi` должен стартовать через `main_webapi.py`, а не через default entrypoint образа.
