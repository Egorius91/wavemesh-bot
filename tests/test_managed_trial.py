from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Message, User
from bot.handlers.user import managed_trial as trial
from bot.handlers.user.payments import payment_return
from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


def pending(**overrides):
    return {"activation_id": "activation-1", "access_id": "access-1", "command_id": "command-1",
            "subscription_id": None, "status": "MATERIALIZING", "expires_at": "2026-10-01T00:00:00Z", **overrides}


def message(chat_id=123, kind="private"):
    return Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type=kind),
                   from_user=User(id=123, is_bot=False, first_name="Fixture"), text="/trial")


class TrialClientTests(IsolatedAsyncioTestCase):
    async def test_duplicate_requests_keep_the_same_user_offer_without_generated_keys(self):
        client = WaveMeshInternalApiClient()
        with patch.object(client, "_request", AsyncMock(return_value=pending())) as request:
            results = await asyncio.gather(client.activate_trial("user-1"), client.activate_trial("user-1"))
            self.assertEqual(results[0], results[1])
            self.assertEqual(request.await_args_list[0], request.await_args_list[1])
            request.assert_awaited_with("POST", "bot/trials", json_body={"user_id": "user-1", "offer_code": "TRIAL3"})

    async def test_status_path_and_response_validation(self):
        client = WaveMeshInternalApiClient()
        with patch.object(client, "_request", AsyncMock(return_value=pending(extra_secret="never forward"))) as request:
            result = await client.get_trial("user-1")
            request.assert_awaited_once_with("GET", "bot/users/user-1/trials/TRIAL3")
            self.assertNotIn("extra_secret", result)
        for value in (None, {}, pending(access_id="../foreign"), pending(status=[]), pending(status="unknown"),
                      pending(expires_at="tomorrow"), pending(expires_at="2026-10-01"), pending(status="READY")):
            with self.subTest(value=value), patch.object(client, "_request", AsyncMock(return_value=value)):
                with self.assertRaises(InternalApiError):
                    await client.get_trial("user-1")

    async def test_invalid_identity_cannot_reach_transport(self):
        client = WaveMeshInternalApiClient()
        with patch.object(client, "_request", AsyncMock()) as request:
            for value in (None, 123, "", "../user", "a" * 129):
                with self.assertRaises(InternalApiError):
                    await client.activate_trial(value)
                with self.assertRaises(InternalApiError):
                    await client.get_trial(value)
            request.assert_not_awaited()


class TrialHandlerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.mode = patch.object(trial, "saas_client_mode_enabled", return_value=True)
        self.mode.start()
        self.addCleanup(self.mode.stop)
        self.client = patch.object(trial, "internal_api_client").start()
        self.addCleanup(patch.stopall)
        self.client.get_telegram_dashboard = AsyncMock(return_value={"user": {"user_id": "canonical-user"}})
        self.client.activate_trial = AsyncMock(return_value=pending())
        self.client.get_trial = AsyncMock(return_value=pending())
        self.render = patch.object(trial, "safe_edit_or_send", AsyncMock()).start()

    async def test_explicit_activation_uses_dashboard_identity_and_status_survives_restart(self):
        await trial._show(message(), 123, activate=True)
        self.client.activate_trial.assert_awaited_once_with("canonical-user")
        # A fresh /trial message has no FSM or callback access identity.
        await trial.trial_command(message())
        self.client.get_trial.assert_awaited_once_with("canonical-user")
        self.assertEqual(self.client.activate_trial.await_count, 1)

    async def test_duplicate_callbacks_do_not_mint_a_new_operation_identity(self):
        callback = SimpleNamespace(message=message(), from_user=SimpleNamespace(id=123),
                                   data="trial_activate", answer=AsyncMock())
        await asyncio.gather(trial.trial_callback(callback), trial.trial_callback(callback))
        self.assertEqual(self.client.activate_trial.await_count, 2)
        for call in self.client.activate_trial.await_args_list:
            self.assertEqual(call.args, ("canonical-user",))
        self.assertEqual(callback.answer.await_count, 2)

    async def test_menu_visibility_ignores_local_trial_usage_in_saas_mode(self):
        from bot.handlers.user import start
        with patch.object(start, "saas_client_mode_enabled", return_value=True), \
             patch.object(start, "_build_tariff_text", return_value=""), \
             patch.object(start, "is_referral_enabled", return_value=False), \
             patch("database.requests.is_trial_enabled", side_effect=AssertionError("legacy state")), \
             patch("database.requests.get_trial_tariff_id", side_effect=AssertionError("legacy state")), \
             patch("database.requests.has_used_trial", side_effect=AssertionError("legacy state")), \
             patch("bot.utils.live_page_renderer.render_live_page", AsyncMock()) as render:
            await start._render_main_page(message())
            self.assertTrue(render.await_args.kwargs["visibility"]["btn_trial"])

    async def test_lost_post_response_offers_readback_and_never_auto_reposts(self):
        self.client.activate_trial.side_effect = InternalApiError("SECRET", code="INTERNAL_API_TIMEOUT", retryable=True)
        await trial._show(message(), 123, activate=True)
        rendered = self.render.await_args.args[1]
        self.assertNotIn("SECRET", rendered)
        self.assertIn("не подтверждён", rendered)
        self.assertNotIn("trial_activate", str(self.render.await_args.kwargs["reply_markup"]))
        await trial.trial_command(message())
        self.assertEqual(self.client.activate_trial.await_count, 1)
        self.client.get_trial.assert_awaited_once()

    async def test_absent_trial_offers_explicit_activation_without_writing(self):
        self.client.get_trial.side_effect = InternalApiError("not found", status=404)
        await trial.trial_command(message())
        self.client.activate_trial.assert_not_awaited()
        self.assertIn("trial_activate", str(self.render.await_args.kwargs["reply_markup"]))

    async def test_missing_profile_does_not_mean_unused_trial(self):
        self.client.get_telegram_dashboard.side_effect = InternalApiError("not found", status=404)
        await trial.trial_command(message())
        self.client.activate_trial.assert_not_awaited()
        self.client.get_trial.assert_not_awaited()
        self.assertNotIn("trial_activate", str(self.render.await_args.kwargs["reply_markup"]))

    async def test_pending_terminal_and_legacy_states_never_deliver_or_reactivate(self):
        with patch.object(trial, "process_ready_payment_return", AsyncMock()) as deliver:
            for status in ("PENDING", "MATERIALIZING", "FAILED", "EXPIRED", "DISABLED"):
                self.client.get_trial.return_value = pending(status=status)
                await trial.trial_command(message())
            self.client.get_trial.side_effect = InternalApiError("SECRET", code="LEGACY_TRIAL_RECONCILIATION_REQUIRED")
            await trial.trial_command(message())
            deliver.assert_not_awaited()
            self.client.activate_trial.assert_not_awaited()
            self.assertIn("прежний", self.render.await_args.args[1])

    async def test_group_wrong_chat_and_disabled_mode_never_call_api(self):
        await trial._show(message(kind="group"), 123, activate=True)
        await trial._show(message(chat_id=999), 123, activate=True)
        with patch.object(trial, "saas_client_mode_enabled", return_value=False):
            await trial._show(message(), 123, activate=True)
        self.client.get_telegram_dashboard.assert_not_awaited()
        self.client.activate_trial.assert_not_awaited()

    async def test_ready_rechecks_owner_before_material_fetch(self):
        self.client.get_trial.return_value = pending(status="READY", subscription_id="sub-1")
        # Run the real shared ownership loader, not a mocked delivery function.
        with patch.object(payment_return.internal_api_client, "get_telegram_dashboard", AsyncMock(return_value={"accesses": []})), \
             patch.object(payment_return.internal_api_client, "get_access_material", AsyncMock()) as material, \
             patch.object(payment_return, "_render_verified_subscription", AsyncMock()) as deliver:
            await trial.trial_command(message())
            material.assert_not_awaited()
            deliver.assert_not_awaited()

    async def test_ready_delivers_before_local_projection_and_tolerates_projection_failure(self):
        self.client.get_trial.return_value = pending(status="READY", subscription_id="sub-1")
        with patch.object(payment_return.internal_api_client, "get_telegram_dashboard", AsyncMock(return_value={
                 "user": {"user_id":"canonical-user", "tenant_id":payment_return.internal_api_client.tenant_id},
                 "accesses": [{"access_id": "access-1", "status": "ready", "authority":"managed", "enabled":True,
                               "desired_version":1, "subscription_url":"https://example.invalid/sub/fixture"}]})), \
             patch.object(payment_return.internal_api_client, "get_access_material", AsyncMock(return_value={
                 "access_id":"access-1", "node_id":"node-1", "desired_version":1,
                 "ready": True, "subscription_url": "https://example.invalid/sub/fixture"})), \
             patch.object(payment_return, "_render_verified_subscription", AsyncMock()) as deliver, \
             patch.object(payment_return, "materialize_ready_payment_return", AsyncMock(side_effect=InternalApiError("projection unavailable"))):
            await trial.trial_command(message())
            deliver.assert_awaited_once()
            self.assertEqual(deliver.await_args.args[1].access_id, "access-1")
            self.client.activate_trial.assert_not_awaited()
