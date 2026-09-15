# Durable private credential replacement

This flow replaces credentials on the same managed SaaS access and Entry Node.
It does not migrate an access between Nodes, create an order, change its paid
period, or reset traffic. SaaS remains authoritative and Node Agent executes
`access.replace_credential`.

## Confirmation and recovery

`key_replace:<local-key>` now opens a private confirmation. Migration 45 stores
the original Telegram actor, local key/user, tenant, SaaS user/access/Node,
expected base version and request identity in `access_replacements`. A hash of
the configured API endpoint, tenant and credential binds the caller scope; the
credential itself is never stored in the journal. Source-message aliases survive
completion and local key deletion. Another click or Telegram callback ID on an
old message returns its original operation. A fresh replacement requires a new
confirmation; replaying its parent `replacement_new` button also returns the
same successor. All confirmation actions verify the private actor and scope.

Only one unresolved operation per tenant/access can exist. SQLite transactions
and expiring, token-fenced leases coordinate separate Bot processes using the
same durable database. PREPARED confirmations expire after ten minutes and may
be cancelled. A confirmed QUEUED operation records DISPATCHED **before** HTTP.
After that marker the worker never sends another replacement POST, including
after timeout, process restart, malformed response, lease expiry or HTTP error.

POST carries the original request key and `{expected_version: <base>}`. GET uses
that same key with `/replacement?expected_version=<base>`. A successful POST's
command ID and the first GET request ID are retained and cannot change. Missing
or unconfirmed results do not authorize retry or another intent. The worker
polls at bounded intervals; identity/scope conflicts require manual review.
The deliberate crash window between DISPATCHED and actual HTTP can remain
unconfirmed indefinitely: resolving it requires authoritative evidence, never
deleting the journal or inventing a new request key.

READY requires the original command's successful readback, the exact target
version (base + 1), and matching owner/access/Entry and active dashboard/material.
Updating the existing local projection and marking DONE share one transaction.
The local key ID, tariff and traffic high-water mark are preserved. Removed or
foreign projections are not recreated. Terminal command failure and a succeeded
original command superseded by later state close the operation without adopting
unrelated material. New attempts still require a current canonical ready binding.
A stale local binding must be reconciled through an authorized projection path;
opening a normal access view alone does not update it.

The background worker completes projection without Telegram delivery. The user's
result button fetches exact authenticated material again before displaying a
subscription URL. Replaying an older completed operation after another rotation
does not display the newer credential as that old operation's result. No raw
HTTP exception, credential, UUID/subId, material or subscription URL is logged or
stored in the replacement journal (the existing canonical key projection still
stores the fields required by its contract).

## Compatibility and acceptance boundaries

Requires SaaS PRs #278/#279 and the canonical projection/private event boundary
from Bot #52/#53. SaaS #279 rejects old empty-body replacement POSTs. Coordinate
deployment so the old replacement handler cannot run against the new contract;
rolling back to the old handler would restore unsafe callback semantics. Keep
the database and all journal/alias tombstones when stopping or rolling back this
worker. Do not reinterpret a legacy unversioned request as a new versioned one;
historical SaaS requests have a separate GET-only recovery contract.

Tests cover real SQLite transactions and separate processes, concurrent
confirmation/leases, late HTTP completion, failures before/after dispatch,
atomic projection rollback, immutable request/command/Node/owner bindings,
cancelled/stale/old-message replay, explicit successors, private aiogram router
delivery, adapter validation and worker startup/shutdown. These source tests do
not prove live Telegram delivery, VPN traffic, old-writer exclusion, backup
restore, quota/grace/referral/revoke or Entry/Exit migration acceptance.
