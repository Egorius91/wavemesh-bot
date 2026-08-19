from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


class InternalApiProviderRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_catalog_uses_billing_mode_and_preserves_order(self) -> None:
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value=[
                {"provider": "YOOKASSA", "role": "DEFAULT"},
                {"provider": "PLATEGA", "role": "CHOICE"},
            ]
        )

        result = await client.list_payment_providers("one_time")

        self.assertEqual(
            result,
            [
                {"provider": "YOOKASSA", "role": "DEFAULT"},
                {"provider": "PLATEGA", "role": "CHOICE"},
            ],
        )
        client._request.assert_awaited_once_with(
            "GET",
            "catalog/payment-providers?billing_mode=ONE_TIME",
        )

    async def test_provider_catalog_rejects_unknown_or_duplicate_provider(self) -> None:
        for payload in (
            [{"provider": "UNKNOWN", "role": "CHOICE"}],
            [
                {"provider": "PLATEGA", "role": "DEFAULT"},
                {"provider": "PLATEGA", "role": "CHOICE"},
            ],
        ):
            with self.subTest(payload=payload):
                client = WaveMeshInternalApiClient()
                client._request = AsyncMock(return_value=payload)
                with self.assertRaises(InternalApiError) as raised:
                    await client.list_payment_providers("ONE_TIME")
                self.assertEqual(
                    raised.exception.code,
                    "INTERNAL_API_INVALID_RESPONSE",
                )

    async def test_provider_catalog_rejects_unknown_billing_mode_before_http(self) -> None:
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock()

        with self.assertRaises(InternalApiError) as raised:
            await client.list_payment_providers("UNKNOWN")

        self.assertEqual(raised.exception.code, "INTERNAL_API_INVALID_REQUEST")
        client._request.assert_not_awaited()

    async def test_create_order_omits_provider_for_default_routing(self) -> None:
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "order_id": "order-12345678",
                "checkout_url": "https://payments.example.invalid/default",
                "status": "pending",
            }
        )

        await client.create_order(
            user_id="user-12345678",
            tariff_id="tariff-12345678",
            billing_mode="ONE_TIME",
            idempotency_key="telegram-routing-default-1",
        )

        client._request.assert_awaited_once_with(
            "POST",
            "bot/orders",
            json_body={
                "user_id": "user-12345678",
                "tariff_id": "tariff-12345678",
                "billing_mode": "ONE_TIME",
                "return_channel": "TELEGRAM",
            },
            idempotency_key="telegram-routing-default-1",
        )

    async def test_create_order_sends_explicit_provider(self) -> None:
        for provider in ("YOOKASSA", "PLATEGA"):
            with self.subTest(provider=provider):
                client = WaveMeshInternalApiClient()
                client._request = AsyncMock(
                    return_value={
                        "order_id": "order-12345678",
                        "checkout_url": "https://payments.example.invalid/explicit",
                        "status": "pending",
                    }
                )

                await client.create_order(
                    user_id="user-12345678",
                    tariff_id="tariff-12345678",
                    billing_mode="ONE_TIME",
                    provider=provider.lower(),
                    access_id="access-12345678",
                    idempotency_key=f"telegram-routing-{provider.lower()}-1",
                )

                client._request.assert_awaited_once_with(
                    "POST",
                    "bot/orders",
                    json_body={
                        "user_id": "user-12345678",
                        "tariff_id": "tariff-12345678",
                        "billing_mode": "ONE_TIME",
                        "provider": provider,
                        "access_id": "access-12345678",
                        "return_channel": "TELEGRAM",
                    },
                    idempotency_key=f"telegram-routing-{provider.lower()}-1",
                )

    async def test_create_order_rejects_unknown_provider_before_http(self) -> None:
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock()

        with self.assertRaises(InternalApiError) as raised:
            await client.create_order(
                user_id="user-12345678",
                tariff_id="tariff-12345678",
                billing_mode="ONE_TIME",
                provider="UNKNOWN",
            )

        self.assertEqual(raised.exception.code, "INTERNAL_API_INVALID_REQUEST")
        client._request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
