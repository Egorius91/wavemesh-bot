import json
import unittest

from bot.services import branding
from bot.utils.action_registry import SYSTEM_BUTTONS


class HappOnboardingTests(unittest.TestCase):
    def test_app_store_links_use_expected_app_ids(self):
        self.assertTrue(branding.HAPP_IOS_RU_URL.endswith("id6783623643"))
        self.assertTrue(branding.HAPP_IOS_GLOBAL_URL.endswith("id6504287215"))

    def test_region_and_connection_callbacks_keep_key_and_region(self):
        context = {"key_id": 42, "platform": "ios", "app": "happ", "region": "ru"}

        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_happ_ru"](context),
            {"callback_data": "onboarding_happ_install:ru:42"},
        )
        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_happ_continue"](context),
            {"callback_data": "onboarding_happ_connection:ru:42"},
        )
        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_happ_help"](context),
            {"callback_data": "onboarding_happ_help:ru:42"},
        )

    def test_happ_buttons_are_hidden_without_key_context(self):
        self.assertIsNone(SYSTEM_BUTTONS["btn_onboarding_happ_ru"]({}))
        self.assertIsNone(SYSTEM_BUTTONS["btn_onboarding_happ_continue"]({}))

    def test_all_happ_page_system_buttons_are_registered(self):
        page_keys = (
            "onboarding_happ_region",
            "onboarding_happ_install_ru",
            "onboarding_happ_install_global",
            "onboarding_happ_connection",
        )
        for page_key in page_keys:
            buttons_json = branding.PAGE_DEFAULTS[page_key][1]
            for button in json.loads(buttons_json):
                if button.get("action_type") == "system":
                    self.assertIn(button["id"], SYSTEM_BUTTONS)

    def test_legacy_ios_buttons_are_migrated_to_fallback_flow(self):
        legacy = json.dumps([
            {
                "id": "btn_happ_ios",
                "label": "Happ",
                "action_type": "url",
                "action_value": branding.HAPP_URL,
            },
            {
                "id": "btn_streisand_ios",
                "label": "Streisand",
                "action_type": "url",
                "action_value": branding.STREISAND_IOS_URL,
            },
        ])

        migrated = branding._migrate_download_ios_happ_flow("download_ios", legacy)
        ids = {button["id"] for button in json.loads(migrated)}

        self.assertNotIn("btn_happ_ios", ids)
        self.assertIn("btn_streisand_ios", ids)
        self.assertIn("btn_onboarding_alt_continue_ios", ids)
        self.assertIn("btn_onboarding_alt_other_back", ids)


if __name__ == "__main__":
    unittest.main()
