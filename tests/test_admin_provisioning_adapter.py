import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Message, User
from bot.handlers.admin import provisioning as handler
from bot.services import admin_provisioning as service
from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


def callback(admin=9, chat=9, kind="private"):
    return SimpleNamespace(from_user=User(id=admin, is_bot=False, first_name="Fixture"),
        message=Message(message_id=5, date=datetime.now(timezone.utc), chat=Chat(id=chat, type=kind)),
        data="admin_grant_reconcile:operation", answer=AsyncMock())


class AdapterTests(IsolatedAsyncioTestCase):
    async def test_readback_is_get_with_original_key_and_strips_unknown_fields(self):
        client = WaveMeshInternalApiClient()
        result = {"submission": "OBSERVED", "status": "READY", "access_id": "access-1",
                  "command_id": "command-1", "assigned_entry_node_id": "node-1", "legacy_key_id": "1",
                  "expires_at": "2026-10-01T00:00:00Z", "can_retry_create": False, "secret": "not forwarded"}
        with patch.object(client, "_request", AsyncMock(return_value=result)) as request:
            observed = await client.get_access_provisioning("admin-grant-0000000000000000")
            request.assert_awaited_once_with("GET", "bot/access-provisioning", idempotency_key="admin-grant-0000000000000000")
            self.assertNotIn("secret", observed)
        for invalid in (None, {}, {**result, "submission": []}, {**result, "can_retry_create": True},
                        {**result, "expires_at": "2026-10-01"}, {**result, "access_id": "../foreign"}):
            with self.subTest(invalid=invalid), patch.object(client, "_request", AsyncMock(return_value=invalid)):
                with self.assertRaises(InternalApiError):
                    await client.get_access_provisioning("admin-grant-0000000000000000")

    async def test_unauthorized_or_nonprivate_confirmation_never_opens_journal(self):
        for admin, chat, kind in ((8,8,"private"), (9,10,"private"), (9,-1,"group")):
            with patch.object(handler, "is_admin", lambda i: i==9), patch.object(handler, "saas_client_mode_enabled", return_value=True), patch.object(handler, "Journal") as journal:
                await handler.confirm(callback(admin,chat,kind), AsyncMock())
                journal.assert_not_called()

    async def test_restart_duplicate_confirmation_does_not_need_fsm_or_send_http(self):
        row = {"id": "operation", "status": "PENDING", "telegram_id":123}
        state = AsyncMock()
        with patch.object(handler, "is_admin", return_value=True), patch.object(handler, "saas_client_mode_enabled", return_value=True), patch.object(handler, "Journal") as journal, patch.object(handler, "show", AsyncMock()) as show:
            journal.return_value.for_callback.return_value = row
            await handler.confirm(callback(), state)
            state.get_data.assert_not_awaited()
            journal.return_value.prepare.assert_not_called()
            show.assert_awaited_once()

    async def test_other_admin_cannot_reconcile_operation(self):
        with patch.object(handler, "is_admin", return_value=True), patch.object(handler, "saas_client_mode_enabled", return_value=True), patch.object(handler, "Journal") as journal, patch.object(handler, "ProvisioningWorker") as worker:
            journal.return_value.get.return_value = {"admin_id":10}
            await handler.reconcile(callback())
            worker.assert_not_called()

    async def test_start_worker_only_in_saas_mode_and_stop_before_restarting(self):
        await service.stop_admin_provisioning_worker()
        with patch("bot.services.runtime_mode.saas_client_mode_enabled", return_value=False):
            service.start_admin_provisioning_worker()
            self.assertIsNone(service._task)
        entered = asyncio.Event()
        async def run_once():
            entered.set()
            await asyncio.Event().wait()
        with patch("bot.services.runtime_mode.saas_client_mode_enabled", return_value=True), patch("bot.services.internal_api.internal_api_client", SimpleNamespace(enabled=True)), patch.object(service.ProvisioningWorker, "run_once", side_effect=run_once):
            service.start_admin_provisioning_worker()
            original = service._task
            service.start_admin_provisioning_worker()
            self.assertIs(service._task, original)
            await asyncio.wait_for(entered.wait(), 1)
            await service.stop_admin_provisioning_worker()
            self.assertTrue(original.done())
            self.assertIsNone(service._task)
