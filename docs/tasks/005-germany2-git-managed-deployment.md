# Task: germany2-git-managed-deployment

## Проверка Контекста Перед Работой

Перед написанием этой задачи или началом её реализации нужно освежить в памяти:

- `docs/WORKFLOW.md`
- `docs/constitution.md`
- `docs/architecture.md`
- `docs/devplan.md`
- `docs/DEPLOYMENT.md`
- релевантные ADR
- связанные task specs

Если задача затрагивает только часть системы, нужно перечитать как минимум документы, относящиеся к этой части.

## Status

Proposed

## Контекст

Сейчас production checkout на `Germany2.play2go.cloud` в `/root/bot_service_appointment` используется как deploy-папка для `docker compose`, но не как строго управляемый git checkout.

Из-за этого возникают риски:

- невозможно надёжно определить, какой commit сейчас в production
- ручная синхронизация файлов может привести к drift между локальным репозиторием и сервером
- rollback опирается на backup директории, а не на точный commit/tag
- нельзя формально зафиксировать version discipline для production

Для проекта это уже становится критичным: доменная логика записи и расписания меняется часто, и production должен быть жёстко привязан к конкретной версии репозитория.

## Цель

Сделать `Germany2` git-managed production checkout, чтобы production всегда соответствовал конкретному commit, а deploy выполнялся от зафиксированной версии без ручного расхождения файлов.

## Scope

В scope:

- определить безопасную миграцию `/root/bot_service_appointment` к git-managed checkout
- привязать production checkout к origin-репозиторию
- обеспечить deploy от конкретного commit или branch-head с явной фиксацией версии
- добавить проверку текущего commit перед и после выката
- обновить deployment docs под git-managed flow
- зафиксировать rollback через checkout предыдущего commit и rebuild containers

Вне scope:

- полный CI/CD pipeline
- registry-based image deploy
- переход на Kubernetes или другой orchestrator
- автоматический GitHub Actions deploy

## Ограничения

- Нельзя ломать текущий production stack на `Germany2`.
- Нельзя потерять `database_prod` и `logs_prod`.
- Нельзя допустить неявный overwrite локальных server-only файлов без их явной инвентаризации.
- Переход должен быть обратимым: до миграции нужен backup текущего server checkout.
- Нужно явно определить, какие файлы на сервере допустимо хранить вне git и как они переживают `git pull`/`checkout`.

## Текущее состояние

- `Germany2` запускает production stack из `/root/bot_service_appointment`.
- Код на сервер часто попадает через ручную синхронизацию файлов.
- Документация уже фиксирует сервер, контейнеры и compose-файл, но ещё не фиксирует git как source of truth для версии production.

## Предлагаемое изменение

### 1. Сделать production checkout git-managed

Нужно перевести `/root/bot_service_appointment` в состояние, где:

- есть `.git`
- настроен `origin`
- можно выполнить `git rev-parse HEAD`
- production deploy опирается на commit, а не на набор вручную скопированных файлов

### 2. Явная дисциплина версии

Перед deploy:

- локально должен быть commit с нужными изменениями
- на сервере должен быть виден текущий deployed commit
- в процессе deploy должен фиксироваться target commit

После deploy:

- нужно проверить, что server checkout находится на ожидаемом commit
- затем уже выполнять `docker compose -f docker-compose.prod.yml up -d --build`

### 3. Rollback

Rollback должен делаться через:

- checkout предыдущего commit
- при необходимости восстановление backup checkout
- rebuild/restart контейнеров

## Затронутые области

- production checkout на `Germany2`
- `docs/DEPLOYMENT.md`
- `docs/architecture.md`
- возможно `docs/WORKFLOW.md`
- возможно отдельный deploy script

## Acceptance Criteria

- Production checkout на `Germany2` имеет git history и связан с origin.
- Перед deploy можно однозначно определить текущий deployed commit.
- Deploy выполняется от конкретного commit, а не через ручное копирование отдельных файлов.
- После deploy можно проверить, что production соответствует ожидаемому commit.
- Rollback на предыдущий commit документирован и реалистичен.
- `database_prod` и `logs_prod` не повреждаются при миграции.

## Verification

- На `Germany2` выполняется `git rev-parse HEAD` в `/root/bot_service_appointment`.
- На `Germany2` выполняется `git remote -v` и показывает ожидаемый origin.
- Выполняется тестовый deploy от конкретного commit с последующей проверкой контейнеров.
- После deploy проверяется `docker ps` и `curl -I http://127.0.0.1:28000/docs`.

## Rollback / Safety

- До миграции сохранить backup текущего `/root/bot_service_appointment`.
- Не удалять текущий checkout до подтверждения работоспособности git-managed варианта.
- Если миграция даёт сбой, вернуть backup checkout и поднять контейнеры по старой схеме.

## Заметки

- Это переход к version discipline в production, но ещё не полноценный CI/CD.
- Следующим шагом после этой задачи может стать deploy script или GitHub Actions pipeline.
