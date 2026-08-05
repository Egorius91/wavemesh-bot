from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import symtable


SCHEDULER_PATH = Path("bot/services/scheduler.py")
FUNCTION_NAME = "check_and_notify_updates"


class FakeKeyboardBuilder:
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []

    def row(self, *buttons: object) -> None:
        self.rows.append(buttons)

    def as_markup(self) -> dict[str, object]:
        return {"rows": self.rows}


class FakeKeyboardButton:
    def __init__(self, *, text: str, callback_data: str) -> None:
        self.text = text
        self.callback_data = callback_data


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.messages.append(dict(kwargs))


def _function_node() -> ast.AsyncFunctionDef:
    tree = ast.parse(
        SCHEDULER_PATH.read_text(encoding="utf-8"),
        filename=str(SCHEDULER_PATH),
    )

    for node in tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == FUNCTION_NAME
        ):
            return node

    raise AssertionError(f"{FUNCTION_NAME} not found")


def _load_function(**overrides: object):
    node = _function_node()
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)

    namespace: dict[str, object] = {
        "ADMIN_IDS": [101, 202],
        "GITHUB_REPO_URL": "https://github.example/repo",
        "InlineKeyboardBuilder": FakeKeyboardBuilder,
        "InlineKeyboardButton": FakeKeyboardButton,
        "check_for_updates": lambda: (
            True,
            1,
            "commit summary",
            False,
            None,
            False,
        ),
        "get_blocked_message": lambda: "updates blocked",
        "is_update_blocked": lambda: False,
        "is_update_notifications_enabled": lambda: True,
        "logger": FakeLogger(),
        "try_unblock": lambda: None,
    }
    namespace.update(overrides)
    exec(compile(module, str(SCHEDULER_PATH), "exec"), namespace)
    return namespace[FUNCTION_NAME]


def test_keyboard_names_are_global_in_update_checker() -> None:
    source = SCHEDULER_PATH.read_text(encoding="utf-8")
    table = symtable.symtable(source, str(SCHEDULER_PATH), "exec")
    function_table = next(
        child
        for child in table.get_children()
        if child.get_name() == FUNCTION_NAME
    )

    for name in ("InlineKeyboardBuilder", "InlineKeyboardButton"):
        symbol = function_table.lookup(name)
        assert symbol.is_global()
        assert not symbol.is_local()


def test_blocked_update_path_sends_dismiss_keyboard() -> None:
    bot = FakeBot()
    function = _load_function(is_update_blocked=lambda: True)

    asyncio.run(function(bot))

    assert len(bot.messages) == 2
    assert all(message["text"] == "updates blocked" for message in bot.messages)
    callbacks = [
        button.callback_data
        for row in bot.messages[0]["reply_markup"]["rows"]
        for button in row
    ]
    assert callbacks == ["dismiss_msg"]


def test_available_update_path_sends_update_keyboard() -> None:
    bot = FakeBot()
    function = _load_function()

    asyncio.run(function(bot))

    assert len(bot.messages) == 2
    assert all("Доступно обновление" in message["text"] for message in bot.messages)
    callbacks = [
        button.callback_data
        for row in bot.messages[0]["reply_markup"]["rows"]
        for button in row
    ]
    assert callbacks == ["admin_update_bot"]
