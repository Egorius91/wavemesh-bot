# Access shadow durable outbox

This stage makes legacy key deletion recoverable when the WaveMesh SaaS Internal API is unavailable or the bot restarts.

## Transaction boundary

`database.db_keys_shadow_outbox.delete_vpn_key` performs the following work in one SQLite transaction:

1. clears the payment foreign-key reference;
2. removes notification-log rows;
3. deletes the legacy VPN key;
4. inserts a sanitized disabled access-shadow snapshot into `access_shadow_outbox`.

The local delete cannot commit without the tombstone event, and the tombstone cannot commit without the local delete.

## Delivery

`bot.services.access_shadow_outbox` starts a lightweight worker after a successful Internal API startup probe. It drains due rows in small batches, uses the existing idempotent shadow endpoint, deletes a row only after successful delivery, and retains failures with capped exponential backoff.

Pending rows survive process restarts because they live in the existing SQLite database. The table contains only `AccessShadowSnapshot` fields and no UUIDs, panel credentials, inbound IDs, subscription URLs, or other connection secrets.

Optional environment settings:

- `WAVEMESH_ACCESS_SHADOW_OUTBOX_POLL_SECONDS` (default `15`)
- `WAVEMESH_ACCESS_SHADOW_OUTBOX_BATCH_SIZE` (default `25`, maximum `100`)

## Staging verification

After deployment:

1. confirm `WaveMesh access shadow outbox worker started` in bot logs;
2. delete a disposable key while the Internal API is available;
3. confirm `reason=outbox_delete` and `outbox delivered` log entries;
4. verify `access_shadow_outbox` has zero pending rows;
5. for retry testing, temporarily disable Internal API writes, delete another disposable key, confirm one pending row, restore writes, and confirm the worker delivers and removes it.
