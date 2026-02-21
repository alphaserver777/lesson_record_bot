# Rollback: Mini App Migration

## 1) Checkout pre-miniapp baseline

```bash
git fetch --tags
git checkout pre-miniapp-20260221-0934
```

## 2) Restore DB from backup

```bash
cp /home/admsys/backups/lesson_record_bot_20260221_093430/test_bot.db /home/admsys/lesson_record_bot/database/test_bot.db
```

## 3) Restart bot container

```bash
docker restart lesson_record_bot_test
```

## 4) Smoke check

1. `/start` in test bot responds.
2. Presence callbacks `presence_yes=...` and `presence_no=...` are handled.
3. Reminder loop still sends presence prompts.

## Optional: verify backup checksums

```bash
cat /home/admsys/backups/lesson_record_bot_20260221_093430/backup_manifest.json
```
