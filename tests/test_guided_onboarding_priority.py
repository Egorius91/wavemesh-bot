import json
import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers.user.onboarding import (
    get_onexray_page,
    get_primary_happ_target,
)
from bot.services import onboarding_branding as copy
from bot.utils import key_sender
from bot.utils.action_registry import ACTION_REGISTRY, SYSTEM_BUTTONS
from bot.utils.onboarding_callbacks import parse_happ_callback


class GuidedOnboardingPriorityTests(unittest.TestCase):
    def test_happ_is_primary_for_every_supported_platform(self):
        self.assertEqual(get_primary_happ_target("ios"), ("onboarding_happ_region", None))
        self.assertEqual(
            get_primary_happ_target("android"),
            ("onboarding_happ_install_android", "google_play"),
        )
        self.assertEqual(
            get_primary_happ_target("windows"),
            ("onboarding_happ_install_windows", "windows"),
        )
        self.assertEqual(
            get_primary_happ_target("macos"),
            ("onboarding_happ_install_macos", "macos"),
        )

    def test_onexray_remains_secondary(self):
        self.assertEqual(get_onexray_page("ios"), "onboarding_ios")
        self.assertEqual(get_onexray_page("android"), "onboarding_android")
        self.assertEqual(get_onexray_page("windows"), "onboarding_windows")
        self.assertEqual(get_onexray_page("macos"), "onboarding_macos")
        self.assertIsNone(get_onexray_page("linux"))
        self.assertIn("дополнительный", copy.ONBOARDING_IOS_TEXT.lower())

    def test_official_client_links_are_present(self):
        self.assertTrue(copy.HAPP_IOS_RU_URL.endswith("id6783623643"))
        self.assertTrue(copy.HAPP_IOS_GLOBAL_URL.endswith("id6504287215"))
        self.assertIn("id=com.happproxy", copy.HAPP_ANDROID_GOOGLE_PLAY_URL)
        self.assertIn("onexray", copy.ONEXRAY_APP_STORE_URL.lower())
        self.assertIn("net.yuandev.onexray", copy.ONEXRAY_GOOGLE_PLAY_URL)

    def test_happ_callback_parser_keeps_context(self):
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

    def test_onboarding_actions_are_registered(self):
        self.assertEqual(ACTION_REGISTRY["cmd_onboarding_start"], "onboarding_start")
        for page_key, (_, buttons_json, _, _) in copy.PAGE_DEFAULTS.items():
            if not buttons_json:
                continue
            for button in json.loads(buttons_json):
                if button.get("action_type") == "system":
                    self.assertIn(button["id"], SYSTEM_BUTTONS, page_key)

    def test_primary_navigation_and_secondary_navigation(self):
        base = {"key_id": 42, "platform": "android"}
        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_android"]({"key_id": 42}),
            {"callback_data": "onboarding_platform:android:42"},
        )
        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_onexray"](base),
            {"callback_data": "onboarding_alt_other:android:42"},
        )
        self.assertEqual(
            SYSTEM_BUTTONS["btn_onboarding_back_happ"](base),
            {"callback_data": "onboarding_platform:android:42"},
        )


class NewKeyOnboardingHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_key_starts_guided_onboarding(self):
        target = object()
        key = {"id": 7}
        with patch(
            "bot.handlers.user.onboarding.start_key_onboarding",
            new=AsyncMock(),
        ) as start_mock, patch.object(
            key_sender._core,
            "send_key_with_qr",
            new=AsyncMock(),
        ) as raw_mock:
            await key_sender.send_key_with_qr(target, key, is_new=True)

        start_mock.assert_awaited_once_with(target, key)
        raw_mock.assert_not_awaited()

    async def test_existing_key_uses_standard_sender(self):
        target = object()
        key = {"id": 7}
        with patch.object(
            key_sender._core,
            "send_key_with_qr",
            new=AsyncMock(return_value="sent"),
        ) as raw_mock:
            result = await key_sender.send_key_with_qr(target, key, is_new=False)

        self.assertEqual(result, "sent")
        raw_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
