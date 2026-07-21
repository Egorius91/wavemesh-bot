import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.services import onboarding_branding
from bot.services import page_context
from bot.utils import message_editor
from bot.utils.onboarding_delivery import send_onboarding_connection
from bot.utils.yaa_context import build_yaa_help_text


class OnboardingYaaRegistrationTests(unittest.TestCase):
    def test_all_onboarding_pages_are_registered_for_yaa(self):
        onboarding_branding.register_onboarding_pages()

        self.assertTrue(
            set(onboarding_branding.ONBOARDING_PAGE_KEYS).issubset(
                set(message_editor.PAGE_KEYS)
            )
        )
        self.assertTrue(
            set(onboarding_branding.ONBOARDING_PAGE_KEYS).issubset(
                set(page_context.SUPPORTED_YAA_PAGE_KEYS)
            )
        )

    def test_connection_placeholder_is_explained_without_exposing_value(self):
        with patch(
            "bot.utils.message_editor.get_message_data",
            return_value={"text": "Добавьте подключение: %ключ%"},
        ):
            help_text = build_yaa_help_text(
                "onboarding_happ_connection",
                {"%ключ%": "<code>private-subscription-url</code>"},
            )

        self.assertIn("<code>%ключ%</code>", help_text)
        self.assertIn("Сохраните динамические плейсхолдеры", help_text)
        self.assertNotIn("private-subscription-url", help_text)


class OnboardingConnectionContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_screen_is_remembered_for_admin_yaa(self):
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=123),
            message=object(),
        )
        rendered_message = object()
        context = {
            "key_id": 7,
            "platform": "android",
            "app": "happ",
            "distribution": "google_play",
        }
        raw_value = "https://example.invalid/subscription"

        with (
            patch(
                "bot.utils.onboarding_delivery._access_value",
                new=AsyncMock(return_value=raw_value),
            ),
            patch(
                "bot.services.subscription_readiness.wait_for_subscription_ready",
                new=AsyncMock(return_value=True),
            ) as wait_ready,
            patch(
                "bot.utils.message_editor.get_message_data",
                return_value={"text": "Ссылка: %ключ%"},
            ),
            patch("bot.utils.page_renderer.build_page_keyboard", return_value=None),
            patch(
                "bot.utils.text.safe_edit_or_send",
                new=AsyncMock(return_value=rendered_message),
            ),
            patch("bot.utils.onboarding_delivery.generate_qr_code", return_value=b"png"),
            patch("config.ADMIN_IDS", [123]),
            patch("bot.services.page_context.remember_page_context") as remember_mock,
        ):
            result = await send_onboarding_connection(
                callback,
                {"id": 7, "server_id": 3, "sub_id": "sub-id"},
                page_key="onboarding_happ_connection_android",
                fallback_text="Ссылка: %ключ%",
                context=context,
            )

        self.assertTrue(result)
        wait_ready.assert_awaited_once_with(raw_value, key_id=7, server_id=3)
        remember_mock.assert_called_once()
        kwargs = remember_mock.call_args.kwargs
        self.assertEqual(kwargs["page_key"], "onboarding_happ_connection_android")
        self.assertIs(kwargs["message"], rendered_message)
        self.assertEqual(kwargs["context"], context)
        self.assertEqual(
            kwargs["text_replacements"],
            {"%ключ%": "<code>https://example.invalid/subscription</code>"},
        )


if __name__ == "__main__":
    unittest.main()
