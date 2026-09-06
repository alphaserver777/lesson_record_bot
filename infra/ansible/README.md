# Unified Professor IT runtime

Этот Ansible-контур разворачивает PostgreSQL, API, CRM/frontend и Telegram-бот
в существующей VM `professorit-web` (`192.168.50.111`). Маркетинговый сайт
остаётся отдельным Compose-проектом в той же VM.

Секреты создаются только на сервере в `/srv/professorit-app/secrets` и не
передаются через Git. Во время репетиции `app_enable_bot: false`: второй
Telegram poller запускать запрещено.

```bash
cd infra/ansible
python3 ../../scripts/verify_crm_release.py
ansible-playbook provision.yml
ansible-playbook deploy.yml -e release_id=$(git -C ../.. rev-parse --short HEAD)
```

Развёртывать CRM можно только из ветки `release/contact-unification` до её
объединения с `dev`. Проверка `verify_crm_release.py` обязательна: она не даст
выкатить старый контур бота, в котором нет PostgreSQL, контактов и воронки.
После запуска playbook дополнительно проверяет эти адреса через Nginx, а не
только общий адрес `/health`.

После финального dump/restore и остановки старого бота установить
`app_enable_bot: true`, повторить deploy и проверить `/ready`.
