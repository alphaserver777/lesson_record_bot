# Production deployment

Актуально на 12 августа 2026 года. Рабочий production-контур находится не на
Germany2, а в VM `vm-robots-dev1` (`192.168.122.10`) на edge-хосте
`robots-dev1`.

## Сервисы и каталоги

| Сервис | Container | VM-каталог |
|---|---|---|
| PostgreSQL | `postgres-postgres-1` | `/srv/proffessor-it/postgres` |
| API кабинета | `cabinet-api-1` | `/srv/proffessor-it/cabinet` |
| Frontend кабинета | `cabinet-frontend-1` | `/srv/proffessor-it/cabinet` |
| Telegram-бот | `cabinet-bot-1` | `/srv/proffessor-it/app` + bot compose overlay |

Код приложения развёрнут в `/srv/proffessor-it/app`. PostgreSQL `proffessor_it`
— единственный operational source of truth. SQLite и Germany2 считаются только
legacy backup-материалами.

## Сеть и домен

`crm.befa-robotics.com` проходит через Traefik на `robots-dev1`, затем TCP
bridge `:8082` и системный Nginx VM. Кабинет доступен по `/cabinet/`.

Полная инфраструктурная карта, включая публичный сайт, находится в
[`PLAN/14-production-infrastructure.md`](../../Marketing_proffessor_it/PLAN/14-production-infrastructure.md)
в соседнем рабочем репозитории.

## Перед deploy

1. Закоммитить изменения атомарными commit'ами в локальном git-репозитории.
2. Отправить commit в origin.
3. На VM обновить `/srv/proffessor-it/app` до того же commit.
4. Если меняются данные или schema — сделать PostgreSQL dump до deploy.
5. Не запускать второго Telegram poller: активный бот только `cabinet-bot-1`.

## Deploy

API и frontend:

```bash
ssh vm-robots-dev1
cd /srv/proffessor-it/cabinet
docker compose -f docker-compose.yml up -d --build
```

Telegram-бот использует compose overlay:

```bash
ssh vm-robots-dev1
cd /srv/proffessor-it/cabinet
docker compose -f docker-compose.yml \
  -f /srv/proffessor-it/app/deploy/cabinet/docker-compose.bot.yml \
  up -d --build --force-recreate bot
```

## Проверка

```bash
ssh vm-robots-dev1 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

ssh vm-robots-dev1 \
  'docker exec cabinet-bot-1 python -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8081/ready\").read())"'

ssh vm-robots-dev1 'docker logs --tail 80 cabinet-bot-1'
ssh vm-robots-dev1 'docker logs --tail 80 cabinet-api-1'
ssh vm-robots-dev1 'docker logs --tail 80 cabinet-frontend-1'
```

Бот считается готовым, если `cabinet-bot-1` имеет `running/healthy`, `/ready`
возвращает `{"status": "ready"}`, а логи содержат `Start polling`.

## Rollback

1. Вернуть `/srv/proffessor-it/app` на предыдущий known-good commit.
2. Пересобрать только изменённые сервисы теми же compose-командами.
3. При schema/data-ошибке восстановить заранее сделанный PostgreSQL dump.
4. Проверить API, bot health и один тестовый сценарий записи.

Не использовать Germany2 как rollback-цель без отдельного решения: это старый
контур с отличающимся состоянием данных.
