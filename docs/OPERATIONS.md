# WaveMesh Bot operations runbook

## Background tasks

The bot starts background tasks for:

- daily statistics and backups;
- update checks;
- traffic synchronization;
- expiration notifications.

They are designed to log errors and continue running instead of crashing the bot process.

## Backups

Default database:

```text
/opt/wavemesh-bot/database/wavemesh_bot.db
```

Backup directory:

```text
/opt/wavemesh-bot/backup/
```

Create a manual backup before major updates:

```bash
sudo systemctl stop wavemesh-bot
sudo cp /opt/wavemesh-bot/database/wavemesh_bot.db /opt/wavemesh-bot/database/wavemesh_bot.db.manual-backup
sudo systemctl start wavemesh-bot
```

## Restore

1. Stop the bot.
2. Copy the selected backup to `database/wavemesh_bot.db`.
3. Start the bot manually or through systemd.
4. Check migrations and logs.
5. Verify users, tariffs, servers, keys, and payments in the admin panel.

## Updates

The project contains an in-bot update mechanism based on Git.

Operational rules:

- do not edit production files manually unless you are ready to lose those changes during forced update;
- keep production changes in Git;
- create a backup before major updates;
- verify `GITHUB_REPO_URL` in `config.py` after repository renaming.

## Logs

Systemd logs:

```bash
sudo journalctl -u wavemesh-bot -f
```

Application log:

```text
/opt/wavemesh-bot/logs/bot.log
```

## First production smoke test

After install or update:

1. `/start` works for a regular user.
2. Admin panel opens for admin IDs.
3. A tariff can be created and displayed.
4. At least one server can be added and checked.
5. A test key can be issued.
6. Backups complete without errors.
7. Logs do not show repeated exceptions.
