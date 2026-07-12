import json
import unittest

from bot.services import branding
from bot.utils.onboarding_callbacks import parse_happ_callback
from bot.utils.action_registry import SYSTEM_BUTTONS


class HappOnboardingTests(unittest.TestCase):
    def test_app_store_links_use_expected_app_ids(self):
        self.assertTrue(branding.HAPP_IOS_RU_URL.endswith("id6783623643"))
        self.assertTrue(branding.HAPP_IOS_GLOBAL_URL.endswith("id6504287215"))

    def test_official_cross_platform_download_links(self):
        self.assertIn("id=com.happproxy", branding.HAPP_ANDROID_GOOGLE_PLAY_URL)
        self.assertTrue(branding.HAPP_ANDROID_APK_URL.endswith("/Happ.apk"))
        self.assertTrue(branding.HAPP_WINDOWS_URL.endswith("/setup-Happ.x64.exe"))
        self.assertTrue(branding.HAPP_MACOS_URL.endswith("/Happ.macOS.universal.dmg"))

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
            "onboarding_happ_install_android",
            "onboarding_happ_install_windows",
            "onboarding_happ_install_macos",
            "onboarding_happ_connection_android",
            "onboarding_happ_connection_windows",
            "onboarding_happ_connection_macos",
        )
        for page_key in page_keys:
            buttons_json = branding.PAGE_DEFAULTS[page_key][1]
            for button in json.loads(buttons_json):
                if button.get("action_type") == "system":
                    self.assertIn(button["id"], SYSTEM_BUTTONS)

    def test_cross_platform_callbacks_keep_platform_and_distribution(self):
        cases = {
            "android": "google_play",
            "windows": "windows",
            "macos": "macos",
        }
        for platform, distribution in cases.items():
            context = {
                "key_id": 42,
                "platform": platform,
                "app": "happ",
                "distribution": distribution,
            }
            self.assertEqual(
                SYSTEM_BUTTONS["btn_onboarding_happ_continue"](context),
                {
                    "callback_data": (
                        f"onboarding_happ_connection:{platform}:{distribution}:42"
                    )
                },
            )
            self.assertEqual(
                SYSTEM_BUTTONS["btn_onboarding_happ_other"](context),
                {"callback_data": f"onboarding_alt_other:{platform}:42"},
            )
            self.assertEqual(
                SYSTEM_BUTTONS["btn_onboarding_alt_other_back"](context),
                {
                    "callback_data": (
                        f"onboarding_happ_install:{platform}:{distribution}:42"
                    )
                },
            )
            self.assertEqual(
                SYSTEM_BUTTONS["btn_onboarding_issue_enable"](context),
                {
                    "callback_data": (
                        f"onboarding_issue:enable:happ:{platform}:{distribution}:42"
                    )
                },
            )

    def test_callback_parser_accepts_legacy_ios_and_new_platform_shape(self):
        self.assertEqual(
            parse_happ_callback("onboarding_happ_install:ru:42"),
            ("ios", "ru", 42),
        )
        self.assertEqual(
            parse_happ_callback(
                "onboarding_happ_install:android:google_play:42"
            ),
            ("android", "google_play", 42),
        )
        self.assertIsNone(
            parse_happ_callback("onboarding_happ_install:windows:apk:42")
        )

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

    def test_legacy_cross_platform_buttons_are_migrated(self):
        cases = {
            "download_android": ("btn_happ_android", "btn_onboarding_alt_continue_android"),
            "download_windows": ("btn_happ_windows", "btn_onboarding_alt_continue_windows"),
            "download_macos": ("btn_happ_macos", "btn_onboarding_alt_continue_macos"),
        }
        for page_key, (legacy_id, continue_id) in cases.items():
            legacy = json.dumps([
                {
                    "id": legacy_id,
                    "label": "Happ",
                    "action_type": "url",
                    "action_value": branding.HAPP_URL,
                },
                {
                    "id": "kept_button",
                    "label": "Fallback",
                    "action_type": "url",
                    "action_value": "https://example.com",
                },
            ])
            migrated = branding._migrate_download_ios_happ_flow(page_key, legacy)
            ids = {button["id"] for button in json.loads(migrated)}
            self.assertNotIn(legacy_id, ids)
            self.assertIn("kept_button", ids)
            self.assertIn(continue_id, ids)
            self.assertIn("btn_onboarding_alt_other_back", ids)

    def test_custom_fallback_without_happ_still_gets_navigation(self):
        custom = json.dumps([
            {
                "id": "btn_hiddify_windows",
                "label": "My Hiddify link",
                "action_type": "url",
                "action_value": branding.HIDDIFY_RELEASES_URL,
                "row": 7,
                "col": 0,
            }
        ])
        migrated = branding._migrate_download_ios_happ_flow(
            "download_windows",
            custom,
        )
        buttons = json.loads(migrated)
        ids = {button["id"] for button in buttons}
        self.assertIn("btn_onboarding_alt_continue_windows", ids)
        self.assertIn("btn_onboarding_alt_other_back", ids)
        self.assertEqual(buttons[0]["label"], "My Hiddify link")
        self.assertEqual(buttons[0]["row"], 0)


if __name__ == "__main__":
    unittest.main()
