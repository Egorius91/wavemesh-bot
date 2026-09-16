"""Безопасный клиент WaveMesh Internal API."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any
from uuid import uuid4

import aiohttp

logger = logging.getLogger(__name__)

_PAYMENT_RETURN_TOKEN_PATTERN = re.compile(r"^pay_[A-Za-z0-9_-]{32}$")
_PAYMENT_RETURN_STATUSES = frozenset(
    {
        "pending",
        "cancelled",
        "access_creating",
        "ready",
        "support_error",
    }
)
_PAYMENT_PROVIDERS = frozenset({"YOOKASSA", "PLATEGA"})
_PAYMENT_PROVIDER_ROLES = frozenset({"DEFAULT", "CHOICE"})
_TRIAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TRIAL_STATUSES = frozenset({"PENDING", "MATERIALIZING", "READY", "FAILED", "EXPIRED", "DISABLED"})


def validate_trial_user_id(value: Any) -> str:
    if not isinstance(value, str) or not _TRIAL_ID.fullmatch(value):
        raise InternalApiError("Invalid trial user identity", code="INTERNAL_API_INVALID_RESPONSE")
    return value


def _validated_trial(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise InternalApiError("Invalid trial response", code="INTERNAL_API_INVALID_RESPONSE")
    for key in ("activation_id", "access_id", "command_id"):
        validate_trial_user_id(result.get(key))
    if result.get("subscription_id") is not None:
        validate_trial_user_id(result["subscription_id"])
    if not isinstance(result.get("status"), str) or result["status"] not in _TRIAL_STATUSES:
        raise InternalApiError("Invalid trial status", code="INTERNAL_API_INVALID_RESPONSE")
    try:
        expires = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            raise ValueError("Missing timezone")
    except (KeyError, AttributeError, TypeError, ValueError) as error:
        raise InternalApiError("Invalid trial expiry", code="INTERNAL_API_INVALID_RESPONSE") from error
    if result["status"] == "READY" and not result.get("subscription_id"):
        raise InternalApiError("Unbound ready trial", code="INTERNAL_API_INVALID_RESPONSE")
    return {key: result[key] for key in ("activation_id", "access_id", "command_id", "status", "expires_at")} | {
        "subscription_id": result.get("subscription_id"),
    }


class InternalApiError(RuntimeError):
    """Ошибка вызова WaveMesh Internal API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


