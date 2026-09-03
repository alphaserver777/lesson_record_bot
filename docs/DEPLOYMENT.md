# Production deployment

Актуально на 16 августа 2026 года. Рабочий production-контур находится в
Ubuntu VM `professorit-web`, VM 201 (`192.168.50.111`) российского
Proxmox-кластера.

## Сервисы и каталоги

| Сервис | Container | VM-каталог |
|---|---|---|
| PostgreSQL | `postgres-postgres-1` | `/srv/professorit-app` |
| API кабинета | `professorit-api` | `/srv/professorit-app` |
| Frontend кабинета | `professorit-frontend` | `/srv/professorit-app` |
| Telegram-бот | `professorit-bot` | `/srv/professorit-app` |

Код приложения развёрнут релизами в `/srv/professorit-app`. PostgreSQL `proffessor_it`
— единственный operational source of truth. SQLite и Germany2 считаются только
legacy backup-материалами. С 17 августа 2026 года старые контейнеры
`bot_service_appointment_miniapi_prod` и
`bot_service_appointment_miniapp_front_prod` на Germany2 остановлены и имеют
`restart=no`; `https://axtar-b2b.ru/miniapp` перенаправляет в канонический
кабинет, а старый `/miniapi/*` возвращает `410 Gone`.

## Сеть и домен

`crm.professorit.ru` проходит через Traefik в CT 202 `edge-proxy`, затем через
Nginx VM в контейнеры frontend/API. Кабинет доступен по `/cabinet/`.

Полная инфраструктурная карта, включая публичный сайт, находится в
[`PLAN/14-production-infrastructure.md`](../../Marketing_proffessor_it/PLAN/14-production-infrastructure.md)
в соседнем рабочем репозитории.

## Перед deploy

1. Закоммитить изменения атомарными commit'ами в локальном git-репозитории.
2. Отправить commit в origin.
3. Если меняются данные или schema — запустить проверенный PostgreSQL backup.
4. Выполнить Ansible deploy с ID этого commit.
5. Не запускать второго Telegram poller: активный бот только `professorit-bot`.

## Deploy

```bash
cd infra/ansible
ansible-playbook provision.yml
ansible-playbook deploy.yml -e release_id=$(git -C ../.. rev-parse --short HEAD)
```

## Проверка

```bash
ssh deploy@192.168.50.111 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

ssh deploy@192.168.50.111 \
  'docker exec professorit-bot python -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8081/ready\").read())"'

ssh deploy@192.168.50.111 'docker logs --tail 80 professorit-bot'
ssh deploy@192.168.50.111 'docker logs --tail 80 professorit-api'
ssh deploy@192.168.50.111 'docker logs --tail 80 professorit-frontend'
```

Бот считается готовым, если `professorit-bot` имеет `running/healthy`, `/ready`
возвращает `{"status": "ready"}`, а логи содержат `Start polling`.

## Rollback

1. Переключить `/srv/professorit-app/current` на предыдущий immutable release.
2. Повторить Ansible/Compose deploy этого release.
3. При schema/data-ошибке восстановить заранее сделанный PostgreSQL dump.
4. Проверить API, bot health и один тестовый сценарий записи.

Не использовать Germany2 как rollback-цель без отдельного решения: это старый
контур с отличающимся состоянием данных.

## Очистка ошибочных прошлых занятий

После создания backup сначала выполнить отчёт:

```bash
docker exec professorit-api python scripts/repair_erroneous_historical_lessons.py
```

Проверить список, затем удалить только подтверждённые строки:

```bash
docker exec professorit-api python scripts/repair_erroneous_historical_lessons.py --apply
```

Скрипт затрагивает только прошлые `record_dates` с точной служебной пометкой
`Восстановлено из истории оплат`; оплаты сохраняются.
