from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bot.services.startup_policy import (
    InternalApiStartupRequired,
    enforce_internal_api_startup,
)


MAIN_PATH = Path("main.py")
UNIT_PATH = Path("systemd/wavemesh-bot.service")


def test_saas_mode_fails_when_internal_api_is_not_ready() -> None:
    with pytest.raises(
        InternalApiStartupRequired,
        match="INTERNAL_API_STARTUP_REQUIRED",
    ):
        enforce_internal_api_startup(
            internal_api_ready=False,
            saas_client_mode=True,
        )


def test_saas_mode_starts_when_internal_api_is_ready() -> None:
    enforce_internal_api_startup(
        internal_api_ready=True,
        saas_client_mode=True,
    )


def test_legacy_mode_preserves_startup_without_internal_api() -> None:
    enforce_internal_api_startup(
        internal_api_ready=False,
        saas_client_mode=False,
    )


def test_internal_api_probe_precedes_local_mutations_and_telegram_startup() -> None:
    tree = ast.parse(
        MAIN_PATH.read_text(encoding="utf-8"),
        filename=str(MAIN_PATH),
    )
    startup = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "on_startup"
    )

    calls: dict[str, int] = {}
    for node in ast.walk(startup):
        if not isinstance(node, (ast.Call, ast.Await)):
            continue
        call = node.value if isinstance(node, ast.Await) else node
        if not isinstance(call, ast.Call):
            continue
        function = call.func
        if isinstance(function, ast.Name):
            calls.setdefault(function.id, call.lineno)
        elif isinstance(function, ast.Attribute):
            calls.setdefault(function.attr, call.lineno)

    assert calls["internal_api_startup_probe"] < calls["enforce_internal_api_startup"]
    assert calls["enforce_internal_api_startup"] < calls["run_migrations"]
    assert calls["enforce_internal_api_startup"] < calls["get_me"]


def test_failed_saas_startup_logs_only_a_fixed_blocker_code() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "WaveMesh SaaS startup blocked: code=%s" in source
    assert "error.code" in source
    assert "internal_api_client.token" not in source
    assert "WAVEMESH_INTERNAL_API_TOKEN" not in source


def test_systemd_uses_a_conservative_fail_fast_retry_delay() -> None:
    lines = set(
        UNIT_PATH.read_text(encoding="utf-8").splitlines()
    )

    assert "Restart=always" in lines
    assert "RestartSec=30" in lines
