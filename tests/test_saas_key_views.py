from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Message
from bot.handlers.user import saas_keys as views
from bot.handlers.user.payments import payment_return


def message(chat=123, kind="private"):
    return Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=chat,type=kind))


def access():
    return {"access_id":"access-1", "authority":"managed", "legacy_key_id":"7", "enabled":True,
            "status":"ready", "desired_version":1, "expires_at":"2026-10-15T00:00:00Z",
            "subscription_url":"https://entry.invalid/sub/fixture"}


class KeyViewTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(views.internal_api_client,"tenant_id","tenant"),
            patch.object(views.internal_api_client,"get_telegram_dashboard",AsyncMock(return_value={
                "user":{"tenant_id":"tenant","user_id":"saas-user"},"accesses":[access()]})),
            patch("bot.services.vpn_api.get_client",AsyncMock(side_effect=AssertionError("No panel reads"))),
            patch.object(views,"safe_edit_or_send",AsyncMock()),
        ]
        self.handles = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    async def test_serverless_list_and_details_use_saas_status(self):
        await views.show_list(message(),123)
        rendered = self.handles[-1]
        buttons = rendered.await_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(buttons[0][0].callback_data,"saas_access:access-1")
        await views.show_access(123,message(),key_id=7)
        self.assertIn("Готов",rendered.await_args.args[1])
        callbacks = [b.callback_data for row in rendered.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("key_renew:7",callbacks)
        self.assertIn("key_replace:7",callbacks)
        self.assertIn("saas_billing",callbacks)
        self.handles[2].assert_not_awaited()

    async def test_config_uses_verified_url_without_local_key_or_panel(self):
        material = access() | {"ready":True,"node_id":"node-1"}
        with patch.object(views.internal_api_client,"get_access_material",AsyncMock(return_value=material)), patch.object(payment_return,"_render_verified_subscription",AsyncMock()) as send:
            await views.show_access(123,message(),access_id="access-1",config=True)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1].subscription_url,access()["subscription_url"])
        self.handles[2].assert_not_awaited()

    async def test_group_or_different_private_chat_never_requests_material(self):
        for target in (message(-1,"group"),message(124)):
            await views.show_list(target,123)
            await views.show_access(123,target,access_id="access-1",config=True)
        self.handles[1].assert_not_awaited()
        self.handles[-1].assert_not_awaited()

    async def test_foreign_access_or_tenant_never_delivers_material(self):
        with patch.object(views.internal_api_client,"get_access_material",AsyncMock()) as material:
            await views.show_access(123,message(),access_id="other",config=True)
            self.handles[1].return_value["user"]["tenant_id"] = "other"
            await views.show_access(123,message(),access_id="access-1",config=True)
        material.assert_not_awaited()

    async def test_guided_connection_reads_saas_url_and_blocks_group_delivery(self):
        from bot.utils import onboarding_delivery as guided
        from bot.handlers.user import onboarding
        key = {"id":7,"telegram_id":123,"saas_managed":1,"server_id":None}
        material = access() | {"ready":True,"node_id":"node-1"}
        with patch("bot.services.runtime_mode.saas_client_mode_enabled",return_value=True), patch.object(views.internal_api_client,"get_access_material",AsyncMock(return_value=material)), patch("database.requests.get_user_keys_for_display",return_value=[key]):
            self.assertEqual(onboarding._get_available_onboarding_keys(123),[key])
            self.assertEqual(await guided._access_value(key),access()["subscription_url"])
            callback = SimpleNamespace(message=message(-1,"group"),from_user=SimpleNamespace(id=123))
            with patch.object(guided,"_access_value",AsyncMock()) as value:
                self.assertFalse(await guided.send_onboarding_connection(callback,key,page_key="fixture",fallback_text="fixture",context={}))
                value.assert_not_awaited()
        self.handles[2].assert_not_awaited()

    async def test_old_key_entrypoints_do_not_discover_local_panels(self):
        from bot.handlers.user import keys
        from bot.utils.key_sender import send_key_with_qr
        callback = SimpleNamespace(from_user=SimpleNamespace(id=123),message=message(),data="key_show:7",answer=AsyncMock())
        with patch("bot.services.runtime_mode.saas_client_mode_enabled",return_value=True), patch.object(keys,"saas_client_mode_enabled",return_value=True), patch.object(views,"show_access",AsyncMock()) as show, patch.object(views,"show_list",AsyncMock()) as listing:
            await keys._render_my_keys_page(message(),123)
            await keys.show_key_details(123,7,message())
            await keys.key_show_handler(callback)
            await send_key_with_qr(callback,{"id":7,"server_id":None})
        self.assertEqual(show.await_count,3)
        listing.assert_awaited_once()
        self.handles[2].assert_not_awaited()
