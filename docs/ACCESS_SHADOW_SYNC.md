# WaveMesh access shadow synchronization

This integration projects safe legacy Bot VPN-key state into the WaveMesh SaaS
`VpnAccess` read model. The local SQLite database remains the source of truth,
and the Telegram UI continues to render from local data.

## Safety boundaries

The projection sends only:

- Telegram user identity and display metadata;
- legacy numeric key ID;
- expiry and enabled/configured booleans;
- subscription readiness as a boolean;
- normalized device limit;
- traffic quota and usage counters in bytes.

It never sends or logs:

- client UUID;
- panel email;
- panel inbound ID;
- subscription ID or subscription URL;
- panel credentials;
- VPN configuration material.

The SaaS endpoint is idempotent and staging-only. Sync failures are logged and do
not affect local key creation, extension, display, or VPN-panel operations.

## Bot gates

The write path is disabled by default:

```env
WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED=false
WAVEMESH_ACCESS_SHADOW_BACKFILL_LIMIT=50
```

`WAVEMESH_INTERNAL_API_TOKEN` must belong to a service client with both the
existing read/user scopes and `bot:access:write`.

## Staged rollout

1. Deploy the code with `WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED=false`.
2. Confirm the Bot startup probe and existing dashboard shadow-read still work.
3. Install a short-lived credential containing `bot:access:write`.
4. Enable the Bot gate while the SaaS staging import gate is enabled.
5. Restart the Bot and verify the bounded startup backfill log.
6. Open **My Keys** and verify local and SaaS aggregate counts match.
7. Keep SQLite and the local UI as the operational source until a later cutover.

The startup backfill is bounded and uses deterministic idempotency keys. Opening
**My Keys** refreshes that user's projections before comparing counts. Key
delivery also schedules a non-blocking single-key refresh.

## Expected logs

A successful five-key staging backfill resembles:

```text
WaveMesh access shadow backfill completed: {'selected': 5, 'synced': 5, 'failed': 0}
```

The dashboard comparison should then resemble:

```text
WaveMesh dashboard shadow-read completed: telegram_id=... trigger=callback status=match local_keys=5 saas_accesses=5 synced=5 sync_failed=0
```

No token, UUID, panel email, subscription ID, or subscription URL should appear
in either log line.
