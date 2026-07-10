# WaveMesh onboarding MVP

## User flow

After a new key is configured, the bot opens:

1. `Connection ready` and device selection.
2. OneXray installation for the selected platform.
3. Connection link and QR import.
4. User confirmation or symptom-based troubleshooting.

The existing key delivery remains available through `Advanced users`. Existing
keys, renewals, payments, and recurring billing keep their previous behavior.

The same wizard can be opened later from an active configured key with
`Configure VPN`, or from Help. Help opens the wizard immediately for one
available key, asks the user to choose when several keys are available, and
shows recovery actions when there is no suitable key.

## Editable pages

Open a page as an administrator and send `/yaa`:

- `onboarding_ready`
- `onboarding_key_select`
- `onboarding_no_available_key`
- `onboarding_ios`
- `onboarding_android`
- `onboarding_windows`
- `onboarding_macos`
- `onboarding_connection`
- `onboarding_connection_alternative`
- `onboarding_troubleshoot`
- `onboarding_issue_enable`
- `onboarding_issue_no_traffic`
- `onboarding_issue_mobile`
- `onboarding_issue_stale`
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
9. Open the wizard from an active key card and confirm that the same key is used.
10. Open the wizard from Help with zero, one, and several available keys.
11. Confirm that expired, unconfigured, and traffic-exhausted keys are not
    offered by Help and do not show `Configure VPN` in their key cards.
12. Choose `Another application`, confirm installation, and verify that the QR
    page uses client-neutral import instructions. Retry actions must stay in
    the alternative-client flow.
13. Test every symptom on the troubleshooting page in both the OneXray and
    alternative-client flows. Back and retry actions must preserve the selected
    client path.

## Rollback

Revert the onboarding commit and restart the bot. No database downgrade is
required: unused rows in `pages` are harmless and can remain in SQLite.
