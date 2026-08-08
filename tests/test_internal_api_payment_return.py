import unittest
from unittest.mock import AsyncMock

from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


class InternalApiPaymentReturnTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_order_requests_telegram_return_channel_by_default(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "order_id": "order-12345678",
                "checkout_url": "https://payments.example.invalid/checkout",
                "status": "pending",
            }
        )

        result = await client.create_order(
            user_id="user-12345678",
            tariff_id="tariff-12345678",
            billing_mode="ONE_TIME",
            access_id="access-12345678",
            idempotency_key="telegram-checkout-1",
        )

        self.assertEqual(result["status"], "pending")
        client._request.assert_awaited_once_with(
            "POST",
            "bot/orders",
            json_body={
                "user_id": "user-12345678",
                "tariff_id": "tariff-12345678",
                "billing_mode": "ONE_TIME",
                "access_id": "access-12345678",
                "return_channel": "TELEGRAM",
            },
            idempotency_key="telegram-checkout-1",
        )

    async def test_create_order_keeps_explicit_legacy_return_url_opt_in(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "order_id": "order-12345678",
                "checkout_url": "https://payments.example.invalid/checkout",
                "status": "pending",
            }
        )

        await client.create_order(
            user_id="user-12345678",
            tariff_id="tariff-12345678",
            billing_mode="ONE_TIME",
            return_url="https://trusted.example.invalid/payment/return",
            return_channel=None,
            idempotency_key="legacy-checkout-1",
        )

        client._request.assert_awaited_once_with(
            "POST",
            "bot/orders",
            json_body={
                "user_id": "user-12345678",
                "tariff_id": "tariff-12345678",
                "billing_mode": "ONE_TIME",
                "return_url": "https://trusted.example.invalid/payment/return",
            },
            idempotency_key="legacy-checkout-1",
        )

    async def test_create_order_rejects_conflicting_return_destinations(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock()

        with self.assertRaises(InternalApiError) as raised:
            await client.create_order(
                user_id="user-12345678",
                tariff_id="tariff-12345678",
                billing_mode="ONE_TIME",
                return_url="https://trusted.example.invalid/payment/return",
            )

        self.assertEqual(raised.exception.code, "INTERNAL_API_INVALID_REQUEST")
        client._request.assert_not_awaited()

    async def test_create_order_rejects_unknown_billing_mode(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock()

        with self.assertRaises(InternalApiError) as raised:
            await client.create_order(
                user_id="user-12345678",
                tariff_id="tariff-12345678",
                billing_mode="UNKNOWN",
            )

        self.assertEqual(raised.exception.code, "INTERNAL_API_INVALID_REQUEST")
        client._request.assert_not_awaited()

    async def test_resolve_payment_return_posts_token_in_body(self):
        client = WaveMeshInternalApiClient()
        token = "pay_" + "A" * 32
        client._request = AsyncMock(
            return_value={
                "schema_version": 1,
                "channel": "TELEGRAM",
                "status": "ready",
                "order_id": "order-12345678",
                "access_id": "access-12345678",
                "retryable": False,
                "token_expires_at": "2026-08-04T11:30:00.000Z",
            }
        )

        result = await client.resolve_payment_return(token)

        self.assertEqual(result["access_id"], "access-12345678")
        client._request.assert_awaited_once_with(
            "POST",
            "bot/payment-returns/resolve",
            json_body={"token": token},
        )

    async def test_resolve_payment_return_accepts_all_verified_non_ready_states(self):
        token = "pay_" + "B" * 32
        expected_retryable = {
            "pending": True,
            "cancelled": False,
            "access_creating": True,
            "support_error": False,
        }

        for status, retryable in expected_retryable.items():
            with self.subTest(status=status):
                client = WaveMeshInternalApiClient()
                client._request = AsyncMock(
                    return_value={
                        "schema_version": 1,
                        "channel": "TELEGRAM",
                        "status": status,
                        "order_id": "order-12345678",
                        "access_id": None,
                        "retryable": retryable,
                        "token_expires_at": "2026-08-04T11:30:00.000Z",
                    }
                )

                result = await client.resolve_payment_return(token)
                self.assertEqual(result["status"], status)

    async def test_resolve_payment_return_fails_closed_on_invalid_projection(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "schema_version": 1,
                "channel": "TELEGRAM",
                "status": "pending",
                "order_id": "order-12345678",
                "access_id": "access-must-not-leak",
                "retryable": True,
                "token_expires_at": "2026-08-04T11:30:00.000Z",
            }
        )

        with self.assertRaises(InternalApiError) as raised:
            await client.resolve_payment_return("pay_" + "C" * 32)

        self.assertEqual(raised.exception.code, "INTERNAL_API_INVALID_RESPONSE")

    async def test_resolve_payment_return_rejects_malformed_token_before_request(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock()

        with self.assertRaises(InternalApiError) as raised:
            await client.resolve_payment_return("pay_too-short")

        self.assertEqual(raised.exception.code, "PAYMENT_RETURN_TOKEN_INVALID")
        client._request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
