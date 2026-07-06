# Live Screen UX Plan

## Goal

Make the Telegram bot chat behave more like an app screen: the user should usually see one current, actionable bot message at the bottom of the chat, while older bot screens are removed when they are no longer useful.

This is a UX cleanup, not a payment-logic change. It must not affect YooKassa payment creation, recurring billing, subscription records, VPN key extension, or admin operations.

## Current Problem

Many flows create a stack of old bot messages: menus, payment prompts, status checks, key details, and repeated navigation screens. The user can still use the bot, but the chat becomes visually noisy and the relevant button may no longer be the last visible thing.

## Target Behavior

1. The newest active user-facing screen is always at the bottom.
2. The previous active bot screen is deleted when a new active screen is shown.
3. The bot only deletes messages that it created and explicitly registered as live screens.
4. User messages are never deleted.
5. Payment and subscription results must remain visible long enough for the user to understand the outcome.
6. If Telegram refuses to delete a message, the bot logs it and continues.

## Definitions

- Live screen: the latest bot message with the current menu, key details, payment screen, or action buttons.
- Final state: a result message such as payment succeeded, payment failed, subscription disabled, or key extended.
- Audit trail: payment, subscription, and key history stored in the database and logs, not in the Telegram chat history.

## Safety Rules

1. Do not delete arbitrary chat history.
2. Do not delete messages from the user.
3. Do not delete messages that were not registered by the live-screen helper.
4. Do not make message deletion required for the flow to continue.
5. Keep admin flows out of the first rollout unless explicitly tested.
6. Keep a feature flag so the behavior can be disabled quickly.

## Feature Flag

Add a setting such as:

```text
live_screen_enabled = 0
```

Initial rollout keeps it disabled by default. After testing in staging, enable it for the test bot, then production.

## Proposed Storage

Create a small table for the last active screen per user/chat:

```sql
CREATE TABLE IF NOT EXISTS user_live_screens (
    telegram_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    screen_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

This keeps deletion scoped and predictable.

## Proposed Helper

Add a small service, for example:

```text
bot/services/live_screen.py
```

Responsibilities:

1. Read the previous live screen for the user.
2. Try to delete it.
3. Send the new message.
4. Store the new message id.
5. Ignore deletion failures after logging them.
6. Provide a method to clear the saved screen when needed.

The helper should support normal text messages first. Photo/media screens can be added later only if needed.

## Rollout Plan

### Phase 1: Documentation and Helpers

- Add this plan.
- Add database helpers and the live-screen service.
- Do not connect it to user flows yet.
- Verify imports and syntax.

### Phase 2: Main User Screens

- Apply live-screen behavior to the main menu and key list/details screens.
- Keep existing business logic unchanged.
- Test ordinary navigation.

### Phase 3: YooKassa Payment Flow

- Apply live-screen behavior to tariff selection, payment instructions, and repeated "I paid" checks.
- Ensure paid, failed, canceled, and pending states remain clear.
- Ensure failed YooKassa orders are still written to `payments.status = failed`.

### Phase 4: Subscription Screen

- Apply live-screen behavior to subscription details and disable-recurring controls.
- Keep the unsubscribe button visible and easy to screenshot for YooKassa requirements.

### Phase 5: Staging Test

- Enable the feature only on staging.
- Run payment tests:
  - successful initial subscription payment;
  - recurring autopayment success;
  - first payment canceled/failed;
  - recurring charge failed;
  - card/payment-method unlink.

### Phase 6: Production Rollout

- Backup production DB.
- Deploy code with feature disabled.
- Restart bot and verify no errors.
- Enable feature flag.
- Test one full user flow.
- Monitor logs.

## Acceptance Criteria

The UX change is ready when:

1. The user always sees the current actionable screen at the bottom.
2. Old registered bot screens disappear when replaced.
3. No user messages are deleted.
4. Payment and subscription outcomes are not hidden prematurely.
5. Payment DB records are still correct for paid, pending, failed, and recurring orders.
6. The feature can be disabled without code rollback.

## Rollback

Fast rollback is done by setting:

```text
live_screen_enabled = 0
```

Code rollback is also simple because each phase should be shipped in a separate small branch or commit.

## Known Follow-up

Production billing logic still needs a deliberate decision:

- extend the next billing date from the actual successful charge time;
- or preserve the previous billing anchor and extend from that anchor.

For staging tests, extending from the actual successful charge is acceptable. For production subscription policy, this should be decided and documented before broad rollout.
