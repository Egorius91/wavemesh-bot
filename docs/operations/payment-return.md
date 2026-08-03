# Telegram payment return

## Purpose

WaveMesh SaaS owns payment confirmation and access state. When the Bot creates a YooKassa order, it requests:

```json
{
  "return_channel": "TELEGRAM"
}
```

SaaS gives YooKassa an expiring deep link of the form:

```text
https://t.me/<bot>?start=pay_<opaque-nonce>
```

The redirect is navigation only. The Bot never treats opening the link as proof of payment.

## Resolution flow

The Bot accepts only an exact `/start pay_<32 base64url characters>` payload in SaaS client mode. It sends the opaque value only in the JSON body of:

```text
POST /internal/v1/bot/payment-returns/resolve
```

The raw value is not written to Bot logs, callback data, SQLite or URLs sent to Internal API.

Verified SaaS states are rendered as follows:

- `pending`: YooKassa has not confirmed the payment; retry the same return link later.
- `cancelled`: the order was cancelled or payment was not completed.
- `access_creating`: payment is confirmed and Entry Node is preparing access; retry the same link later.
- `ready`: fetch material from the existing access-material endpoint, then create or refresh the local SQLite projection.
- `support_error`: do not create another payment; support must inspect the durable SaaS state.

## Idempotency and material boundary

- Repeated token resolution is allowed until token expiry.
- Ready processing is serialized per SaaS `access_id` in the Bot process.
- A new local key is found by its material identity before insertion, preventing duplicate projection after an interrupted request.
- Existing renewals update expiry, tariff, traffic limit and traffic-period counters in one SQLite transaction.
- The SaaS-to-SQLite legacy link uses a stable idempotency key.
- Sensitive access material is fetched only after SaaS reports `ready`.
- A new key is automatically sent only on the first local creation. Repeated ready returns show an `Open key` button instead of re-sending material.

## Rollout boundary

This change does not create a payment and does not modify SaaS, Entry Node or Node Builder. Deploy to Bot staging only after the pull request is merged and both Bot CI workflows pass. Do not run a YooKassa test payment until Bot runtime configuration, Internal API scopes, router assembly and read-only acceptance checks are complete.
