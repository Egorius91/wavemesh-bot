import unittest
from unittest.mock import AsyncMock, patch

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils import key_sender
from bot.utils.key_card_onboarding import (
    KEY_CARD_TEXT,
    add_onboarding_button,
    normalize_key_card_template,
)


class KeyCardOnboardingMarkupTests(unittest.TestCase):
    def test_setup_button_is_prepended_for_selected_key(self):
        original = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Мои ключи", callback_data="my_keys")]
            ]
        )

        result = add_onboarding_button(original, 42)

        self.assertEqual(result.inline_keyboard[0][0].text, "🧭 Настроить VPN")
        self.assertEqual(
            result.inline_keyboard[0][0].callback_data,
            "onboarding_ready:42",
        )
        self.assertEqual(result.inline_keyboard[1][0].callback_data, "my_keys")

    def test_setup_button_is_not_duplicated(self):
        original = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🧭 Настроить VPN",
                        callback_data="onboarding_ready:42",
                    )
                ]
            ]
        )

        result = add_onboarding_button(original, 42)

        self.assertIs(result, original)
        self.assertEqual(len(result.inline_keyboard), 1)

    def test_known_legacy_instruction_is_replaced(self):
        legacy = (
            "✅ <b>Ваш VPN-ключ!</b>\n\n%ключ%\n\n"
            "📱 <b>Инструкция:</b>\n"
            "Импортируйте в свой клиент."
        )

        self.assertEqual(normalize_key_card_template(legacy), KEY_CARD_TEXT)

    def test_custom_card_copy_is_preserved(self):
        custom = "🔐 <b>Моя карточка</b>\n\n%ключ%"
        self.assertEqual(normalize_key_card_template(custom), custom)


class KeySenderRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_card_uses_onboarding_aware_renderer(self):
        key = {"id": 7, "sub_id": "sub-id"}
        renderer = AsyncMock(return_value="rendered")

        with (
            patch("bot.services.vpn_api.is_subscription_mode", return_value=True),
            patch(
                "bot.utils.key_sender.send_subscription_key_card",
                renderer,
            ),
        ):
            result = await key_sender.send_key_with_qr(
                object(),
                key,
                key_manage_markup=None,
                is_new=False,
            )

        self.assertEqual(result, "rendered")
        renderer.assert_awaited_once_with(
            unittest.mock.ANY,
            key,
            fallback_markup=None,
        )

    async def test_plain_key_keeps_existing_actions_and_adds_setup(self):
        key = {"id": 9, "sub_id": None}
        existing = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="key:9")]
            ]
        )
        core_sender = AsyncMock(return_value="rendered")

        with patch("bot.utils.key_sender._core.send_key_with_qr", core_sender):
            result = await key_sender.send_key_with_qr(
                object(),
                key,
                key_manage_markup=existing,
                is_new=False,
            )

        self.assertEqual(result, "rendered")
        passed_markup = core_sender.await_args.kwargs["key_manage_markup"]
        self.assertEqual(
            passed_markup.inline_keyboard[0][0].callback_data,
            "onboarding_ready:9",
        )
        self.assertEqual(passed_markup.inline_keyboard[1][0].callback_data, "key:9")


if __name__ == "__main__":
    unittest.main()
