# Production deployment

Актуально на 3 сентября 2026 года. Рабочий production-контур находится в
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
[`PLAN/14-production-infrastructure.md`](../../marketing_professorit/PLAN/14-production-infrastructure.md)
в соседнем рабочем репозитории.

## Перед deploy

1. Закоммитить изменения атомарными commit'ами в локальном git-репозитории.
2. Отправить commit в origin.
3. Выполнить `./scripts/test_critical_flows.sh`; выпуск останавливается при
   падении проверки записи или оплаты.
4. Создать аннотированную метку только из текущей `main`.
5. Развернуть именно эту метку. Ansible перед переключением всегда создаёт и
   проверяет резервную копию PostgreSQL.
6. Не запускать второго Telegram poller: активный бот только `professorit-bot`.

## Конвейер проверок и выпуска

GitHub Actions запускает пять обязательных проверок для `develop`, `main` и
запросов на слияние: исходники и Ansible, критические потоки записи и оплаты,
сборку кабинета, известные уязвимости зависимостей и поиск секретов.

Выпуск не создаётся при обычном отправлении фиксации. Владелец запускает
`Создать выпуск` только из `main`, указывает новую метку
`professorit-vX.Y.Z` и подтверждает окружение `release`. Сценарий повторяет все
проверки, удостоверяется, что `main` не изменялась, и создаёт аннотированную
метку.

Рабочее развёртывание запускается отдельным действием `Развернуть рабочий
выпуск`. Оно принимает только аннотированную метку, которая указывает на
текущую или прошлую фиксацию `main`; подтверждение окружения `production`
обязательно. Сценарий не получает данные PostgreSQL и не восстанавливает их.
При неуспешном запуске контейнеров или проверок Ansible возвращает ссылку
`current` на предыдущий каталог кода и повторно запускает его.

### Настройка GitHub владельцем

До первого удалённого развёртывания в GitHub нужно сделать следующее:

1. В разделе защиты веток запретить прямую отправку в `main` и `develop`,
   потребовать запрос на слияние и все пять проверок `Качество и безопасность`.
   Запрет обхода правил распространяется и на владельцев.
2. Создать окружение `release` с обязательным подтверждением владельцем.
3. Создать окружение `production` с обязательным подтверждением владельцем и
   добавить в него только `PRODUCTION_SSH_PRIVATE_KEY` и
   `PRODUCTION_SSH_KNOWN_HOSTS`. Второй секрет содержит заранее проверенную
   запись `known_hosts` VM 201, а не получается во время развёртывания.

Значения этих секретов нельзя добавлять в документы, сообщения, журналы или
Git. После смены ключа или сервера нужно одновременно обновить оба секрета.

## Deploy

```bash
git fetch origin main --tags
git switch --detach professorit-vX.Y.Z
cd infra/ansible
ansible-playbook deploy.yml \
  -e release_id=professorit-vX.Y.Z \
  -e release_commit=$(git -C ../.. rev-parse HEAD)
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

## Оплата тест-драйва

Prodamus вызывает `https://professorit.ru/api/public/payments/prodamus/webhook`.
CRM сохраняет оплату и задачу выдачи в PostgreSQL, затем сразу пытается создать
доступ. При недоступности LMS или Telegram задача автоматически повторяется ботом:
сначала через 2 минуты, затем с увеличением паузы до часа. Повторное уведомление
Prodamus для этого не нужно и не создаёт вторую выдачу.

Очередь находится в таблице `test_drive_lms_deliveries`. Статусы: `pending` —
ожидает первого запуска, `retrying` — ожидает повтора, `processing` — выполняется,
`delivered` — доступ отправлен. Временный пароль не хранится в таблице: он
повторяемо вычисляется из закрытого ключа интеграции и идентификатора задачи.
При длительной ошибке проверить `professorit-api`, работающий Telegram-бот
и наличие `LMS_INTERNAL_SECRET` в контейнере `lms-backend-1`; затем смотреть
`last_error` и `next_retry_at` только через защищённый доступ к PostgreSQL.

## Rollback

1. При ошибке в ходе deploy Ansible автоматически возвращает предыдущий каталог
   кода; проверить API, bot health и маршруты CRM.
2. Для отдельного ручного отката выбрать предыдущую аннотированную метку и
   повторить выпускной сценарий. Нельзя переключать произвольную папку.
3. При schema/data-ошибке восстановление PostgreSQL требует отдельного решения:
   код и данные не откатываются одним действием.

Не использовать Germany2 как rollback-цель без отдельного решения: это старый
контур с отличающимся состоянием данных.

## Очистка ошибочных прошлых занятий

После создания backup сначала выполнить отчёт:

```bash
docker exec professorit-api sh -lc 'cd /app && PYTHONPATH=/app python scripts/repair_erroneous_historical_lessons.py'
```

Проверить список, затем удалить только подтверждённые строки:

```bash
docker exec professorit-api sh -lc 'cd /app && PYTHONPATH=/app python scripts/repair_erroneous_historical_lessons.py --apply'
```

Скрипт затрагивает только прошлые `record_dates` с точной служебной пометкой
`Восстановлено из истории оплат`; оплаты сохраняются.

## Поля лида

Цена занятия и имя пользователя Telegram являются полями контакта и доступны
до появления профиля ученика. При создании лида они сохраняются в `contacts`;
при наличии связанного Telegram ID имя пользователя синхронизируется с
`telegram_identities.username`. После изменений схемы проверить наличие
`contacts.price` и `contacts.telegram_username` в PostgreSQL.
