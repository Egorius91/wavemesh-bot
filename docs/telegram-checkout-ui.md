# Telegram current checkout UI

SaaS mode registers the new private checkout router before provider routing and
the older SaaS router. `/buy`, `buy_key`, `key_renew`, old new/renew/provider
callback formats and opaque `wmco_*` actions use current discovery for both modes.
The source-message/action identity survives a new Telegram callback.id; generated
choice references survive process restart. An old confirmed/cancelled choice
stays bound to its original local intent even after a subsequent purchase.

Every selection creates only a PREPARED intent. The user sees original price,
period, device/traffic limits, target kind, saved payment method and autorenewal
terms; only a separate "Согласен и оплатить" action confirms and dispatches recurring
checkout. ONE_TIME shows a single payment without autorenewal and requires
"Подтвердить и оплатить"; it never sends saved-method consent.
Recovery uses GET and does not require catalog/sales availability. Another Web
checkout is discoverable without a Bot key. Unknown local dispatch is retained
and cannot be replaced by a new tariff/provider or an empty server lookup.

New purchase requires fresh terminal readback, an explicit next action, another
tariff selection and new consent; its stored expected predecessor cannot silently
advance when another device creates an intervening order. Renewals retain the
specifically selected SaaS access. A stale/foreign action never displays a new
owner's private payment URL. URL delivery requires a fresh same-owner/same-order
check; invalid/group/inline/inaccessible updates are rejected without private IO.

Migration47 adds immutable owner/scope-bound UI references. No provider credentials,
checkout URL, VPN UUID or subscription URL are written to either checkout journal.
Pay/configuration/recurring status are distinct; configuration-ready is not a
claim that VPN traffic has been accepted. Support is reachable via the main menu.

ONE_TIME keeps SaaS automatic provider routing, but now enters the same durable
prepare/confirm/one-dispatch/recovery journal as recurring. Mode/provider and
economic terms are validated on readback; rejection kind must match the original
purchase. Lost responses and old callbacks cannot allocate a new operation.
Platega recurring
is rejected with a fresh-selection instruction, never silently rerouted to YooKassa.
All sales/runtime gates and deployment approvals remain separate.

Tests run actual aiogram Dispatcher updates with the real coordinator and isolated
SQLite, mocking the SaaS client at its boundary. Separate adapter tests exercise
real loopback HTTP transport. Neither proves the full Python/SaaS/PostgreSQL/provider
contract; that is the next integration prerequisite before staged/live acceptance.