class WaveMeshInternalApiClient:
    def __init__(self) -> None:
        self.enabled = os.getenv(
            "WAVEMESH_INTERNAL_API_ENABLED",
            "false",
        ).strip().lower() == "true"

        self.base_url = os.getenv(
            "WAVEMESH_INTERNAL_API_BASE_URL",
            "",
        ).strip().rstrip("/")

        self.tenant_id = os.getenv(
            "WAVEMESH_INTERNAL_API_TENANT_ID",
            "",
        ).strip()

        self.token = os.getenv(
            "WAVEMESH_INTERNAL_API_TOKEN",
            "",
        ).strip()

        timeout_raw = os.getenv(
            "WAVEMESH_INTERNAL_API_TIMEOUT_SECONDS",
            "10",
        ).strip()

        try:
            self.timeout_seconds = max(1.0, float(timeout_raw))
        except ValueError:
            self.timeout_seconds = 10.0

        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.base_url
            and self.tenant_id
            and self.token
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session

        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
                self._session = aiohttp.ClientSession(timeout=timeout)

        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not self.configured:
            raise InternalApiError(
                "WaveMesh Internal API is disabled or not configured",
                code="INTERNAL_API_NOT_CONFIGURED",
            )

        headers = {
            "Authorization": f"Bearer {self.token}",
            "x-wavevpn-tenant-id": self.tenant_id,
            "Accept": "application/json",
        }

        if json_body is not None:
            headers["Content-Type"] = "application/json"

        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            async with session.request(
                method,
                url,
                headers=headers,
                json=json_body,
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except Exception:
                    payload = {
                        "message": (await response.text())[:500],
                    }

                if response.status >= 400:
                    if isinstance(payload, dict):
                        code = payload.get("code")
                        message = payload.get("message") or f"HTTP {response.status}"
                        retryable = bool(payload.get("retryable"))
                    else:
                        code = None
                        message = f"HTTP {response.status}"
                        retryable = response.status >= 500

                    raise InternalApiError(
                        str(message),
                        status=response.status,
                        code=str(code) if code else None,
                        retryable=retryable,
                    )

                return payload

        except asyncio.TimeoutError as error:
            raise InternalApiError(
                "WaveMesh Internal API request timed out",
                code="INTERNAL_API_TIMEOUT",
                retryable=True,
            ) from error

        except aiohttp.ClientError as error:
            raise InternalApiError(
                f"WaveMesh Internal API network error: {error}",
                code="INTERNAL_API_NETWORK_ERROR",
                retryable=True,
            ) from error

    async def list_tariffs(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "catalog/tariffs")
        if not isinstance(payload, list):
            raise InternalApiError(
                "Unexpected tariff catalog response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        return payload

    async def list_payment_providers(
        self,
        billing_mode: str,
    ) -> list[dict[str, str]]:
        normalized_billing_mode = billing_mode.strip().upper()
        if normalized_billing_mode not in {"ONE_TIME", "RECURRING"}:
            raise InternalApiError(
                "Unsupported payment billing mode",
                code="INTERNAL_API_INVALID_REQUEST",
            )

        payload = await self._request(
            "GET",
            f"catalog/payment-providers?billing_mode={normalized_billing_mode}",
        )
        if not isinstance(payload, list):
            raise InternalApiError(
                "Unexpected payment provider catalog response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        providers: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise InternalApiError(
                    "Unexpected payment provider catalog response",
                    code="INTERNAL_API_INVALID_RESPONSE",
                )
            provider = item.get("provider")
            role = item.get("role")
            if (
                provider not in _PAYMENT_PROVIDERS
                or role not in _PAYMENT_PROVIDER_ROLES
                or provider in seen
            ):
                raise InternalApiError(
                    "Unexpected payment provider catalog response",
                    code="INTERNAL_API_INVALID_RESPONSE",
                )
            seen.add(provider)
            providers.append({"provider": str(provider), "role": str(role)})

        return providers

    async def upsert_telegram_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        display_name: str | None,
        is_bot_blocked: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "telegram_id": str(telegram_id),
            "username": username,
            "display_name": display_name,
            "is_bot_blocked": is_bot_blocked,
        }

        result = await self._request(
            "POST",
            "bot/users/upsert",
            json_body=payload,
            idempotency_key=(
                idempotency_key
                or f"telegram-user-{telegram_id}-{uuid4()}"
            ),
        )

        if not isinstance(result, dict):
            raise InternalApiError(
                "Unexpected user upsert response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        return result

    async def get_telegram_dashboard(
        self,
        telegram_id: int,
    ) -> dict[str, Any]:
        result = await self._request(
            "GET",
            f"bot/users/{telegram_id}/dashboard",
        )

        if not isinstance(result, dict):
            raise InternalApiError(
                "Unexpected dashboard response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        return result

    async def activate_trial(self, user_id: str) -> dict[str, Any]:
        # SaaS user/offer uniqueness is the durable identity across both channels.
        user_id = validate_trial_user_id(user_id)
        return _validated_trial(await self._request(
            "POST", "bot/trials", json_body={"user_id": user_id, "offer_code": "TRIAL3"},
        ))

    async def get_trial(self, user_id: str) -> dict[str, Any]:
        user_id = validate_trial_user_id(user_id)
        return _validated_trial(await self._request("GET", f"bot/users/{user_id}/trials/TRIAL3"))

    async def create_order(
        self,
        *,
        user_id: str,
        tariff_id: str,
        billing_mode: str,
        provider: str | None = None,
        access_id: str | None = None,
        return_url: str | None = None,
        return_channel: str | None = "TELEGRAM",
        idempotency_key: str | None = None,
        recurring_consent: dict[str, Any] | None = None,
        confirmed_terms: dict[str, Any] | None = None,
        expected_previous_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Создаёт SaaS order и запрашивает безопасный возврат в Telegram."""
        if return_url and return_channel:
            raise InternalApiError(
                "return_url and return_channel are mutually exclusive",
                code="INTERNAL_API_INVALID_REQUEST",
            )

        normalized_return_channel = (
            return_channel.strip().upper()
            if isinstance(return_channel, str)
            else None
        )
        if normalized_return_channel not in {None, "TELEGRAM"}:
            raise InternalApiError(
                "Unsupported payment return channel",
                code="INTERNAL_API_INVALID_REQUEST",
            )

        normalized_billing_mode = billing_mode.strip().upper()
        if normalized_billing_mode not in {"ONE_TIME", "RECURRING"}:
            raise InternalApiError(
                "Unsupported payment billing mode",
                code="INTERNAL_API_INVALID_REQUEST",
            )

        normalized_provider = (
            provider.strip().upper()
            if isinstance(provider, str)
            else None
        )
        if normalized_provider not in {None, "YOOKASSA", "PLATEGA"}:
            raise InternalApiError(
                "Unsupported payment provider",
                code="INTERNAL_API_INVALID_REQUEST",
            )

        payload: dict[str, Any] = {
            "user_id": user_id,
            "tariff_id": tariff_id,
            "billing_mode": normalized_billing_mode,
        }
        if normalized_provider:
            payload["provider"] = normalized_provider
        if access_id:
            payload["access_id"] = access_id
        if return_url:
            payload["return_url"] = return_url
        if normalized_return_channel:
            payload["return_channel"] = normalized_return_channel
        if recurring_consent is not None or confirmed_terms is not None or expected_previous_order_id is not None:
            from bot.services.checkout_contract import consent, identity, request_key
            try:
                if recurring_consent is not None and (normalized_billing_mode != "RECURRING" or normalized_provider != "YOOKASSA"):
                    raise ValueError("Invalid saved checkout provider")
                request_key(idempotency_key)
                if recurring_consent is not None:
                    payload["recurring_consent"] = consent(recurring_consent)
                if confirmed_terms is not None:
                    if normalized_billing_mode != "ONE_TIME":
                        raise ValueError("Invalid one-time confirmation mode")
                    payload["confirmed_terms"] = consent(confirmed_terms)
                if expected_previous_order_id is not None:
                    payload["expected_previous_order_id"] = identity(expected_previous_order_id)
            except ValueError as error:
                raise InternalApiError("Invalid saved checkout intent", code="INTERNAL_API_INVALID_REQUEST") from error

        result = await self._request(
            "POST",
            "bot/orders",
            json_body=payload,
            idempotency_key=(idempotency_key or f"telegram-order-{uuid4()}"),
        )

        if not isinstance(result, dict):
            raise InternalApiError(
                "Unexpected checkout response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        order_id = result.get("order_id")
        checkout_url = result.get("checkout_url")
        status = result.get("status")
        if (
            not isinstance(order_id, str)
            or not order_id
            or not isinstance(checkout_url, str)
            or not checkout_url.startswith("https://")
            or not isinstance(status, str)
        ):
            raise InternalApiError(
                "Unexpected checkout response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        return result

    async def get_current_checkout(self, user_id: str) -> dict[str, Any] | None:
        return await self._checkout_read(user_id)

    async def get_checkout(self, user_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._checkout_read(user_id, idempotency_key)

    async def get_checkout_rejection(self, user_id: str, idempotency_key: str, *, billing_mode="RECURRING") -> bool:
        from bot.services.checkout_contract import identity, rejection_proof, request_key

        try:
            identity(user_id)
            request_key(idempotency_key)
        except ValueError as error:
            raise InternalApiError("Invalid checkout identity", code="INTERNAL_API_INVALID_REQUEST") from error
        try:
            result = await self._request("GET", f"bot/orders/checkout/rejection?user_id={user_id}", idempotency_key=idempotency_key)
        except InternalApiError as error:
            if error.status == 404 and error.code == "CHECKOUT_NOT_FOUND":
                return False
            raise
        try:
            return rejection_proof(result, billing_mode)
        except ValueError as error:
            raise InternalApiError("Invalid checkout rejection", code="INTERNAL_API_INVALID_RESPONSE") from error

    async def reject_unadmitted_checkout(self, *, original_payload: dict[str, Any], idempotency_key: str) -> bool:
        """Fence the exact original Bot checkout intent; the caller must GET proof afterward."""
        from bot.services.checkout_contract import dispatch_payload, rejection_proof, request_key

        try:
            request_key(idempotency_key)
            payload = dispatch_payload(original_payload)
        except ValueError as error:
            raise InternalApiError("Invalid checkout intent", code="INTERNAL_API_INVALID_REQUEST") from error
        try:
            result = await self._request(
                "POST", "bot/orders/checkout/reject-unadmitted",
                json_body=payload | {"return_channel": "TELEGRAM"},
                idempotency_key=idempotency_key,
            )
            return rejection_proof(result, payload["billing_mode"])
        except ValueError as error:
            raise InternalApiError("Invalid checkout rejection", code="INTERNAL_API_INVALID_RESPONSE") from error

    async def _checkout_read(self, user_id, idempotency_key=None):
        from bot.services.checkout_contract import identity, request_key, snapshot
        try:
            identity(user_id)
            if idempotency_key is not None:
                request_key(idempotency_key)
        except ValueError as error:
            raise InternalApiError("Invalid checkout identity", code="INTERNAL_API_INVALID_REQUEST") from error
        path = "current" if idempotency_key is None else "status"
        result = await self._request("GET", f"bot/orders/checkout/{path}?user_id={user_id}", idempotency_key=idempotency_key)
        try:
            return snapshot(result, current=idempotency_key is None)
        except (ValueError, TypeError) as error:
            raise InternalApiError("Invalid checkout snapshot", code="INTERNAL_API_INVALID_RESPONSE") from error

    async def resolve_payment_return(
        self,
        token: str,
    ) -> dict[str, Any]:
        """Разрешает opaque Telegram return token без передачи его в URL."""
        if not isinstance(token, str) or not _PAYMENT_RETURN_TOKEN_PATTERN.fullmatch(token):
            raise InternalApiError(
                "Invalid payment return token",
                code="PAYMENT_RETURN_TOKEN_INVALID",
            )

        result = await self._request(
            "POST",
            "bot/payment-returns/resolve",
            json_body={"token": token},
        )

        if not isinstance(result, dict):
            raise InternalApiError(
                "Unexpected payment return response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        status = result.get("status")
        access_id = result.get("access_id")
        retryable = result.get("retryable")
        expected_retryable = status in {"pending", "access_creating"}
        if (
            result.get("schema_version") != 1
            or result.get("channel") != "TELEGRAM"
            or status not in _PAYMENT_RETURN_STATUSES
            or not isinstance(result.get("order_id"), str)
            or not result["order_id"]
            or not isinstance(retryable, bool)
            or retryable is not expected_retryable
            or not isinstance(result.get("token_expires_at"), str)
            or not result["token_expires_at"]
            or (
                status == "ready"
                and (not isinstance(access_id, str) or not access_id)
            )
            or (status != "ready" and access_id is not None)
        ):
            raise InternalApiError(
                "Unexpected payment return response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )

        return result

    async def link_access_projection(
        self,
        *,
        access_id: str,
        telegram_id: int,
        legacy_key_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"bot/accesses/{access_id}/legacy-link",
            json_body={
                "telegram_id": str(telegram_id),
                "legacy_key_id": str(legacy_key_id),
            },
            idempotency_key=idempotency_key,
        )
        if (
            not isinstance(result, dict)
            or result.get("access_id") != access_id
            or str(result.get("legacy_key_id")) != str(legacy_key_id)
        ):
            raise InternalApiError(
                "Unexpected access projection link response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        return result

    async def replace_access(
        self,
        *,
        access_id: str,
        idempotency_key: str,
        expected_version: int,
    ) -> dict[str, Any]:
        from bot.services.replacement_contract import reference, request_values
        try:
            request_values(access_id, idempotency_key, expected_version)
        except (ValueError, TypeError) as error:
            raise InternalApiError("Invalid replacement request", code="INTERNAL_API_INVALID_REQUEST") from error
        result = await self._request(
            "POST",
            f"bot/accesses/{access_id}/replace",
            json_body={"expected_version": expected_version},
            idempotency_key=idempotency_key,
        )
        try:
            return reference(result, expected_version)
        except (ValueError, TypeError) as error:
            raise InternalApiError("Invalid replacement response", code="INTERNAL_API_INVALID_RESPONSE") from error

    async def get_access_replacement(self, access_id: str, idempotency_key: str, expected_version: int) -> dict[str, Any]:
        from bot.services.replacement_contract import readback, request_values
        try:
            request_values(access_id, idempotency_key, expected_version)
        except (ValueError, TypeError) as error:
            raise InternalApiError("Invalid replacement request", code="INTERNAL_API_INVALID_REQUEST") from error
        result = await self._request("GET", f"bot/accesses/{access_id}/replacement?expected_version={expected_version}",
                                     idempotency_key=idempotency_key)
        try:
            return readback(result, access_id, expected_version)
        except (ValueError, TypeError) as error:
            raise InternalApiError("Invalid replacement readback", code="INTERNAL_API_INVALID_RESPONSE") from error

    async def create_access(
        self,
        *,
        telegram_id: int,
        legacy_key_id: int,
        duration_days: int,
        traffic_limit_bytes: int,
        device_limit: int,
        requested_node_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "telegram_id": str(telegram_id),
            "legacy_key_id": str(legacy_key_id),
            "duration_days": duration_days,
            "traffic_limit_bytes": str(max(0, traffic_limit_bytes)),
            "device_limit": device_limit,
        }
        if requested_node_id:
            payload["requested_node_id"] = requested_node_id

        result = await self._request(
            "POST",
            "bot/accesses",
            json_body=payload,
            idempotency_key=(
                idempotency_key
                or f"telegram-admin-access-{legacy_key_id}-{uuid4()}"
            ),
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("access_id"), str)
            or not isinstance(result.get("command_id"), str)
            or result.get("status") != "materializing"
        ):
            raise InternalApiError(
                "Unexpected access provisioning response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        return result

    async def get_access_provisioning(self, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", idempotency_key):
            raise InternalApiError("Invalid provisioning request identity", code="INTERNAL_API_INVALID_RESPONSE")
        result = await self._request("GET", "bot/access-provisioning", idempotency_key=idempotency_key)
        valid = (isinstance(result, dict) and result.get("submission") in ("OBSERVED", "UNCONFIRMED")
                 and result.get("can_retry_create") is False and isinstance(result.get("status"), str))
        if valid and result["submission"] == "OBSERVED":
            valid = all(isinstance(result.get(k), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result[k]) for k in
                        ("access_id", "command_id", "assigned_entry_node_id"))
            valid = valid and isinstance(result.get("legacy_key_id"), str) and result["legacy_key_id"].isdigit()
            try:
                valid = valid and datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00")).tzinfo is not None
            except (KeyError, AttributeError, TypeError, ValueError):
                valid = False
        if not valid:
            raise InternalApiError("Invalid provisioning readback", code="INTERNAL_API_INVALID_RESPONSE")
        return {k: result.get(k) for k in ("submission", "status", "access_id", "command_id",
                "assigned_entry_node_id", "legacy_key_id", "expires_at", "can_retry_create")}

    async def get_provisioning_entries(self) -> dict[str, Any]:
        result = await self._request("GET", "bot/provisioning-entries")
        if (not isinstance(result, dict) or result.get("tenant_id") != self.tenant_id
                or not isinstance(result.get("service_client_id"), str)
                or not _TRIAL_ID.fullmatch(result["service_client_id"])
                or not isinstance(result.get("entries"), list)):
            raise InternalApiError("Invalid Entry catalog", code="INTERNAL_API_INVALID_RESPONSE")
        entries, seen = [], set()
        for item in result["entries"]:
            if (not isinstance(item, dict) or not isinstance(item.get("node_id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", item["node_id"])
                    or item["node_id"] in seen or any(not isinstance(item.get(k), str) for k in ("name","external_id"))):
                raise InternalApiError("Invalid Entry catalog", code="INTERNAL_API_INVALID_RESPONSE")
            seen.add(item["node_id"])
            entries.append({k: item[k] for k in ("node_id","name","external_id")})
        return {"tenant_id":result["tenant_id"], "service_client_id":result["service_client_id"], "entries":entries}

    async def get_access_material(self, access_id: str) -> dict[str, Any]:
        result = await self._request(
            "GET",
            f"bot/accesses/{access_id}/material",
        )
        if (
            not isinstance(result, dict)
            or result.get("access_id") != access_id
            or not isinstance(result.get("ready"), bool)
            or not isinstance(result.get("status"), str)
        ):
            raise InternalApiError(
                "Unexpected access material response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        if result["ready"]:
            from urllib.parse import urlsplit
            try:
                raw_url = result["subscription_url"]
                if not isinstance(raw_url, str):
                    raise ValueError()
                url = urlsplit(raw_url)
                valid_url = (isinstance(raw_url, str) and url.scheme == "https" and bool(url.hostname)
                             and not url.username and not url.password and not url.fragment
                             and not any(c.isspace() or ord(c) < 32 for c in raw_url))
            except (KeyError, TypeError, ValueError):
                valid_url = False
            required_strings = (
                "node_id",
                "panel_email",
                "client_uuid",
                "sub_id",
                "protocol",
                "subscription_url",
            )
            if (
                any(not isinstance(result.get(key), str) or not result[key] for key in required_strings)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result["node_id"])
                or type(result.get("desired_version")) is not int
                or result["desired_version"] < 1
                or type(result.get("primary_inbound_id")) is not int
                or result["primary_inbound_id"] < 1
                or result["protocol"] != "vless"
                or not valid_url
            ):
                raise InternalApiError(
                    "Unexpected ready access material response",
                    code="INTERNAL_API_INVALID_RESPONSE",
                )
        return result

    async def sync_access_shadow(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            "bot/accesses/shadow-sync",
            json_body=payload,
            idempotency_key=idempotency_key,
        )
        if not isinstance(result, dict) or not result.get("access_id"):
            raise InternalApiError(
                "Unexpected access shadow response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        return result


internal_api_client = WaveMeshInternalApiClient()


async def startup_probe() -> bool:
    """Проверяет доступность API без остановки запуска бота при ошибке."""
    if not internal_api_client.enabled:
        logger.info("WaveMesh Internal API integration is disabled")
        return False

    if not internal_api_client.configured:
        logger.error(
            "WaveMesh Internal API is enabled but configuration is incomplete"
        )
        return False

    try:
        tariffs = await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.error(
            "WaveMesh Internal API startup probe failed: "
            "code=%s status=%s retryable=%s message=%s",
            error.code,
            error.status,
            error.retryable,
            error,
        )
        return False

    logger.info(
        "WaveMesh Internal API startup probe succeeded: tariffs=%s",
        len(tariffs),
    )
    return True


_background_tasks: set[asyncio.Task[Any]] = set()


def schedule_telegram_user_upsert(
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    is_bot_blocked: bool = False,
) -> None:
    """
    Запускает shadow-upsert без задержки пользовательского обработчика.

    Ошибка SaaS только записывается в журнал и не влияет на ответ Telegram-бота.
    """
    if not internal_api_client.configured:
        return

    display_name = " ".join(
        part.strip()
        for part in (first_name, last_name)
        if isinstance(part, str) and part.strip()
    ) or None

    async def runner() -> None:
        try:
            result = await internal_api_client.upsert_telegram_user(
                telegram_id=telegram_id,
                username=username,
                display_name=display_name,
                is_bot_blocked=is_bot_blocked,
                idempotency_key=f"telegram-start-{telegram_id}-{uuid4()}",
            )
        except InternalApiError as error:
            logger.warning(
                "WaveMesh Internal API shadow user upsert failed: "
                "telegram_id=%s code=%s status=%s retryable=%s",
                telegram_id,
                error.code,
                error.status,
                error.retryable,
            )
            return
        except Exception:
            logger.exception(
                "Unexpected WaveMesh Internal API shadow user upsert error: "
                "telegram_id=%s",
                telegram_id,
            )
            return

        logger.info(
            "WaveMesh Internal API shadow user upsert succeeded: "
            "telegram_id=%s user_id=%s",
            telegram_id,
            result.get("user_id"),
        )

    task = asyncio.create_task(
        runner(),
        name=f"internal-api-user-upsert-{telegram_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
