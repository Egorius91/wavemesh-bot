"""Безопасный клиент WaveMesh Internal API."""

from __future__ import annotations

import asyncio
import logging
import os
import re
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

    async def create_order(
        self,
        *,
        user_id: str,
        tariff_id: str,
        billing_mode: str,
        access_id: str | None = None,
        return_url: str | None = None,
        return_channel: str | None = "TELEGRAM",
        idempotency_key: str | None = None,
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

        payload: dict[str, Any] = {
            "user_id": user_id,
            "tariff_id": tariff_id,
            "billing_mode": normalized_billing_mode,
        }
        if access_id:
            payload["access_id"] = access_id
        if return_url:
            payload["return_url"] = return_url
        if normalized_return_channel:
            payload["return_channel"] = normalized_return_channel

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
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"bot/accesses/{access_id}/replace",
            json_body={},
            idempotency_key=idempotency_key,
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("command_id"), str)
            or result.get("status") not in {"pending", "running"}
            or not isinstance(result.get("desired_version"), int)
            or result["desired_version"] < 2
        ):
            raise InternalApiError(
                "Unexpected access replacement response",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        return result

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
            required_strings = (
                "panel_email",
                "client_uuid",
                "sub_id",
                "protocol",
                "subscription_url",
            )
            if (
                any(not isinstance(result.get(key), str) or not result[key] for key in required_strings)
                or not isinstance(result.get("desired_version"), int)
                or result["desired_version"] < 1
                or not isinstance(result.get("primary_inbound_id"), int)
                or result["primary_inbound_id"] < 1
                or result["protocol"] != "vless"
                or not result["subscription_url"].startswith("https://")
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
