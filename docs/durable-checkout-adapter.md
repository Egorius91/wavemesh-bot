# Durable Telegram checkout adapter

This is the adapter prerequisite for replacing the existing Telegram purchase
handlers. It is not enabled by a new flag and is not called by those handlers yet.
Do not activate sales or deploy it as a completed customer flow. SaaS remains the
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
evidence. A received CHECKOUT_ADMISSION_REQUIRED is durably retained; only this
receipt and authenticated original-key CHECKOUT_NOT_FOUND can resolve an
unadmitted attempt. Lost rejection without receipt remains unknown. Unknown or
contradictory state cannot allocate a new local operation. A fresh next purchase
requires a new explicit action and exactly the verified terminal predecessor.

`cancel` cancels only a still-PREPARED local intent. It cannot cancel an Order,
payment or dispatched request. Bot authenticated undispatched-Order abandonment
is not available in the SaaS contract yet; Web supports that separate action.

Compatibility: create_order's new consent/predecessor fields are optional for old
callers, and existing ONE_TIME payloads are unchanged. This does not make the old
handlers safe: their callback.id-based identity and missing recurring consent
must be replaced before activation. This adapter currently targets initial
YooKassa recurring checkout, consuming SaaS #299/#300; ONE_TIME and Platega remain
required and need shared admission/recovery. Platega recurring stays disabled.

Tests exercise the real Python HTTP client against an isolated loopback API
fixture and file-backed SQLite with independent connections: persistence before
POST, competing confirmations, restart/lost response, original callback replay,
scope/owner/target change, stale predecessor, rejection/outage and invalid private
snapshots. The API fixture is not real SaaS/PostgreSQL/provider acceptance.

Next: wire private Telegram buy/renew/consent/status/next-purchase handlers to this
coordinator; preserve original operations even when catalog/gates are unavailable;
provide current-operation discovery without a local key; verify Python against
actual SaaS + disposable PostgreSQL and Web/Bot cross-channel contention. Then
separately prove real payment, VPN traffic, renewal, expiry/restoration, refund,
support and Entry/Exit replacement. Source and CI do not prove runtime readiness.
