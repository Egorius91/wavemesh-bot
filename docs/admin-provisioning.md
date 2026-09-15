# Durable administrative provisioning

In SaaS client mode an admin confirmation creates a local draft and an adapter
operation in one SQLite transaction (migration 43). The Telegram confirmation
message is the replay identity. A second form for the same user reuses unresolved
work owned by the same administrator; another administrator cannot adopt it.
The journal is not an entitlement ledger. SaaS owns the access, its expiry,
runtime identity and provisioning command.

Startup runs a background finalizer after successful SaaS initialization. Status
and explicit reconciliation use the same worker. Each external write has a
committed dispatch phase before HTTP; SQLite FULL synchronization, a write
transaction and fencing token protect the journal across processes. No network
request runs inside a database transaction. An expired lease does not permit a
second submission. A worker that lost its lease cannot finalize local state.

User/shadow delivery is reconciled through the owner's dashboard; provisioning
uses GET `/internal/v1/bot/access-provisioning` with the original Idempotency-Key.
This requires SaaS PR276 (and its dependencies), currently unmerged. Unknown
results remain unresolved. A crash after dispatch intent but before HTTP can
require operator reconciliation: this adapter deliberately cannot prove that a
write did not happen and does not automatically repeat CREATE.

READY recovery verifies canonical owner, local-key/access binding, command/Node
readback, dashboard material version/URL and expiry. It updates the original key
and DONE status atomically. Deleted keys are never recreated, changed credentials
are never overwritten, and FAILED/TIMEOUT/MANUAL_REVIEW remain visible. The
journal stores no VPN credentials, subscription URL or raw exception message.

Scope is conservatively bound to a hash of API URL, tenant and credential. This
is not a ServiceClient ID claim: even rotation of the same client's token needs
explicit reconciliation; a different client cannot silently inherit old work.

The old local Entry/inbound selection is bypassed in SaaS mode; SaaS chooses the
Entry. Local projection requires exactly one active server whose configured host
matches the validated subscription URL host. There is no single-server fallback.
Different public/panel hostnames or ambiguous mappings require review. The existing
SaaS admin API still requires explicit requested_node_id when multiple Entries
are eligible. A canonical Node catalog/mapping and multi-Entry admin selection
remain necessary follow-up work; this PR does not claim fleet readiness.

The disposable SQLite tests use the real migration chain and separate connections,
with concurrent preparation, lease takeover, lost user/shadow/create responses,
failed local commits, deletion, scope/ownership changes and terminal failure.
HTTP and Telegram boundaries are simulated. No deployment or live VPN acceptance
is established. Bot #28 stays open for runtime orphan discovery/reconciliation,
Node mapping, operator recovery and end-to-end staging acceptance. This change
also does not prove exclusion of legacy panel writers.
