"""Wait for a public 3X-UI subscription endpoint without exposing secrets."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Sequence

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_READINESS_DELAYS: tuple[float, ...] = (0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 8.0)
DEFAULT_REQUEST_TIMEOUT = 5.0
MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SubscriptionProbe:
    """Redacted result of one public subscription request."""

    status: Optional[int]
    content_length: int = 0
    has_metadata: bool = False
    error_type: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.status == 200 and self.content_length > 0 and self.has_metadata


ProbeCallable = Callable[[str, float], Awaitable[SubscriptionProbe]]
SleepCallable = Callable[[float], Awaitable[None]]


async def probe_subscription_url(
    url: str,
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT,
) -> SubscriptionProbe:
    """Fetch a public subscription URL and return only non-secret metadata."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"User-Agent": "WaveMeshBot/subscription-readiness"}

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True, headers=headers) as response:
                body = await response.content.read(MAX_RESPONSE_BYTES)
                return SubscriptionProbe(
                    status=response.status,
                    content_length=len(body),
                    has_metadata=bool(response.headers.get("Subscription-Userinfo")),
                )
    except Exception as exc:
        # Do not log the exception text here: connector errors may contain the URL.
        return SubscriptionProbe(status=None, error_type=type(exc).__name__)


async def wait_for_subscription_ready(
    url: str,
    *,
    key_id: int | str | None = None,
    server_id: int | str | None = None,
    delays: Sequence[float] = DEFAULT_READINESS_DELAYS,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    probe: ProbeCallable | None = None,
    sleep: SleepCallable = asyncio.sleep,
) -> bool:
    """Poll until the public subscription returns content and usage metadata."""
    if not url or not delays:
        return False

    active_probe = probe or probe_subscription_url
    last_result = SubscriptionProbe(status=None)
    attempts = len(delays)

    for attempt, delay in enumerate(delays, start=1):
        if delay > 0:
            await sleep(delay)

        try:
            last_result = await active_probe(url, request_timeout)
        except Exception as exc:
            # Test/custom probes may raise. Keep logs redacted just like the HTTP probe.
            last_result = SubscriptionProbe(status=None, error_type=type(exc).__name__)

        logger.info(
            "Subscription readiness key_id=%s server_id=%s attempt=%s/%s "
            "status=%s bytes=%s metadata=%s ready=%s error=%s",
            key_id,
            server_id,
            attempt,
            attempts,
            last_result.status,
            last_result.content_length,
            last_result.has_metadata,
            last_result.ready,
            last_result.error_type or "-",
        )
        if last_result.ready:
            return True

    logger.warning(
        "Subscription readiness timeout key_id=%s server_id=%s attempts=%s "
        "last_status=%s last_error=%s",
        key_id,
        server_id,
        attempts,
        last_result.status,
        last_result.error_type or "-",
    )
    return False


__all__ = [
    "DEFAULT_READINESS_DELAYS",
    "SubscriptionProbe",
    "probe_subscription_url",
    "wait_for_subscription_ready",
]
