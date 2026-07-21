import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.services.subscription_readiness import (  # noqa: E402
    SubscriptionProbe,
    wait_for_subscription_ready,
)
from bot.utils.key_card_onboarding import send_subscription_key_card  # noqa: E402


async def no_sleep(_delay: float) -> None:
    return None


class SubscriptionReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_404_until_ready(self):
        results = iter(
            (
                SubscriptionProbe(status=404),
                SubscriptionProbe(status=404),
                SubscriptionProbe(status=200, content_length=364, has_metadata=True),
            )
        )
        calls = []

        async def probe(url: str, timeout: float) -> SubscriptionProbe:
            calls.append((url, timeout))
            return next(results)

        ready = await wait_for_subscription_ready(
            "https://entry.example/sub/secret-value",
            key_id=17,
            server_id=3,
            delays=(0, 0, 0),
            probe=probe,
            sleep=no_sleep,
        )

        self.assertTrue(ready)
        self.assertEqual(len(calls), 3)

    async def test_requires_body_and_subscription_metadata(self):
        results = iter(
            (
                SubscriptionProbe(status=200, content_length=364, has_metadata=False),
                SubscriptionProbe(status=200, content_length=0, has_metadata=True),
            )
        )

        async def probe(_url: str, _timeout: float) -> SubscriptionProbe:
            return next(results)

        ready = await wait_for_subscription_ready(
            "https://entry.example/sub/secret-value",
            delays=(0, 0),
            probe=probe,
            sleep=no_sleep,
        )

        self.assertFalse(ready)

    async def test_timeout_logs_do_not_expose_subscription_url(self):
        secret_url = "https://entry.example/sub/SENSITIVE_SUBSCRIPTION_ID"

        async def probe(_url: str, _timeout: float) -> SubscriptionProbe:
            return SubscriptionProbe(status=404)

        with self.assertLogs("bot.services.subscription_readiness", level="INFO") as captured:
            ready = await wait_for_subscription_ready(
                secret_url,
                key_id=9,
                server_id=4,
                delays=(0, 0),
                probe=probe,
                sleep=no_sleep,
            )

        self.assertFalse(ready)
        joined = "\n".join(captured.output)
        self.assertNotIn(secret_url, joined)
        self.assertNotIn("SENSITIVE_SUBSCRIPTION_ID", joined)

    async def test_key_card_shows_waiting_message_when_not_ready(self):
        secret_url = "https://entry.example/sub/SENSITIVE_SUBSCRIPTION_ID"

        with (
            patch(
                "bot.services.vpn_api.get_subscription_url_for_key",
                new=AsyncMock(return_value=secret_url),
            ) as get_url,
            patch(
                "bot.services.subscription_readiness.wait_for_subscription_ready",
                new=AsyncMock(return_value=False),
            ) as wait_ready,
            patch(
                "bot.utils.key_sender_core._send_error",
                new=AsyncMock(),
            ) as send_error,
        ):
            result = await send_subscription_key_card(
                object(),
                {"id": 27, "server_id": 5, "sub_id": "redacted"},
            )

        self.assertIsNone(result)
        get_url.assert_awaited_once()
        wait_ready.assert_awaited_once_with(secret_url, key_id=27, server_id=5)
        send_error.assert_awaited_once()
        self.assertIn("сервер всё ещё подготавливает", send_error.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
