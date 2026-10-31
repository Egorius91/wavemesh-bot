"""Authorization through real aiogram dispatch; every external effect is mocked."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher, Router
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.middlewares.private_commercial import install_private_commercial_boundary
from bot.utils import admin as admin_policy


CALLBACKS = (
    "admin_key_delete_ask:7", "admin_key_delete_confirm:7",
    "admin_sync_deleted_menu", "admin_sync_deleted_panel_ask",
    "admin_sync_deleted_panel_confirm", "admin_sync_deleted_db_ask",
    "admin_sync_deleted_db_confirm", "admin_sync_db_orphans_ask",
    "admin_sync_db_orphans_confirm", "admin_sync_db_gone_ask:3",
    "admin_sync_db_gone_confirm:3", "admin_sync_db_missing_ask:3",
    "admin_sync_db_missing_confirm:3", "admin_sync_db_unreach_ask:3",
    "admin_sync_db_unreach_confirm:3",
)
ADMIN, OTHER = 101, 202


def callback(data, *, actor=OTHER, message_actor=777000, chat_id=None):
    message = Message(message_id=1, date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id or actor, type="private"),
        from_user=User(id=message_actor, is_bot=True, first_name="Fixture bot"))
    return CallbackQuery(id="fixture-query", chat_instance="fixture-chat",
        from_user=User(id=actor, is_bot=False, first_name="Fixture actor"),
        message=message, data=data)


class AdminKeyCleanupAuthorizationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict("os.environ", {"WAVEMESH_SAAS_CLIENT_MODE": "false"}))
        self.stack.enter_context(patch.object(admin_policy, "ADMIN_IDS", [ADMIN]))
        self.answer = self.stack.enter_context(patch.object(CallbackQuery, "answer", AsyncMock()))
        self.db = self.stack.enter_context(patch("database.connection.get_db",
            side_effect=AssertionError("unexpected database access")))
        path = Path(__file__).resolve().parents[1] / "bot/handlers/admin/users_keys_deleted.py"
        spec = importlib.util.spec_from_file_location("_cleanup_authorization_fixture", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tripwires = []
        for name in ("get_vpn_key_by_id", "delete_vpn_key", "get_user_vpn_keys",
                     "get_active_servers", "get_all_servers", "get_users_stats",
                     "get_client_from_server_data"):
            tripwire = self.stack.enter_context(patch.object(self.module, name,
                side_effect=AssertionError("unexpected business dependency: " + name)))
            self.tripwires.append(tripwire)
        self.render = self.stack.enter_context(patch.object(self.module, "safe_edit_or_send", AsyncMock()))
        self.scan = self.stack.enter_context(patch.object(self.module, "_scan_db_keys", AsyncMock(
            side_effect=AssertionError("unexpected panel scan"))))
        self.bot = Bot(token="777000:" + "fixture" * 8)
        self.addAsyncCleanup(self.bot.session.close)
        self.dp = Dispatcher(disable_fsm=True)
        install_private_commercial_boundary(self.dp)
        self.dp.include_router(self.module.router)
        self.user_handler = AsyncMock(return_value="ordinary-user-callback")
        later = Router()
        async def ordinary_callback(event):
            return await self.user_handler(event)
        later.callback_query.register(ordinary_callback)
        self.dp.include_router(later)

    async def feed(self, event):
        update = Update.model_construct(update_id=1, callback_query=event).as_(self.bot)
        return await self.dp.feed_update(self.bot, update)

    def assert_no_business(self):
        self.db.assert_not_called()
        for tripwire in self.tripwires:
            tripwire.assert_not_called()
        self.render.assert_not_awaited()
        self.scan.assert_not_awaited()

    async def test_all_registered_cleanup_callbacks_deny_non_admin_before_effects(self):
        self.assertEqual(len(self.module.router.callback_query.handlers), len(CALLBACKS))
        for mode in ("false", "true"):
            with patch.dict("os.environ", {"WAVEMESH_SAAS_CLIENT_MODE": mode}):
                for data in CALLBACKS:
                    with self.subTest(mode=mode, data=data):
                        self.answer.reset_mock()
                        await self.feed(callback(data))
                        self.answer.assert_awaited_once_with("⛔ Доступ запрещён", show_alert=True)
                        self.assert_no_business()
        self.user_handler.assert_not_awaited()

    async def test_alternate_and_malformed_ids_are_denied_before_parsing(self):
        for data in ("admin_key_delete_confirm:0007:ignored",
                     "admin_key_delete_confirm:not-an-integer",
                     "admin_sync_db_unreach_confirm:"):
            with self.subTest(data=data):
                self.answer.reset_mock()
                await self.feed(callback(data))
                self.answer.assert_awaited_once_with("⛔ Доступ запрещён", show_alert=True)
                self.assert_no_business()

    async def test_callback_actor_cannot_borrow_admin_message_or_chat_identity(self):
        await self.feed(callback("admin_key_delete_confirm:7", message_actor=ADMIN, chat_id=ADMIN))
        self.answer.assert_awaited_once_with("⛔ Доступ запрещён", show_alert=True)
        self.assert_no_business()
        self.answer.reset_mock()
        event = callback("admin_key_delete_confirm:7").model_copy(update={"from_user": None})
        await self.feed(event)
        self.answer.assert_awaited_once_with("⛔ Доступ запрещён", show_alert=True)
        self.assert_no_business()

    async def test_authorized_admin_still_reaches_every_registered_callback(self):
        handlers = self.module.router.callback_query.handlers
        mocks = []
        for index, handler in enumerate(handlers):
            mock = AsyncMock(return_value=index)
            mocks.append(self.stack.enter_context(patch.object(handler, "callback", mock)))
        with patch.dict("os.environ", {"WAVEMESH_SAAS_CLIENT_MODE": "true"}):
            for index, data in enumerate(CALLBACKS):
                self.assertEqual(await self.feed(callback(data, actor=ADMIN)), index)
        for mock in mocks:
            mock.assert_awaited_once()
        self.answer.assert_not_awaited()
        self.user_handler.assert_not_awaited()

    async def test_authorized_single_key_delete_keeps_db_first_and_both_panel_forms(self):
        events = []
        client = SimpleNamespace(
            delete_clients_by_email_on_server=AsyncMock(side_effect=lambda *a: events.append("email") or 1),
            delete_client=AsyncMock(side_effect=lambda *a: events.append("client")))
        self.module.get_client_from_server_data.side_effect = lambda value: client
        self.module.delete_vpn_key.side_effect = lambda value: events.append("db") or True
        self.module.get_users_stats.side_effect = None
        self.module.get_users_stats.return_value = {}
        self.stack.enter_context(patch.object(self.module, "users_menu_kb", return_value=None))
        for subscription in (True, False):
            with self.subTest(subscription=subscription):
                events.clear()
                self.module.get_vpn_key_by_id.side_effect = None
                self.module.get_vpn_key_by_id.return_value = dict(id=7, telegram_id=0, saas_managed=0,
                    server_active=True, host="fixture.invalid", sub_id="fixture" if subscription else None,
                    panel_email="user_fixture", panel_inbound_id=9, client_uuid="fixture-client")
                await self.feed(callback("admin_key_delete_confirm:7", actor=ADMIN))
                self.assertEqual(events, ["db", "email" if subscription else "client"])
        client.delete_clients_by_email_on_server.assert_awaited_once_with("user_fixture")
        client.delete_client.assert_awaited_once_with(9, "fixture-client")

    async def test_authorized_bulk_cleanup_keeps_known_and_external_clients(self):
        @contextmanager
        def fake_db():
            conn = MagicMock()
            conn.execute.return_value.fetchall.return_value = [{"email": "user_kept"}]
            yield conn
        self.db.side_effect = fake_db
        self.module.get_active_servers.side_effect = None
        self.module.get_active_servers.return_value = [{"id": 3, "name": "Fixture server"}]
        client = SimpleNamespace(get_inbounds=AsyncMock(return_value=[dict(id=9, settings=json.dumps(dict(
            clients=[dict(email="user_old", id="old"), dict(email="user_kept", id="kept"),
                     dict(email="external", id="external")])))]), delete_client=AsyncMock())
        self.module.get_client_from_server_data.side_effect = lambda value: client
        self.stack.enter_context(patch.object(self.module, "sync_deleted_menu_kb", return_value=None))
        await self.feed(callback("admin_sync_deleted_panel_confirm", actor=ADMIN))
        client.delete_client.assert_awaited_once_with(9, "old")
        self.answer.assert_awaited_once_with()

    async def test_unrelated_user_callback_passes_without_admin_denial(self):
        for mode in ("false", "true"):
            with patch.dict("os.environ", {"WAVEMESH_SAAS_CLIENT_MODE": mode}):
                self.assertEqual(await self.feed(callback("ordinary-user-action")), "ordinary-user-callback")
        self.answer.assert_not_awaited()
        self.assert_no_business()
        self.assertEqual(self.user_handler.await_count, 2)
