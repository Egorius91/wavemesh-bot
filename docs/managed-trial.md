# Managed trial in Telegram

Requires SaaS PR275's activation/status contract and its existing internal and
Node pipeline gates. The Bot uses the existing service token, tenant and scopes
(`bot:users:read`, `bot:access:read`, `bot:access:write`). No new runtime flag is
enabled by default. New trials require `NEW_TRIALS_ENABLED=true` in both the
Bot and the SaaS API. The closed paid beta leaves this switch unset or false.
The status command and existing access remain available while new trials are closed.

In SaaS mode, the trial menu and `/trial` read the canonical user's activation.
Only explicit activation submits `POST bot/trials`; user/offer uniqueness in SaaS
is shared with Web. The Bot never creates a local order/key or consumes a local
trial-used mark to initiate this flow. A lost response offers status retrieval.
Reopening the menu after process restart uses GET, without an FSM or polling task.

Ready material is delivered only in the user's private chat through the existing
SaaS ownership check and material delivery path, before best-effort local key
projection. A failed local projection does not suppress configuration delivery.
Terminal/legacy states offer status/help; no fallback panel CREATE is performed.
The legacy trial router remains available only outside SaaS mode.

Tests mock SaaS transport and Telegram rendering; SaaS PR275 supplies separate
PostgreSQL concurrency/receipt/trial-to-paid coverage. Actual email/Telegram
linking, bot delivery, checkout, renewal and VPN traffic still need staging proof.
