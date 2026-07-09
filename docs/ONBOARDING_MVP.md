# WaveMesh onboarding MVP

## User flow

After a new key is configured, the bot opens:

1. `Connection ready` and device selection.
2. OneXray installation for the selected platform.
3. Connection link and QR import.
4. User confirmation or symptom-based troubleshooting.

The existing key delivery remains available through `Advanced users`. Existing
keys, renewals, payments, and recurring billing keep their previous behavior.

## Editable pages

Open a page as an administrator and send `/yaa`:

- `onboarding_ready`
- `onboarding_ios`
- `onboarding_android`
- `onboarding_windows`
- `onboarding_macos`
- `onboarding_connection`
- `onboarding_troubleshoot`
- `onboarding_success`

Existing `/yaa` custom text and media are not overwritten at startup.

## Smoke test

1. Buy and configure a subscription key.
2. Confirm that the device selection opens instead of the raw key.
3. Test each platform and its OneXray installation URL.
4. Click `Application installed` and confirm that the subscription URL and QR
   are shown.
5. Test `VPN enabled`, `Cannot connect`, and both retry actions.
6. Test `Advanced users` and confirm that the previous key delivery still works.
7. Repeat with a one-time key and confirm that its QR and JSON file are sent.
8. Restart the bot and confirm that `/yaa` customizations remain.

## Rollback

Revert the onboarding commit and restart the bot. No database downgrade is
required: unused rows in `pages` are harmless and can remain in SQLite.
