import unittest

from bot.handlers.user.saas_keys import actions


class ServiceSubscriptionActionsTests(unittest.TestCase):
    def access(self, **patch):
        return {"access_id": "access-12345678", "authority": "managed", "enabled": True,
                "status": "ready", "subscription_kind": "service_subscription", "legacy_key_id": "42",
                "renewal_url": "https://account.example.invalid/pricing?accessId=access-12345678", **patch}

    def test_service_renewal_uses_owned_cabinet_and_never_legacy_key_actions(self):
        buttons = [b for row in actions(self.access()).inline_keyboard for b in row]
        self.assertEqual([b.url for b in buttons if b.url], [self.access()["renewal_url"]])
        callbacks = [b.callback_data for b in buttons if b.callback_data]
        self.assertIn("saas_config:access-12345678", callbacks)
        self.assertFalse(any(value.startswith(("key_renew:", "key_replace:", "onboarding_ready:")) for value in callbacks))

    def test_foreign_access_or_extra_query_cannot_become_a_renewal_button(self):
        for url in ("https://account.example.invalid/pricing?accessId=foreign-access",
                    self.access()["renewal_url"] + "&amount=1", "javascript:alert(1)"):
            buttons = [b for row in actions(self.access(renewal_url=url)).inline_keyboard for b in row]
            self.assertFalse(any(b.url for b in buttons))

    def test_legacy_access_keeps_existing_renewal_and_replacement(self):
        buttons = [b for row in actions(self.access(subscription_kind=None)).inline_keyboard for b in row]
        callbacks = [b.callback_data for b in buttons]
        self.assertIn("key_renew:42", callbacks)
        self.assertIn("key_replace:42", callbacks)
