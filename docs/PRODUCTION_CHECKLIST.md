# WaveMesh Production Checklist

Use this checklist before merging and deploying the YooKassa recurring subscriptions branch to production.

## 1. Release Gate

- [ ] Staging bot is running from `feature/yookassa-recurring-subscriptions`.
- [ ] Staging uses a separate bot token, database, YooKassa test shop, and systemd service.
- [ ] Successful first subscription payment stores `payment_method_id`.
- [ ] Successful recurring charge extends the VPN key.
- [ ] Failed recurring charge creates a `yookassa_recurring` payment with `status = 'failed'`.
- [ ] Subscription moves to `payment_failed` and increments `failed_attempts` on failed recurring charge.
- [ ] Card unlink button clears `subscriptions.payment_method_id`.
- [ ] Card unlink keeps access active until the paid period ends.
- [ ] User UI shows active auto-renewal status and next charge date.
- [ ] YooKassa screenshot requirements are satisfied for card unlink flow.
- [ ] Billing anchor decision is made: renew from successful charge time or previous planned billing date.

## 2. Code Review

- [ ] No production secrets are committed.
- [ ] No test bot token is committed.
- [ ] No YooKassa shop ID or secret key is committed.
- [ ] No staging SQLite database is committed.
- [ ] `main.py` starts the recurring billing scheduler.
- [ ] `bot/services/subscription_billing.py` handles successful and failed recurring charges.
- [ ] Failed recurring orders are marked `failed`, not left `pending`.
- [ ] One-click/QR first payments still work for non-recurring tariffs.
- [ ] Existing Telegram Provider Token card flow is not used for recurring subscriptions.
- [ ] Admin payment settings still load and save correctly.
- [ ] Local syntax check passes:

```bash
python -m py_compile main.py bot/services/subscription_billing.py bot/handlers/user/payments/yookassa.py database/requests.py
```

## 3. Production Backup

- [ ] Confirm current production project directory.
- [ ] Confirm current production service name.
- [ ] Confirm current production database path.
- [ ] Stop only when deploy window starts, not during preparation.
- [ ] Create SQLite backup before deploy:

```bash
sqlite3 /path/to/production.db ".backup '/path/to/backup/wavemesh_bot_before_recurring_YYYY-MM-DD.db'"
```

- [ ] Save current git commit:

```bash
git rev-parse HEAD
```

- [ ] Save current service status and logs:

```bash
sudo systemctl status wavemesh-bot --no-pager
sudo journalctl -u wavemesh-bot -n 200 --no-pager > /tmp/wavemesh-prod-before-recurring.log
```

## 4. Production Env

- [ ] Production `.env` still contains the production Telegram bot token.
- [ ] Production `.env` points to the production database only.
- [ ] Production YooKassa shop ID is the real production shop ID.
- [ ] Production YooKassa secret key is the real production secret key.
- [ ] Test YooKassa credentials are not present in production.
- [ ] `DATABASE_PATH` is either set correctly or the app uses the existing production DB path.
- [ ] systemd `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` point to production paths.

## 5. YooKassa Go-Live Requirements

- [ ] Store short name for bank statement is agreed with YooKassa.
- [ ] Short name format fits YooKassa requirement: `YM*` plus up to 11 allowed characters.
- [ ] YooKassa cabinet has production recurring/one-click capability enabled.
- [ ] Bot screenshots show the bot name.
- [ ] Screenshots show how a user unlinks a card.
- [ ] Card unlink removes the local recurring token immediately.
- [ ] No separate YooKassa API request is required for unlinking.

## 6. Deploy

- [ ] Merge branch only after all staging checks pass.
- [ ] Pull production code:

```bash
cd /opt/wavemesh/production
git fetch origin
git status
git pull
```

- [ ] Install or update dependencies if `requirements.txt` changed:

```bash
.venv/bin/pip install -r requirements.txt
```

- [ ] Run migrations explicitly if the project supports it, or start once and confirm migrations in logs.
- [ ] Restart production service:

```bash
sudo systemctl restart wavemesh-bot
```

## 7. Post-Deploy Smoke Test

- [ ] Service is active:

```bash
sudo systemctl status wavemesh-bot --no-pager
```

- [ ] Logs show startup without errors:

```bash
sudo journalctl -u wavemesh-bot -n 200 --no-pager
```

- [ ] Logs show recurring billing scheduler started.
- [ ] Admin panel opens.
- [ ] Payment settings open.
- [ ] Existing users can open the bot.
- [ ] Existing keys are visible.
- [ ] Existing non-recurring purchase path still opens.
- [ ] Existing subscription key display shows auto-renewal state correctly.

## 8. Production Payment Test

Run minimal live checks only with an intentionally small/controlled tariff if possible.

- [ ] Create or select a production recurring tariff.
- [ ] Make first real payment.
- [ ] Confirm `payments.status = 'paid'`.
- [ ] Confirm `payments.payment_method_id` is saved.
- [ ] Confirm `subscriptions.payment_method_id` is saved.
- [ ] Confirm `subscriptions.status = 'active'`.
- [ ] Confirm `subscriptions.next_charge_at` is correct.
- [ ] Confirm VPN key was created or extended.
- [ ] Confirm user sees active subscription and next charge date.
- [ ] Confirm card unlink clears local `payment_method_id`.

## 9. Monitoring After Deploy

- [ ] Watch logs for at least 30 minutes:

```bash
sudo journalctl -u wavemesh-bot -f
```

- [ ] Check failed payments are not repeatedly retried every minute forever.
- [ ] Check scheduler does not create duplicate recurring orders for the same due subscription.
- [ ] Check pending YooKassa checkout payments do not incorrectly issue VPN keys.
- [ ] Check users with unlinked cards are not charged.
- [ ] Check production database size and service memory are stable.

## 10. Rollback

- [ ] Keep previous commit SHA ready.
- [ ] Roll back code if startup, payments, or key provisioning break:

```bash
cd /opt/wavemesh/production
git checkout <previous_commit_sha>
sudo systemctl restart wavemesh-bot
```

- [ ] Restore database only if a migration or data mutation corrupted production data.
- [ ] If database restore is needed, stop the bot before restore.
- [ ] After rollback, verify existing bot flows and logs.

## 11. Known Follow-Ups

- [ ] Decide and implement final production billing anchor policy.
- [ ] Decide cleanup policy for old `pending` YooKassa checkout payments.
- [ ] Decide retry policy for `payment_failed` subscriptions.
- [ ] Decide whether failed recurring subscriptions should clear `payment_method_id` immediately or keep it for manual retry.
- [ ] Add an admin report for active, failed, canceled, and due subscriptions.
