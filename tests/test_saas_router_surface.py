from __future__ import annotations

import ast
from pathlib import Path
import unittest


PAYMENTS_INIT = Path("bot/handlers/user/payments/__init__.py")
USER_INIT = Path("bot/handlers/user/__init__.py")
START = Path("bot/handlers/user/start.py")
SAAS = Path("bot/handlers/user/payments/saas.py")


def imports_in(nodes: list[ast.stmt]) -> set[str]:
    result: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom) and child.module:
                result.add(child.module)
    return result


def first_mode_if(path: Path, *, negated: bool = False) -> ast.If:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if negated:
            if (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Call)
                and isinstance(test.operand.func, ast.Name)
                and test.operand.func.id == "saas_client_mode_enabled"
            ):
                return node
        elif (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "saas_client_mode_enabled"
        ):
            return node
    raise AssertionError(f"runtime-mode branch not found in {path}")


class SaasRouterSurfaceTests(unittest.TestCase):
    def test_saas_payment_branch_imports_only_authoritative_routers(self) -> None:
        branch = first_mode_if(PAYMENTS_INIT)
        self.assertEqual(
            imports_in(branch.body),
            {"payment_return", "saas"},
        )
        legacy_imports = imports_in(branch.orelse)
        self.assertTrue(
            {
                "base",
                "balance",
                "yookassa",
                "wata",
                "platega",
                "cardlink",
                "stars",
                "crypto",
                "keys_config",
                "demo",
            }.issubset(legacy_imports)
        )

    def test_trial_and_tariff_routers_exist_only_in_legacy_branch(self) -> None:
        branch = first_mode_if(USER_INIT, negated=True)
        self.assertEqual(imports_in(branch.body), {"trial", "tariffs"})

    def test_known_legacy_links_are_blocked_without_matching_opaque_return(self) -> None:
        tree = ast.parse(START.read_text(encoding="utf-8"), filename=str(START))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "is_legacy_payment_start_arg"
        )
        prefixes = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_LEGACY_PAYMENT_START_PREFIXES"
                for target in node.targets
            )
        )
        namespace: dict[str, object] = {
            "_LEGACY_PAYMENT_START_PREFIXES": ast.literal_eval(prefixes),
        }
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(START), "exec"), namespace)
        matcher = namespace["is_legacy_payment_start_arg"]

        for value in (
            "pay_yookassa_order",
            "pay_wata_order",
            "pay_platega_order",
            "pay_cardlink_order",
            "cl_old",
            "bill123",
        ):
            self.assertTrue(matcher(value))
        self.assertFalse(matcher("pay_abcdefghijklmnopqrstuvwxyzABCDEF"))
        self.assertFalse(matcher(None))

    def test_start_skips_local_catalog_and_trial_in_saas_mode(self) -> None:
        source = START.read_text(encoding="utf-8")
        self.assertIn(
            'if saas_client_mode_enabled():\n        return ""',
            source,
        )
        self.assertIn("not saas_client_mode_enabled()", source)
        self.assertIn("if args and not saas_mode:", source)
        self.assertIn(
            "if args and not saas_mode and args.startswith('bill'):",
            source,
        )

    def test_saas_router_owns_buy_command_and_button(self) -> None:
        source = SAAS.read_text(encoding="utf-8")
        self.assertIn('@router.message(Command("buy"))', source)
        self.assertIn('@router.callback_query(F.data == "buy_key")', source)
        self.assertIn("_render_saas_new_access_tariffs", source)
        self.assertNotIn("create_pending_order", source)


if __name__ == "__main__":
    unittest.main()
