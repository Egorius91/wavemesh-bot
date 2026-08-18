import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bot.services.internal_api import InternalApiError, internal_api_client
from bot.services.provider_billing_api import (
    cancel_provider_billing_agreement,
    list_provider_billing_agreements,
)


def test_provider_billing_list_uses_tenant_authenticated_internal_transport():
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

    assert result == payload
    request.assert_awaited_once_with(
        "GET",
        "bot/users/123456789/billing-agreements",
    )


def test_provider_billing_cancel_reuses_deterministic_idempotency_key():
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

    assert first["cancellation"] == "REQUESTED"
    assert second["cancellation"] == "REQUESTED"
    assert request.await_count == 2
    for call in request.await_args_list:
        assert call.args == (
            "POST",
            "bot/users/123456789/billing-agreements/agreement-1/cancel",
        )
        assert call.kwargs["json_body"] == {}
        assert (
            call.kwargs["idempotency_key"]
            == "telegram-provider-billing-cancel-123456789-agreement-1"
        )


def test_provider_billing_client_rejects_unexpected_provider_response():
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
        try:
            asyncio.run(list_provider_billing_agreements(123456789))
        except InternalApiError as error:
            assert error.code == "INTERNAL_API_INVALID_RESPONSE"
        else:
            raise AssertionError("invalid provider response was accepted")


def test_telegram_provider_billing_flow_is_saas_only_and_has_confirmation_boundary():
    payments_init = Path("bot/handlers/user/payments/__init__.py").read_text()
    handler = Path(
        "bot/handlers/user/payments/provider_billing.py"
    ).read_text()
    client = Path("bot/services/provider_billing_api.py").read_text()

    saas_block = payments_init.split("else:", 1)[0]
    legacy_block = payments_init.split("else:", 1)[1]
    assert "provider_billing_router" in saas_block
    assert "provider_billing_router" not in legacy_block
    assert 'Command("billing")' in handler
    assert "saas_billing_confirm" in handler
    assert "saas_billing_cancel" in handler
    assert "Подтвердить отключение" in handler
    assert "уже оплаченный VPN-доступ" in handler
    assert "telegram-provider-billing-cancel-" in client
    assert "cancelBillingAgreement" not in handler
    assert "PLATEGA" not in handler
