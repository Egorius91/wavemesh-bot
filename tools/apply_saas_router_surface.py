from __future__ import annotations

from pathlib import Path


START = Path("bot/handlers/user/start.py")
SAAS = Path("bot/handlers/user/payments/saas.py")
TEST = Path("tests/test_saas_router_surface.py")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


start = START.read_text(encoding="utf-8")
start = replace_once(
    start,
    '''from bot.services.internal_api import schedule_telegram_user_upsert
''',
    '''from bot.services.internal_api import schedule_telegram_user_upsert
from bot.services.runtime_mode import saas_client_mode_enabled
''',
    "start runtime import",
)
start = replace_once(
    start,
    '''router = Router()


def _tariff_group_title''',
    '''router = Router()

_LEGACY_PAYMENT_START_PREFIXES = (
    "pay_yookassa_",
    "pay_wata_",
    "pay_platega_",
    "pay_cardlink_",
    "cl_",
    "bill",
)


def is_legacy_payment_start_arg(value: str | None) -> bool:
    """Identify only historical provider/billing deep links."""
    return isinstance(value, str) and value.startswith(
        _LEGACY_PAYMENT_START_PREFIXES
    )


def _tariff_group_title''',
    "legacy prefix helper",
)
start = replace_once(
    start,
    '''def _build_tariff_text() -> str:
    """Формирует сгруппированный блок тарифов для плейсхолдера %тарифы%."""
    from database.requests import (
''',
    '''def _build_tariff_text() -> str:
    """Формирует сгруппированный блок тарифов для плейсхолдера %тарифы%."""
    if saas_client_mode_enabled():
        return ""

    from database.requests import (
''',
    "SaaS tariff text guard",
)
start = replace_once(
    start,
    '''    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
''',
    '''    show_trial = (
        not saas_client_mode_enabled()
        and is_trial_enabled()
        and get_trial_tariff_id() is not None
        and not has_used_trial(user_id)
    )
''',
    "trial visibility guard",
)
start = replace_once(
    start,
    '''    args = command.args
    if args:
        try:
            from bot.handlers.user.payments.base import handle_payment_deeplink
''',
    '''    args = command.args
    saas_mode = saas_client_mode_enabled()

    if args and saas_mode and is_legacy_payment_start_arg(args):
        await state.clear()
        await safe_edit_or_send(
            message,
            "⚠️ <b>Старая платёжная ссылка больше не используется</b>\\n\\n"
            "Откройте актуальные тарифы WaveMesh командой /buy.",
            force_new=True,
        )
        return

    if args and not saas_mode:
        try:
            from bot.handlers.user.payments.base import handle_payment_deeplink
''',
    "legacy deeplink mode guard",
)
start = replace_once(
    start,
    '''    if args and args.startswith('bill'):
''',
    '''    if args and not saas_mode and args.startswith('bill'):
''',
    "crypto bill guard",
)
START.write_text(start, encoding="utf-8")

saas = SAAS.read_text(encoding="utf-8")
saas = replace_once(
    saas,
    '''from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
''',
    '''from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
''',
    "SaaS buy imports",
)
old_start = saas.index('@router.callback_query(F.data == "buy_key")')
old_end = saas.index(
    '\n\n@router.callback_query(F.data.startswith(f"{_NEW_CHECKOUT_PREFIX}:"))',
    old_start,
)
new_block = '''async def _render_saas_new_access_tariffs(
    target: Message,
    telegram_id: int,
) -> bool:
    """Render the authoritative SaaS tariff catalog for a Telegram user."""
    try:
        dashboard, tariffs = await internal_api_client.get_telegram_dashboard(
            telegram_id,
        ), await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS new access catalog failed: telegram_id=%s code=%s status=%s",
            telegram_id,
            error.code,
            error.status,
        )
        await safe_edit_or_send(
            target,
            "❌ <b>Не удалось загрузить тарифы WaveMesh</b>\\n\\n"
            "Попробуйте немного позже.",
            force_new=True,
        )
        return False

    user = dashboard.get("user")
    if not isinstance(user, dict) or not user.get("user_id"):
        await safe_edit_or_send(
            target,
            "⏳ <b>Профиль WaveMesh ещё создаётся</b>\\n\\n"
            "Повторите команду /buy немного позже.",
            force_new=True,
        )
        return False

    available = [
        item
        for item in tariffs
        if isinstance(item, dict)
        and isinstance(item.get("tariff_id"), str)
        and isinstance(item.get("price_rub"), (int, float))
        and item["price_rub"] > 0
    ]
    builder = InlineKeyboardBuilder()
    for tariff in available:
        data = f"{_NEW_CHECKOUT_PREFIX}:{tariff['tariff_id']}"
        if len(data.encode("utf-8")) <= 64:
            builder.row(
                InlineKeyboardButton(
                    text=_tariff_button_text(tariff),
                    callback_data=data,
                )
            )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="home"))
    await safe_edit_or_send(
        target,
        "💳 <b>Купить новый ключ</b>\\n\\n"
        "Выберите тариф. Оплата и создание доступа выполняются через WaveMesh SaaS.",
        reply_markup=builder.as_markup(),
        force_new=True,
    )
    return True


@router.message(Command("buy"))
async def saas_buy_command(message: Message) -> None:
    """Open the authoritative SaaS catalog from the /buy command."""
    if message.from_user is None:
        return
    await _render_saas_new_access_tariffs(
        message,
        message.from_user.id,
    )


@router.callback_query(F.data == "buy_key")
async def saas_new_access_tariffs(callback: CallbackQuery) -> None:
    """Open the authoritative SaaS catalog from the main-page button."""
    rendered = await _render_saas_new_access_tariffs(
        callback.message,
        callback.from_user.id,
    )
    await callback.answer(
        "" if rendered else "Не удалось загрузить тарифы WaveMesh.",
        show_alert=not rendered,
    )
'''
saas = saas[:old_start] + new_block + saas[old_end:]
SAAS.write_text(saas, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations

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
            'if saas_client_mode_enabled():\\n        return ""',
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
''',
    encoding="utf-8",
)
