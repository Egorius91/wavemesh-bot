# WaveMesh Bot

Telegram bot for managing user access, tariffs, payments, referrals, broadcasts, and server-side connection records through an admin panel.

## Features

- Telegram user interface.
- Telegram admin panel.
- User, tariff, trial, referral, and broadcast management.
- Payment provider modules.
- Server records and access record management.
- SQLite database with automatic migrations.
- GitHub Actions checks for syntax, imports, database migrations, router assembly, and removed external admin-agent references.

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

## Notes

This codebase is intended to be a standalone bot. External branded admin-agent integrations are intentionally removed.
