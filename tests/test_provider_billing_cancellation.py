import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from bot.services.internal_api import InternalApiError, internal_api_client
from bot.services.provider_billing_api import (
    cancel_provider_billing_agreement,
    list_provider_billing_agreements,
)


class ProviderBillingCancellationTests(unittest.TestCase):
    def test_provider_billing_list_uses_tenant_authenticated_internal_transport(self):
        payload = [
            {
                "agreement_id": "agreement-1",
                "provider": "PLATEGA",
                "status": "active",
                "amount_rub": 1999,
                "currency": "RUB",
                "interval": {"unit": "year", "count": 1},
                "next_charge_at": None,
                "cancellation_requested_at": None,
                "cancelled_at": None,
            }
        ]
        request = AsyncMock(return_value=payload)
        with patch.object(internal_api_client, "_request", request):
            result = asyncio.run(list_provider_billing_agreements(123456789))

        self.assertEqual(result, payload)
        request.assert_awaited_once_with(
            "GET",
            "bot/users/123456789/billing-agreements",
        )

    def test_provider_billing_cancel_reuses_deterministic_idempotency_key(self):
        request = AsyncMock(
            return_value={
                "agreementId": "agreement-1",
                "cancellation": "REQUESTED",
            }
        )
        with patch.object(internal_api_client, "_request", request):
            first = asyncio.run(
                cancel_provider_billing_agreement(
                    telegram_id=123456789,
                    agreement_id="agreement-1",
                )
            )
            second = asyncio.run(
                cancel_provider_billing_agreement(
                    telegram_id=123456789,
                    agreement_id="agreement-1",
                )
            )

        self.assertEqual(first["cancellation"], "REQUESTED")
        self.assertEqual(second["cancellation"], "REQUESTED")
        self.assertEqual(request.await_count, 2)
        for call in request.await_args_list:
            self.assertEqual(
                call.args,
                (
                    "POST",
                    "bot/users/123456789/billing-agreements/agreement-1/cancel",
                ),
            )
            self.assertEqual(call.kwargs["json_body"], {})
            self.assertEqual(
                call.kwargs["idempotency_key"],
                "telegram-provider-billing-cancel-123456789-agreement-1",
            )

    def test_provider_billing_client_rejects_unexpected_provider_response(self):
        request = AsyncMock(
            return_value=[
                {
                    "agreement_id": "agreement-1",
                    "provider": "UNKNOWN",
                    "status": "active",
                }
            ]
        )
        with patch.object(internal_api_client, "_request", request):
            with self.assertRaises(InternalApiError) as captured:
                asyncio.run(list_provider_billing_agreements(123456789))

        self.assertEqual(captured.exception.code, "INTERNAL_API_INVALID_RESPONSE")

    def test_telegram_provider_billing_flow_is_saas_only_and_has_confirmation_boundary(self):
        payments_init = Path("bot/handlers/user/payments/__init__.py").read_text()
        handler = Path(
            "bot/handlers/user/payments/provider_billing.py"
        ).read_text()
        client = Path("bot/services/provider_billing_api.py").read_text()

        saas_block = payments_init.split("else:", 1)[0]
        legacy_block = payments_init.split("else:", 1)[1]
        self.assertIn("provider_billing_router", saas_block)
        self.assertNotIn("provider_billing_router", legacy_block)
        self.assertIn('Command("billing")', handler)
        self.assertIn("saas_billing_confirm", handler)
        self.assertIn("saas_billing_cancel", handler)
        self.assertIn("Подтвердить отключение", handler)
        self.assertIn("уже оплаченный VPN-доступ", handler)
        self.assertIn("telegram-provider-billing-cancel-", client)
        self.assertNotIn("cancelBillingAgreement", handler)
        self.assertNotIn("PLATEGA", handler)


if __name__ == "__main__":
    unittest.main()
