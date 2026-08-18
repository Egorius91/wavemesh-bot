"""Provider-neutral billing-agreement operations over WaveMesh Internal API."""

from __future__ import annotations

from typing import Any

from bot.services.internal_api import InternalApiError, internal_api_client

_ALLOWED_PROVIDERS = frozenset({"YOOKASSA", "PLATEGA"})
_ALLOWED_STATUSES = frozenset(
    {"pending", "active", "past_due", "cancelled", "expired"}
)
_ALLOWED_CANCELLATION_RESULTS = frozenset(
    {"REQUESTED", "CONFIRMED", "NOT_REQUIRED"}
)


def _validate_agreement(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise InternalApiError(
            "Unexpected billing agreement response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )

    agreement_id = item.get("agreement_id")
    provider = item.get("provider")
    status = item.get("status")
    if (
        not isinstance(agreement_id, str)
        or not agreement_id
        or provider not in _ALLOWED_PROVIDERS
        or status not in _ALLOWED_STATUSES
    ):
        raise InternalApiError(
            "Unexpected billing agreement response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    return item


async def list_provider_billing_agreements(
    telegram_id: int,
) -> list[dict[str, Any]]:
    result = await internal_api_client._request(  # noqa: SLF001 - shared authenticated transport
        "GET",
        f"bot/users/{telegram_id}/billing-agreements",
    )
    if not isinstance(result, list):
        raise InternalApiError(
            "Unexpected billing agreement list response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    return [_validate_agreement(item) for item in result]


async def cancel_provider_billing_agreement(
    *,
    telegram_id: int,
    agreement_id: str,
) -> dict[str, Any]:
    if not isinstance(agreement_id, str) or not agreement_id:
        raise InternalApiError(
            "Billing agreement id is invalid",
            code="INTERNAL_API_INVALID_REQUEST",
        )

    idempotency_key = (
        f"telegram-provider-billing-cancel-{telegram_id}-{agreement_id}"
    )
    result = await internal_api_client._request(  # noqa: SLF001 - shared authenticated transport
        "POST",
        (
            f"bot/users/{telegram_id}/billing-agreements/"
            f"{agreement_id}/cancel"
        ),
        json_body={},
        idempotency_key=idempotency_key,
    )
    if not isinstance(result, dict):
        raise InternalApiError(
            "Unexpected billing cancellation response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )

    cancellation = result.get("cancellation")
    if cancellation not in _ALLOWED_CANCELLATION_RESULTS:
        raise InternalApiError(
            "Unexpected billing cancellation response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    if cancellation == "NOT_REQUIRED" and result.get("agreementStatus") != "EXPIRED":
        raise InternalApiError(
            "Unexpected billing cancellation terminal response",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    return result
