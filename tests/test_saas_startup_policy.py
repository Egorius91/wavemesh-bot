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

    def test_internal_api_probe_precedes_local_mutations_and_telegram_startup(
        self,
    ) -> None:
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
