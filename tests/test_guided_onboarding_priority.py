import json
import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers.user.onboarding import (
    get_onexray_page,
    get_primary_happ_target,
)
from bot.services import branding
from bot.utils import key_sender
from bot.utils.action_registry import SYSTEM_BUTTONS
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

    def test_onexray_remains_a_secondary_platform_path(self):
        self.assertEqual(get_onexray_page("ios"), "onboarding_ios")
        self.assertEqual(get_onexray_page("android"), "onboarding_android")
        self.assertEqual(get_onexray_page("windows"), "onboarding_windows")
        self.assertEqual(get_onexray_page("macos"), "onboarding_macos")
        self.assertIsNone(get_onexray_page("linux"))

    def test_official_happ_and_onexray_links_are_present(self):
        self.assertTrue(branding.HAPP_IOS_RU_URL.endswith("id6783623643"))
        self.assertTrue(branding.HAPP_IOS_GLOBAL_URL.endswith("id6504287215"))
        self.assertIn("id=com.happproxy", branding.HAPP_ANDROID_GOOGLE_PLAY_URL)
        self.assertIn("onexray", branding.ONEXRAY_APP_STORE_URL.lower())
        self.assertIn("net.yuandev.onexray", branding.ONEXRAY_GOOGLE_PLAY_URL)

    def test_happ_callback_contracts_keep_platform_distribution_and_key(self):
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

    def test_all_onboarding_system_buttons_are_registered(self):
        for page_key, (_, buttons_json, _, _) in branding.PAGE_DEFAULTS.items():
            if not page_key.startswith("onboarding_") or not buttons_json:
                continue
            for button in json.loads(buttons_json):
                if button.get("action_type") == "system":
                    self.assertIn(button["id"], SYSTEM_BUTTONS, page_key)


class NewKeyOnboardingHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_default_delivery_starts_guided_onboarding(self):
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

    async def test_existing_or_onboarding_delivery_uses_raw_sender(self):
        target = object()
        key = {"id": 7}
        with patch.object(
            key_sender._core,
            "send_key_with_qr",
            new=AsyncMock(return_value="sent"),
        ) as raw_mock:
            result = await key_sender.send_key_with_qr(
                target,
                key,
                is_new=False,
                page_key="onboarding_happ_connection",
                onboarding_platform="ios",
                onboarding_app="happ",
                onboarding_region="ru",
                onboarding_distribution="ru",
            )

        self.assertEqual(result, "sent")
        raw_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
