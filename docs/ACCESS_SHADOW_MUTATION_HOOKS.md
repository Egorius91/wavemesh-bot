# Access shadow mutation hooks

This stage keeps the legacy SQLite database and 3X-UI operations authoritative while refreshing the SaaS `VpnAccess` read model immediately after successful local key mutations.

## Integration point

`database.requests` remains the public database facade used by handlers and schedulers. It imports the original `database.db_keys` functions first and then overlays the same mutation names from `database.db_keys_shadow`.

The wrapper calls the original SQLite function synchronously. Only after that call has returned successfully does it schedule a non-blocking shadow projection. SaaS failures therefore cannot roll back, delay, or alter the local operation.

## Covered mutations

- initial, configured, admin, and subscription key creation;
- expiry extension, including referral extension;
- server/client connection and final configuration updates;
- subscription readiness (`sub_id`) changes;
- tariff and traffic-limit changes;
- single and bulk traffic-counter refreshes;
- monthly traffic reset state;
- local key deletion.

Deletion captures the already-sanitized snapshot before the SQLite row is removed and sends it afterward with `enabled=false`, `configured=false`, and `subscription_ready=false`. No UUID, panel email, inbound ID, `sub_id`, subscription URL, panel credential, or VPN configuration is copied into the tombstone.

## Failure model

- the existing `WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED` gate controls all writes;
- no running asyncio loop means the shadow update is skipped while the local mutation remains successful;
- network and SaaS errors are logged but never propagated into the local database call;
- deterministic access payload idempotency remains handled by `bot.services.access_shadow`;
- startup backfill and the `My Keys` refresh remain reconciliation fallbacks for non-deletion state.

A failed deletion tombstone is currently retried only by the in-process task execution. A durable deletion outbox is intentionally deferred until the SaaS shadow write path is promoted beyond staging.

## Staging verification

1. deploy with the existing shadow gate still enabled;
2. verify bot startup and Internal API probe;
3. extend one test key and confirm a log entry with `reason=extend`;
4. wait for the traffic scheduler and confirm entries with `reason=traffic_bulk`;
5. open `My Keys` and verify `status=match`;
6. do not test physical deletion unless the selected key is disposable.
