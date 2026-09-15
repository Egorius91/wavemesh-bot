# SaaS Node selection and local access projection

Depends on Bot PR51 and SaaS PR277. Source/CI work only; deployment and runtime
acceptance are separate. A local server hostname is not a Node identity.

Private admin grant forms load the tenant-scoped SaaS Entry catalog and refresh
it on selection and confirmation. The selected `requested_node_id` is persisted
with the original durable intent. Retries/readback keep this selection; a Node
mismatch stops reconciliation. Unsubmitted old intents without a Node choice
require operator review. Already dispatched intents still use original readback.

Migration44 adds `saas_access_projections` and the `vpn_keys.saas_managed` marker.
The binding retains tenant/access/Node/SaaS user/local user/Telegram/key/version
identity without panel credentials. It has no cascading foreign key: deletion
of the local key must not authorize another projection. SQLite FULL transactions
serialize concurrent projection creation and commit the key and binding together.
Admin finalization also commits journal DONE in the same transaction.

READY material must agree with the caller-owned managed dashboard's version and
URL. New keys need no local `servers` row. Replays reuse the canonical key;
different Node/owner/key, stale versions and changed same-version material fail
closed. Adoption of an existing key checks its material. Renewal and higher-version
credential rotation update the same key. Traffic has a local high-water mark:
credential rotation does not imply permission for a quota reset.

In SaaS mode, key list/detail/configuration use the authenticated dashboard and
material endpoints. Paid/trial delivery still sends the verified URL before
best-effort local projection/linking. A lost link response reuses the committed
binding and original projection idempotency key. Legacy delete/unlink buttons do
not claim SaaS revocation/cancellation; the provider billing view remains linked.

Managed projection INSERT/UPDATE do not enqueue legacy entitlement snapshots.
Snapshot reads exclude these keys; outbox delivery retires pre-adoption events
when a retained canonical binding exists, including after local key deletion.
This check is not a distributed writer fence: an already-dispatched legacy HTTP
call and old processes still require the SaaS/Agent ownership cutover protocol.

Remaining acceptance: real Telegram/VPN traffic, adopted legacy fleet, durable
replacement intent recovery, operator recovery/revoke workflows, quota-period
reset and grace semantics, Entry migration and Exit expansion, strict writer
exclusion and safe rollback. Do not turn off SaaS mode or roll back migrations
as a substitute for that protocol. Do not infer orphan deletion from SQLite absence.
