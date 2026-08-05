"""Startup safety policy for the authoritative WaveMesh SaaS mode."""

from __future__ import annotations


class InternalApiStartupRequired(RuntimeError):
    """Raised when SaaS mode cannot prove its authoritative API is ready."""

    code = "INTERNAL_API_STARTUP_REQUIRED"

    def __init__(self) -> None:
        super().__init__(self.code)


def enforce_internal_api_startup(
    *,
    internal_api_ready: bool,
    saas_client_mode: bool,
) -> None:
    """Block Telegram polling when SaaS mode has no authoritative API."""
    if saas_client_mode and not internal_api_ready:
        raise InternalApiStartupRequired()
