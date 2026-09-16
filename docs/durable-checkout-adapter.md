# Durable Telegram checkout adapter

The private Telegram checkout router now uses this adapter for initial YooKassa
recurring buy/renew/consent/recovery and explicit next-purchase actions. It runs
before both old SaaS and provider-routing handlers, including old recurring
callbacks. Do not activate sales or deploy it as an accepted commercial flow:
actual SaaS/provider/runtime acceptance is still required. SaaS remains the
only owner of Orders, Payments, subscriptions, paid periods and VPN desired state.

`CheckoutCoordinator.prepare` resolves the current Telegram-to-SaaS owner, reads
the server current checkout before selecting a fresh operation, and persists the
original tariff/amount/period/device/traffic terms. A caller must render these
terms and obtain explicit recurring consent before calling `confirm`. The UI must
run only in an authenticated private chat; use a stable source-message callback
identity, not Telegram callback.id, and place the opaque operation ID in action
buttons. Callback aliases survive cancellation and completion, so a replay always
refers to the original intent. A selection made while another local intent is
unresolved attaches to that intent, even if the selection differs.

Migration 46 adds local `checkout_intents` and `checkout_callbacks`; no business
tables or runtime access are changed. SQLite FULL synchronous transactions and an
unresolved-per-Telegram-user unique index protect independent connections. Scope
includes a hash of endpoint/tenant/credential and the original SaaS owner. Credential
rotation/relinking cannot silently adopt unresolved work. The journal contains no
payment URL, VPN subscription URL, bearer credential or provider payment method.

`confirm` checks the current owner, renewal target and server predecessor, then
commits DISPATCHED before its single POST. Only the winner of this transition may
send. Restart, cancellation, timeout, invalid response or a lost response do not
permit another POST. There is no lease expiry or automatic retry. Crash after the
dispatch marker but before network remains unresolved and needs a future server
recovery protocol; elapsed time and a 404 are not proof of non-dispatch.

`recover` uses original-key and current-operation GETs. It validates bounded
snapshots and matches original terms/purchase kind before recording terminal
evidence. A received CHECKOUT_ADMISSION_REQUIRED is retained only as a receipt.
After original-key CHECKOUT_NOT_FOUND, GET `/bot/orders/checkout/rejection`
must return the exact version-1 INITIAL_SAVED / NOT_ADMITTED / final=true /
allowNewCreate=false proof before SQLite commits TERMINAL / NOT_ADMITTED.
This also resolves a lost refusal response without replaying POST. The original
row and callback aliases remain permanently; a later Order cannot rebind them.
An already observed Order cannot disappear or acquire rejection proof. Missing,
unavailable or malformed proof keeps the dispatch unresolved. Unknown or
contradictory state cannot allocate a new local operation. A fresh next purchase
requires a new explicit action and exactly the verified terminal predecessor.

`cancel` cancels only a still-PREPARED local intent. It cannot cancel an Order,
payment or dispatched request. Bot authenticated undispatched-Order abandonment
is not available in the SaaS contract yet; Web supports that separate action.

Compatibility: create_order's new consent/predecessor fields are optional for old
callers. ONE_TIME still uses SaaS default provider routing through its existing
creation helper; source-choice identity is stable but this is not durable ONE_TIME
admission/recovery. Recurring callbacks no longer reach the old creation helpers
through the installed SaaS router. This adapter currently targets initial
YooKassa recurring checkout, consuming SaaS #299/#300; ONE_TIME and Platega remain
required and need shared admission/recovery. Platega recurring stays disabled.

Tests exercise the real Python HTTP client against an isolated loopback API
fixture and file-backed SQLite with independent connections: persistence before
POST, competing confirmations, restart/lost response, original callback replay,
scope/owner/target change, stale predecessor, rejection/outage and invalid private
snapshots. The API fixture is not real SaaS/PostgreSQL/provider acceptance.

Private UI references are persisted by migration47 and contain only owner/scope
and original selection/operation IDs. The chosen amount/period/device/traffic and
autorenewal consent are displayed separately before dispatch. Status distinguishes
payment, configuration readiness and recurring activation. Payment URLs are only
exposed after an explicit button action rechecks owner and original current Order;
they are not persisted. An already-issued Telegram URL button cannot be recalled
reliably from every old message; server payment/session policy remains necessary.

Discovery precedes catalog reads, including old callbacks and missing local state.
Catalog/transport failures produce bounded private retry/support text. PREPARING
server abandonment directs the user to the same payment in the linked Web account
or support; a local confirmation cancel never substitutes for that server action.

Next: verify the actual Python client against
actual SaaS + disposable PostgreSQL and Web/Bot cross-channel contention. Then
separately prove real payment, VPN traffic, renewal, expiry/restoration, refund,
support and Entry/Exit replacement. Source and CI do not prove runtime readiness.
