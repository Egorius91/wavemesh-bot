from __future__ import annotations

import ast
from pathlib import Path
import unittest

from bot.services.startup_policy import (
    InternalApiStartupRequired,
    enforce_internal_api_startup,
)


MAIN_PATH = Path("main.py")
UNIT_PATH = Path("systemd/wavemesh-bot.service")


def function_calls(function: ast.AsyncFunctionDef | ast.FunctionDef) -> dict[str, int]:
    calls: dict[str, int] = {}
    for node in ast.walk(function):
        if not isinstance(node, (ast.Call, ast.Await)):
            continue
        call = node.value if isinstance(node, ast.Await) else node
        if not isinstance(call, ast.Call):
            continue
        target = call.func
        if isinstance(target, ast.Name):
            calls.setdefault(target.id, call.lineno)
        elif isinstance(target, ast.Attribute):
            calls.setdefault(target.attr, call.lineno)
    return calls


class SaasStartupPolicyTests(unittest.TestCase):
    def test_saas_mode_fails_when_internal_api_is_not_ready(self) -> None:
        with self.assertRaisesRegex(
            InternalApiStartupRequired,
            "INTERNAL_API_STARTUP_REQUIRED",
        ):
            enforce_internal_api_startup(
                internal_api_ready=False,
                saas_client_mode=True,
            )

    def test_saas_mode_starts_when_internal_api_is_ready(self) -> None:
        enforce_internal_api_startup(
            internal_api_ready=True,
            saas_client_mode=True,
        )

    def test_legacy_mode_preserves_startup_without_internal_api(self) -> None:
        enforce_internal_api_startup(
            internal_api_ready=False,
            saas_client_mode=False,
        )

    def test_internal_api_probe_precedes_mutations_telegram_and_jobs(self) -> None:
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
        calls = function_calls(startup)

        self.assertLess(
            calls["internal_api_startup_probe"],
            calls["enforce_internal_api_startup"],
        )
        self.assertLess(
            calls["enforce_internal_api_startup"],
            calls["run_migrations"],
        )
        self.assertLess(
            calls["enforce_internal_api_startup"],
            calls["get_me"],
        )
        self.assertLess(
            calls["enforce_internal_api_startup"],
            calls["start_legacy_background_tasks"],
        )

    def test_polling_setup_does_not_start_background_jobs_early(self) -> None:
        tree = ast.parse(
            MAIN_PATH.read_text(encoding="utf-8"),
            filename=str(MAIN_PATH),
        )
        main = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "main"
        )

        calls = function_calls(main)
        self.assertNotIn("create_task", calls)
        self.assertNotIn("start_legacy_background_tasks", calls)

    def test_failed_saas_startup_logs_only_a_fixed_blocker_code(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn("WaveMesh SaaS startup blocked: code=%s", source)
        self.assertIn("error.code", source)
        self.assertNotIn("internal_api_client.token", source)
        self.assertNotIn("WAVEMESH_INTERNAL_API_TOKEN", source)

    def test_systemd_uses_a_conservative_fail_fast_retry_delay(self) -> None:
        lines = set(
            UNIT_PATH.read_text(encoding="utf-8").splitlines()
        )

        self.assertIn("Restart=always", lines)
        self.assertIn("RestartSec=30", lines)


if __name__ == "__main__":
    unittest.main()
