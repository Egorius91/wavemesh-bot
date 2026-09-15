# Private SaaS Telegram boundary

The authoritative SaaS bot accepts user/admin message and callback actions only
from a human actor in that actor's own private chat. `main` installs the boundary
before BotBlockedResetMiddleware and InternalApiDashboardShadowMiddleware, so a
rejected update cannot clear a local blocked flag, schedule upstream shadow work,
reach checkout/cancellation/replacement handlers, or render account material.

Groups, supergroups, channels, other users' private targets, absent/bot actors,
inline callbacks, inaccessible messages (including zero-date Message decoding),
sender_chat and business-connection contexts are denied. The bot sends no public
reply or unsolicited private message. Denied callbacks can receive one fixed
actor-only popup; popup failure does not open the boundary or log raw errors.
Legacy mode routing is unchanged. Background reconciliation is not filtered by
this Telegram ingress middleware.

The shared payment-return delivery path also validates its explicit target before
reading SaaS material or creating a local projection. Verified material carries
its Telegram owner; direct credential rendering and reuse for local projection
reject a different owner. Outgoing bot messages remain valid delivery targets:
their sender is the bot, while the target chat must be the verified owner's chat.
Trial, SaaS key views and guided connection delivery use the same actor/target
predicate. The payment-return command has its own entry guard for direct calls.

Tests exercise actual aiogram Dispatcher ordering with the existing DB/shadow
middlewares, valid and denied Telegram updates, safe popup failure, direct
shared-renderer misuse, cross-owner projection reuse, and private delivery's
existing URL-before-best-effort-projection behavior. Provider/HTTP/DB state is
mocked or ephemeral in CI; no live mutation or real Telegram acceptance follows
from these tests. Historical log containment, durable replacement intents,
distributed writer exclusion and full commercial/VPN acceptance remain separate.
