# Unified Professor IT runtime

Этот Ansible-контур разворачивает PostgreSQL, API, CRM/frontend и Telegram-бот
в существующей VM `professorit-web` (`192.168.50.111`). Маркетинговый сайт
остаётся отдельным Compose-проектом в той же VM.

Секреты создаются только на сервере в `/srv/professorit-app/secrets` и не
передаются через Git. Во время репетиции `app_enable_bot: false`: второй
Telegram poller запускать запрещено.

```bash
git fetch origin main --tags
git switch --detach professorit-vX.Y.Z
cd infra/ansible
python3 ../../scripts/verify_crm_release.py
python3 ../../scripts/verify_release_source.py \
  --tag professorit-vX.Y.Z --commit "$(git -C ../.. rev-parse HEAD)" --require-main
ansible-playbook deploy.yml \
  -e release_id=professorit-vX.Y.Z \
  -e release_commit="$(git -C ../.. rev-parse HEAD)"
```

Рабочее развёртывание обычно запускает GitHub Actions после подтверждения
окружения `production`. Ручной путь оставлен только для аварийного случая и
использует те же проверки. Playbook не принимает ветку, короткий SHA или
текущую папку: ему нужны аннотированная метка и полный SHA одной фиксации.

Перед переключением он запускает и проверяет резервную копию PostgreSQL. После
запуска проверяются API, кабинет через Nginx и готовность единственного бота.
При ошибке каталог кода возвращается к предыдущему выпуску; PostgreSQL не
восстанавливается автоматически.
