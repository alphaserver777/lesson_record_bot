# Task: miniapp-frontend-modularization

## Проверка Контекста Перед Работой

Перед написанием этой задачи или началом её реализации нужно освежить в памяти:

- `docs/WORKFLOW.md`
- `docs/constitution.md`
- `docs/architecture.md`
- `docs/devplan.md`
- `docs/revie_architecture.md`
- релевантные ADR
- связанные task specs

Если задача затрагивает только часть системы, нужно перечитать как минимум документы, относящиеся к этой части.

## Status

Done

## Контекст

`miniapp/src/App.jsx` уже превратился в монолитный frontend entrypoint, который одновременно держит:

- layout
- data loading
- retry logic
- polling
- optimistic updates
- admin и user UX
- формы и локальный UI-state

Это уже мешает безопасной разработке:

- каждая новая фича повышает риск побочного эффекта
- локальные изменения труднее ревьюить
- сложно понять границы ответственности
- UI-слой, application-логика и API-работа смешаны

Архитектурная критика из `docs/revie_architecture.md` по frontend в целом справедлива: Mini App уже перерос формат “один большой App.jsx”.

## Цель

Разбить монолитный frontend Mini App на более профессиональную и сопровождаемую структуру feature-модулей, не ломая текущую функциональность.

## Scope

В scope:

- разрезать `App.jsx` на более мелкие компоненты и feature-модули
- отделить layout/navigation от feature-экранов
- отделить API/data-loading слой от крупного UI-компонента
- уменьшить размер и связанность основного entrypoint
- зафиксировать новую frontend-структуру в документации

Вне scope:

- полный редизайн Mini App
- переход на другую frontend-библиотеку или state manager
- массовая переработка backend API
- одновременное переписывание всех feature-flows с нуля

## Ограничения

- Нельзя устраивать “big bang rewrite”.
- Переход должен быть инкрементальным и проверяемым.
- UX не должен деградировать.
- Нельзя смешивать эту задачу с unrelated visual polish-задачами.

## Текущее состояние

- Один `App.jsx` содержит сразу и user view, и admin view, и большой набор side effects.
- Повторно используемые части почти не оформлены как самостоятельные frontend boundaries.

## Предлагаемое изменение

### 1. Целевая структура

Разделить Mini App хотя бы на уровни:

- `layout`
- `features/user`
- `features/admin`
- `shared/ui`
- `shared/api`
- `shared/hooks`

### 2. Первый инкремент

В первую очередь вынести:

- admin records/schedule screen
- user booking screen
- shared notification layer
- API helper logic и повторяющийся data loading

### 3. Entry point

`App.jsx` должен стать тонким composition-root, а не местом, где живёт вся бизнес-логика интерфейса.

## Затронутые области

- `miniapp/src/App.jsx`
- новые frontend-модули/компоненты
- возможно `miniapp/src/api.js`
- `docs/architecture.md`
- возможно ADR по frontend boundaries

## Acceptance Criteria

- Размер и ответственность `App.jsx` заметно уменьшены.
- Основные экраны вынесены в отдельные модули.
- API/data-loading больше не смешаны хаотично с layout-слоем.
- Поведение Mini App сохраняется.
- Новая структура frontend описана в документации.

## Verification

- Собрать Mini App.
- Проверить user flow.
- Проверить admin records/schedule flow.
- Проверить, что polling/retry не сломались после разбиения.

## Результат

- `miniapp/src/App.jsx` сокращён до composition-root с Telegram auth и выбором admin/user view.
- `UserView` вынесен в `miniapp/src/features/user/UserView.jsx`.
- `AdminView` вынесен в `miniapp/src/features/admin/AdminView.jsx`.
- Общие компоненты и утилиты вынесены в:
  - `miniapp/src/shared/ui/`
  - `miniapp/src/shared/hooks/`
  - `miniapp/src/shared/lib/`
- Notification layer из `008` включён в общий shared-слой и больше не живёт внутри монолитного `App.jsx`.

## Rollback / Safety

- Делать инкрементально, с небольшими безопасными коммитами.
- Если конкретный этап даёт регрессию, откатывать именно его, а не весь frontend.

## Заметки

- Это уже архитектурная задача, а не просто косметическое улучшение.
- Её правильно делать после стабилизации слоя уведомлений и текущих feature-flows.
