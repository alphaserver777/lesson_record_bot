# Переключение Telegram-бота на PostgreSQL

## Предусловия

- VM `vm-robots-dev1`: PostgreSQL, API и frontend healthy.
- Сверены количества рабочих таблиц SQLite и PostgreSQL.
- На VM синхронизирован код и актуальный `.env.prod` (секреты не коммитятся).
- `MINI_APP_URL=https://crm.befa-robotics.com/cabinet/`.

## Окно переключения

У Telegram токена может быть только один long-polling процесс. Поэтому окно
будет коротким: остановить старый bot → запустить новый bot → проверить
`/ready`. API и frontend на Germany2 не останавливаются до контрольного периода.

## Команды

1. На Germany2 сохранить SQLite backup и остановить только основной бот:

```bash
cd /root/bot_service_appointment
cp database_prod/database.db database_prod/database-pre-postgres-cutover.db
docker compose -f docker-compose.prod.yml stop app
```

2. На VM запустить bot рядом с PostgreSQL:

```bash
cd /srv/proffessor-it/cabinet
docker compose -f docker-compose.yml -f ../app/deploy/cabinet/docker-compose.bot.yml up -d --build bot
docker compose -f docker-compose.yml -f ../app/deploy/cabinet/docker-compose.bot.yml ps bot
```

3. Smoke check: написать `/start` тестовому аккаунту, открыть кабинет,
создать/отменить тестовую запись и проверить `/ready` внутри контейнера.

## Rollback

Если `/ready` не становится healthy или Telegram не отвечает, остановить bot
на VM и вернуть app на Germany2:

```bash
cd /srv/proffessor-it/cabinet
docker compose -f docker-compose.yml -f ../app/deploy/cabinet/docker-compose.bot.yml stop bot
ssh Germany2 'cd /root/bot_service_appointment && docker compose -f docker-compose.prod.yml start app'
```

SQLite не удаляется в течение контрольного периода. Новый бот не должен
переключаться до отдельного восстановления Google Calendar credentials.
