# Private access views and future paid periods

Requires the SaaS `scheduled_periods` projection introduced by wavevpn-saas#289
(0b7b9a1815028b66d6478afdec1607619f5912b6). Bot base: #54,
98827acbe8398cc2951ccd83de5692876da02d1f. Both dependencies are unmerged.

The ordinary private access detail view displays each period's tariff and UTC
start/end separately from current configuration readiness. The API owns period
selection, refund exclusion and ordering. Missing optional periods preserve
compatibility with older SaaS responses; malformed periods produce a bounded
display warning without hiding access navigation. At most 100 records are parsed
and three displayed, with duplicate subscription IDs suppressed. Tariff text is
bounded before HTML escaping; dates require explicit timezone information.

A refund gap no longer displays the disabled runtime's epoch deadline. A current
deadline is shown only for ready, enabled configuration. Future payment never
enables configuration or changes replacement/renewal controls. Material delivery
still performs its existing independent verification. Rendering performs only
the owner-scoped dashboard read, and creates no payment, grant or Node command.

Validation covers future paid gaps, pending Node, current plus future access,
private ownership, malformed/large input, UTC conversion, escaping and duplicates.
These are source tests, not proof of Telegram deployment, real VPN traffic,
payment/refund acceptance or exclusion of legacy panel writers.
