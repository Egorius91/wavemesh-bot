# WaveMesh Staging Deployment

This runbook creates a staging bot next to production without reusing the production bot token, YooKassa credentials, or SQLite database.

## Inputs

- Branch: `feature/yookassa-recurring-subscriptions`
- Staging directory: `/opt/wavemesh/staging`
- Staging service: `wavemesh-staging.service`
- Staging database: `/opt/wavemesh/staging/database/wavemesh_bot_staging.db`

## 1. Find production safely

Run on the server:

```bash
systemctl list-units --type=service | grep -i wavemesh
systemctl cat wavemesh-bot.service
systemctl show wavemesh-bot.service -p WorkingDirectory -p ExecStart -p FragmentPath
ps aux | grep -E 'wavemesh|main.py' | grep -v grep
```

Do not copy production `config.py`, `.env`, bot token, YooKassa credentials, or database into staging.

## 2. Create the test Telegram bot

Create a separate bot in BotFather, for example `WaveMesh Test` with a free username such as `WaveMeshVPNTestBot`.

Use this token only for staging.

## 3. Install staging

From the cloned branch on the server:

```bash
sudo bash scripts/install-staging.sh
```

The script clones/updates `/opt/wavemesh/staging`, creates `/opt/wavemesh/staging/.venv`, writes `/opt/wavemesh/staging/.env`, writes a staging `config.py`, installs dependencies, runs migrations on the staging DB, installs `wavemesh-staging.service`, and starts it.

Manual equivalent:

```bash
sudo mkdir -p /opt/wavemesh
sudo git clone --branch feature/yookassa-recurring-subscriptions https://github.com/Egorius91/wavemesh-bot.git /opt/wavemesh/staging
cd /opt/wavemesh/staging
sudo cp .env.staging.example .env
sudo cp deploy/config.staging.py.example config.py
sudo nano .env
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp systemd/wavemesh-staging.service /etc/systemd/system/wavemesh-staging.service
sudo systemctl daemon-reload
sudo systemctl enable wavemesh-staging
sudo systemctl start wavemesh-staging
```

## 4. Verify isolation

```bash
sudo systemctl status wavemesh-staging
sudo journalctl -u wavemesh-staging -n 100 --no-pager
sudo systemctl show wavemesh-staging -p WorkingDirectory -p ExecStart -p EnvironmentFiles
sudo ls -la /opt/wavemesh/staging/database/
```

The staging DB path must be `/opt/wavemesh/staging/database/wavemesh_bot_staging.db`.

## 5. Configure YooKassa in staging

In the staging bot admin panel/settings:

- set the test Shop ID;
- set the test Secret Key;
- enable direct YooKassa API / QR payments;
- do not use Telegram Provider Token for recurring subscriptions;
- do not use the production YooKassa shop.

## 6. Telegram smoke test

In the staging bot:

1. Open `/start`.
2. Open the admin panel.
3. Check payment settings.
4. Create a recurring test tariff.
5. Make the first test payment through YooKassa API.
6. Confirm that `payment_method_id` is saved.

## 7. Database checks

```bash
sqlite3 /opt/wavemesh/staging/database/wavemesh_bot_staging.db \
"SELECT id, user_id, vpn_key_id, tariff_id, status, payment_method_id, next_charge_at
 FROM subscriptions
 ORDER BY id DESC
 LIMIT 5;"
```

Force a test subscription to become due:

```bash
sqlite3 /opt/wavemesh/staging/database/wavemesh_bot_staging.db \
"UPDATE subscriptions
 SET next_charge_at = datetime('now', '-1 hour')
 WHERE id = <subscription_id>;"
```

Then wait for the scheduler or restart staging:

```bash
sudo systemctl restart wavemesh-staging
sudo journalctl -u wavemesh-staging -f
```

Check recurring charge result:

```bash
sqlite3 /opt/wavemesh/staging/database/wavemesh_bot_staging.db \
"SELECT id, status, last_payment_id, next_charge_at, failed_attempts
 FROM subscriptions
 ORDER BY id DESC
 LIMIT 5;"
```

## Ready criteria

Staging is ready when the test bot runs separately from production, the DB path is separate, YooKassa uses test credentials, recurring tariffs can be created, the first payment stores `payment_method_id`, recurring charge extends the VPN key, and the production bot remains untouched.
