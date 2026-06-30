# WaveMesh Bot

Telegram bot for managing user access, tariffs, payments, referrals, broadcasts, and server-side connection records through an admin panel.

## Features

- Telegram user interface.
- Telegram admin panel.
- User, tariff, trial, referral, and broadcast management.
- Payment provider modules.
- Server records and access record management.
- SQLite database with automatic migrations.
- Ubuntu/systemd deployment through `install.sh`.

## One-command install on Ubuntu 24.04

Run as root on a clean VPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Egorius91/wavemesh-bot/main/install.sh)
```

The installer will ask for:

- repository URL;
- branch;
- Telegram `BOT_TOKEN`;
- admin Telegram IDs.

It installs system packages, creates a `wavemesh` system user, clones the project into `/opt/wavemesh-bot`, creates a Python virtual environment, writes `config.py`, installs a systemd service, runs migrations, and starts the bot.

## Service commands

```bash
systemctl status wavemesh-bot
journalctl -u wavemesh-bot -f
systemctl restart wavemesh-bot
systemctl stop wavemesh-bot
```

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.py config.py
python main.py
```

Before deployment, edit `config.py` and set real values for:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `GITHUB_REPO_URL`
- payment provider settings
- server settings through the admin panel

## Production files

Default project directory:

```text
/opt/wavemesh-bot
```

Default SQLite database:

```text
/opt/wavemesh-bot/database/wavemesh_bot.db
```

Application log:

```text
/opt/wavemesh-bot/logs/bot.log
```

Automatic backups:

```text
/opt/wavemesh-bot/backup/
```

## First manual smoke test

After installation:

1. Open the Telegram bot.
2. Send `/start`.
3. Confirm that the main page renders.
4. Confirm that the admin panel button appears for your admin ID.
5. Add a server in the admin panel.
6. Add a tariff.
7. Create a test key.
8. Check service logs.

## Notes

This codebase is intended to be a standalone bot. External branded admin-agent integrations are intentionally removed.
