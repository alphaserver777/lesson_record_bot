# Актуальное размещение на 5 сентября 2026 года

Рабочая платформа находится на ВМ `192.168.50.111`, каталог
`/srv/professorit-app`. Контейнеры: `professorit-api`, `professorit-bot`,
`professorit-frontend`, `postgres-postgres-1`. Germany2 ниже — историческая
инструкция, её нельзя применять к рабочей платформе.

Проверка обнаружила, что локальная копия репозитория не содержала Ansible-файлы,
присутствующие в развёрнутом приложении. Шаблон `infra/ansible/templates/compose.yml.j2`
восстановлен из рабочей копии и дополнен привязкой API к `192.168.50.111:18000`:
она нужна для подписанных уведомлений от ВМ LMS `192.168.50.114`.
Привязка к `127.0.0.1:18000` также сохраняется. Приёмник проверяет адрес
источника и подпись HMAC. Остальные файлы развёртывания пока нужно сверять
с `/srv/professorit-app/current/infra/ansible`; локальная старая копия не является
полным описанием текущего выпуска.

Исправление связи с LMS применяется воспроизводимым сценарием
`marketing_professorit/infra/lms/production/deploy-reliability.yml`.
При следующем выпуске основной платформы необходимо использовать обновлённый
шаблон с обеими привязками порта, иначе связь с LMS снова прервётся.

---

# Production Deployment

## Сервер

- production server: `Germany2.play2go.cloud`
- checkout path: `/root/bot_service_appointment`
- checkout mode: git-managed
- tracked branch: `dev`

## Контейнеры

- `bot_service_appointment_prod` — основной Telegram-бот
- `bot_service_appointment_miniapi_prod` — FastAPI backend для Mini App
- `bot_service_appointment_miniapp_front_prod` — React/Vite frontend Mini App

## Источник истины для продового запуска

Production stack должен подниматься через:

- `docker-compose.prod.yml`
- конкретный git commit в `/root/bot_service_appointment`

Ручные `docker run` не должны быть основным способом выката.
Ручная синхронизация отдельных файлов в production checkout не должна быть основным способом выката.

## Подготовка перед выкатом

1. Убедиться, что актуальный код закоммичен.
2. Зафиксировать commit, который выкатывается.
3. Проверить, что локальный commit существует в `origin/dev`.
4. На сервере сохранить backup текущего checkout.
5. Если изменение затрагивает схему или данные БД, сохранить production БД локально в игнорируемую папку:
   `backups/production-db/`
6. На сервере перевести checkout на нужный commit.

Последние локальные backup production БД:

- `backups/production-db/germany2-database_prod-20260308-123933.db`
- `backups/production-db/germany2-database_prod-20260308-130339.db`

## Deploy

На `Germany2`:

```bash
cd /root/bot_service_appointment
git fetch origin
git checkout dev
git reset --hard <target-commit>
docker compose -f docker-compose.prod.yml up -d --build
```

Допустимые server-local файлы вне git:

- `.env.prod.docker`
- `.env.prod.bak.*`
- `database_prod/`
- `logs_prod/`

## Проверка

Проверить git-версию:

```bash
git rev-parse HEAD
git branch --show-current
git status --short
```

Проверить контейнеры:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep bot_service_appointment
```

Проверить Mini App API:

```bash
curl -I http://127.0.0.1:28000/docs
```

Проверить логи:

```bash
docker logs --tail 50 bot_service_appointment_prod
docker logs --tail 50 bot_service_appointment_miniapi_prod
docker logs --tail 50 bot_service_appointment_miniapp_front_prod
```

## Важные детали

- `miniapi` должен стартовать через `main_webapi.py`
- Mini App frontend использует `VITE_API_BASE=https://axtar-b2b.ru/miniapi`
- production calendar timezone для `app` и `miniapi` должна быть явно зафиксирована как `CALENDAR_TIMEZONE=Europe/Moscow`
- bot и miniapi используют production volumes:
  - `./database_prod:/app/data/`
  - `./logs_prod:/app/logs/`

## Rollback

1. Остановить текущие контейнеры.
2. Вернуть production checkout на предыдущий commit или восстановить backup checkout.
3. Если изменение затрагивало БД, восстановить нужный локальный backup production БД.
4. Повторно выполнить:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Data Fix Notes

- Для regular booking из Mini App source of truth серии остаётся `regular_lessons`.
- Если в production обнаружены approved `record_dates.kind="regular"` без шаблона в `regular_lessons`, сначала делается локальный backup БД, затем выполняется точечный backfill шаблонов, и только после этого выкатывается код.
- Если rollout меняет производные поля профилей (`student_profiles.full_name`), сначала делается локальный backup production БД, затем выкатывается commit, который выполняет мягкий backfill при startup.
