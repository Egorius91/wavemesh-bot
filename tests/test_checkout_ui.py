from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, Router
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.handlers.user.payments import checkout as ui
from bot.services.checkout_contract import snapshot
from bot.services.checkout_coordinator import CheckoutCoordinator
from bot.services.internal_api import InternalApiError
from database.admin_provisioning import connection_scope
from database.checkout_intents import CheckoutJournal, ensure_schema
from database.checkout_ui import CheckoutUIJournal, ensure_schema as ensure_ui


OWNER = "owner-fixture-123"
TARIFF = {"tariff_id": "tariff-fixture-123", "name": "Original", "billing_mode": "RECURRING",
          "price_rub": 299, "duration_days": 30, "device_limit": 2, "traffic_limit_gb": None}


def wire(order="order-fixture-123", status="PENDING", mode="RECURRING"):
    return {"version": 1, "billingMode": mode, "provider": "YOOKASSA", "allowNewCreate": False, "orderId": order, "paymentStatus": status,
            "checkoutUrl": "https://checkout.invalid/original" if status == "PENDING" else None,
            "terms": {"tariffId": TARIFF["tariff_id"], "name": "Original", "amountRub": 299, "durationDays": 30,
                      "deviceLimit": 2, "trafficLimitGb": None, "purchaseKind": "NEW_ACCESS"},
            "entitlement": {"status": "PENDING"}, "access": None, "recurring": "PENDING"}


class CheckoutUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ui.db"
        conn = self.connect()
        ensure_schema(conn)
        ensure_ui(conn)
        conn.commit()
        conn.close()
        self.journal, self.views = CheckoutJournal(self.connect), CheckoutUIJournal(self.connect)
        self.owner, self.current, self.originals, self.posts, self.reject_posts = OWNER, None, {}, [], []
        self.fail_catalog, self.fail_current, self.lost = False, False, False
        self.tariffs = [deepcopy(TARIFF)]
        self.client = SimpleNamespace(base_url="https://fixture.invalid", tenant_id="tenant-fixture", token="fixture-only",
            get_telegram_dashboard=AsyncMock(side_effect=self.dashboard), get_current_checkout=AsyncMock(side_effect=self.read_current),
            get_checkout=AsyncMock(side_effect=self.read_original), list_tariffs=AsyncMock(side_effect=self.catalog),
            get_checkout_rejection=AsyncMock(return_value=False),
            create_order=AsyncMock(side_effect=self.create),
            reject_unadmitted_checkout=AsyncMock(side_effect=self.reject))
        self.runner = CheckoutCoordinator(self.client, self.journal)
        self.sent = AsyncMock()
        self.answer = AsyncMock()
        for target, value in [("coordinator", lambda: CheckoutCoordinator(self.client, CheckoutJournal(self.connect))),
                              ("ui_journal", lambda: CheckoutUIJournal(self.connect)), ("safe_edit_or_send", self.sent)]:
            p = patch.object(ui, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(CallbackQuery, "answer", self.answer)
        p.start()
        self.addCleanup(p.stop)
        self.bot = Bot(token="777000:"+"fixture"*8)
        self.dp = Dispatcher(disable_fsm=True)
        self.dp.include_router(ui.build_router())
        self.fallback = AsyncMock()
        async def fallback(event):
            await self.fallback(event)
        fallback_router = Router()
        fallback_router.callback_query.register(fallback)
        self.dp.include_router(fallback_router)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def asyncTearDown(self):
        await self.bot.session.close()
        self.tmp.cleanup()

    async def dashboard(self, actor):
        return {"user": {"user_id": self.owner}, "accesses": [{"access_id": "access-fixture-123"}]}

    async def catalog(self):
        if self.fail_catalog:
            raise InternalApiError("fixture-private-provider-error")
        return self.tariffs

    async def read_current(self, owner):
        if self.fail_current:
            raise InternalApiError("fixture-private-provider-error")
        return snapshot(self.current) if self.current else None

    async def read_original(self, owner, key):
        if key not in self.originals:
            raise InternalApiError("missing", status=404, code="CHECKOUT_NOT_FOUND")
        return snapshot(self.originals[key])

    async def create(self, **payload):
        self.posts.append(payload)
        self.current = wire("order-fixture-"+str(len(self.posts)), mode=payload["billing_mode"])
        if payload.get("access_id"):
            self.current["terms"]["purchaseKind"] = "RENEWAL"
        self.originals[payload["idempotency_key"]] = self.current
        row = self.journal.active(123, connection_scope(self.client), OWNER)
        self.assertEqual(row["phase"], "DISPATCHED")
        self.assertIsNotNone(row["confirmed_at"])
        if self.lost:
            raise InternalApiError("timeout", code="INTERNAL_API_TIMEOUT")
        return {"order_id": self.current["orderId"], "checkout_url": self.current["checkoutUrl"], "status": "pending"}

    async def reject(self, **payload):
        self.reject_posts.append(payload)
        self.client.get_checkout_rejection.return_value = True
        return True

    async def feed(self, data="buy_key", *, actor=123, chat=123, chat_type="private", message_id=10, callback_id="tap-one", inline=None):
        message = Message(message_id=message_id, date=datetime.now(timezone.utc), chat=Chat(id=chat, type=chat_type),
                          from_user=User(id=777000, is_bot=True, first_name="Bot"), text="Fixture")
        callback = CallbackQuery(id=callback_id, from_user=User(id=actor, is_bot=False, first_name="Fixture"),
                                 chat_instance="fixture-chat", message=message, data=data, inline_message_id=inline)
        await self.dp.feed_update(self.bot, Update(update_id=1, callback_query=callback).as_(self.bot))

    def last(self):
        call = self.sent.await_args
        return call.args[1], [b for row in call.kwargs["reply_markup"].inline_keyboard for b in row]

    def callback(self, prefix):
        return next(b.callback_data for b in self.last()[1] if b.callback_data and b.callback_data.startswith(prefix))

    async def prepared(self):
        await self.feed()
        choice = self.callback("wmco_select:")
        await self.feed(choice)
        return choice, self.callback("wmco_confirm:")

    async def test_dispatcher_requires_separate_explicit_consent(self):
        _, confirm = await self.prepared()
        self.assertEqual(self.posts, [])
        text, _ = self.last()
        self.assertIn("299 ₽ каждые 30 дней", text)
        self.assertIn("сохранение способа оплаты", text)
        self.assertIn("Устройств: 2", text)
        await self.feed(confirm)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]["recurring_consent"]["amountRub"], 299)
        self.fallback.assert_not_awaited()

    async def test_repeated_taps_restart_and_lost_response_stay_original(self):
        choice, confirm = await self.prepared()
        self.lost = True
        await self.feed(confirm)
        await self.feed(confirm, callback_id="another-tap")
        await self.feed(choice, callback_id="old-message-tap")
        await self.feed("buy_key")
        self.assertEqual(len(self.posts), 1)
        self.assertNotIn("wmco_confirm:", str(self.last()[1]))

    async def test_lost_rejection_proof_restores_ui_without_reusing_consent(self):
        choice, confirm = await self.prepared()
        async def lost_rejection(**payload):
            self.posts.append(payload)
            self.current = wire("competing-order-123", "PAID")
            raise InternalApiError("timeout", code="INTERNAL_API_TIMEOUT")
        self.client.create_order.side_effect = lost_rejection
        self.client.get_checkout_rejection.return_value = True
        await self.feed(confirm)
        self.assertNotIn("Статус оплаты пока", self.last()[0])
        self.assertIn("Оплата подтверждена", self.last()[0])
        await self.feed(choice)
        await self.feed(confirm)
        self.assertEqual(len(self.posts), 1)
        await self.feed(self.callback("wmco_next:"))
        await self.feed(self.callback("wmco_select:"))
        self.assertIn("Подтвердите подписку", self.last()[0])
        self.assertEqual(len(self.posts), 1)
        self.client.create_order.side_effect = self.create
        await self.feed(self.callback("wmco_confirm:"))
        self.assertEqual(len(self.posts), 2)
        self.assertNotEqual(self.posts[0]["idempotency_key"], self.posts[1]["idempotency_key"])

    async def test_recovery_precedes_broken_catalog_and_new_tariff(self):
        _, confirm = await self.prepared()
        await self.feed(confirm)
        self.fail_catalog = True
        await self.feed("saas_new_checkout:changed-tariff-123")
        self.assertIn("299 ₽ за 30 дней", self.last()[0])
        self.assertNotIn("fixture-private", self.last()[0])
        self.assertEqual(len(self.posts), 1)

    async def test_lost_confirmation_refusal_requires_fresh_terms_and_new_explicit_confirm(self):
        self.tariffs[0]["billing_mode"] = "ONE_TIME"
        choice, confirm = await self.prepared()
        async def refused(**payload):
            self.posts.append(payload)
            raise InternalApiError("timeout", code="INTERNAL_API_TIMEOUT")
        self.client.create_order.side_effect = refused
        self.client.get_checkout_rejection.return_value = True
        await self.feed(confirm)
        self.assertIn("Покупка не создана", self.last()[0])
        await self.feed(choice)
        await self.feed(confirm)
        self.assertEqual(len(self.posts), 1)
        self.tariffs[0]["price_rub"] = 499
        await self.feed(self.callback("buy_key"))
        await self.feed(self.callback("wmco_select:"))
        self.assertIn("499 ₽", self.last()[0])
        self.assertEqual(len(self.posts), 1)
        self.client.create_order.side_effect = self.create
        await self.feed(self.callback("wmco_confirm:"))
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.posts[1]["confirmed_terms"]["amountRub"], 499)
        self.assertNotEqual(self.posts[0]["idempotency_key"], self.posts[1]["idempotency_key"])

    async def test_refused_renewal_returns_to_access_selection_instead_of_new_access(self):
        self.tariffs[0]["billing_mode"] = "ONE_TIME"
        context = ({"display_name": "Key"}, {"user_id": OWNER, "access": {"access_id": "access-fixture-123"}}, {})
        with patch("bot.handlers.user.payments.saas._load_checkout_context", AsyncMock(return_value=context)):
            await self.feed("key_renew:7")
            await self.feed(self.callback("wmco_select:"))
        self.client.create_order.side_effect = InternalApiError("timeout", code="INTERNAL_API_TIMEOUT")
        self.client.get_checkout_rejection.return_value = True
        await self.feed(self.callback("wmco_confirm:"))
        self.assertIn("Покупка не создана", self.last()[0])
        self.assertTrue(any(b.text == "Выбрать доступ для продления" and b.callback_data == "my_keys" for b in self.last()[1]))
        self.assertFalse(any(b.callback_data == "buy_key" for b in self.last()[1]))

    async def test_remote_web_checkout_without_local_key_is_discovered(self):
        self.current = wire()
        self.fail_catalog = True
        await self.feed("buy_key")
        self.assertIn("Ожидаем подтверждения", self.last()[0])
        self.assertEqual(self.posts, [])
        self.assertIsNone(self.journal.active(123, connection_scope(self.client), OWNER))

    async def test_payment_url_requires_fresh_same_owner_and_order(self):
        self.current = wire()
        await self.feed("buy_key")
        pay = self.callback("wmco_pay:")
        self.assertFalse(any(b.url for b in self.last()[1]))
        await self.feed(pay)
        self.assertEqual(next(b.url for b in self.last()[1] if b.url), "https://checkout.invalid/original")
        self.current = wire("changed-order-123")
        await self.feed(pay)
        self.assertFalse(any(b.url for b in self.last()[1]))
        self.owner = "changed-owner-123"
        await self.feed(pay)
        self.assertFalse(any(b.url for b in self.last()[1]))
        self.assertIn("Статус оплаты пока", self.last()[0])

    async def test_paid_configuration_and_recurring_are_distinct(self):
        self.current = wire(status="PAID")
        await self.feed("buy_key")
        text = self.last()[0]
        self.assertIn("Оплата подтверждена", text)
        self.assertIn("Доступ подготавливается", text)
        self.assertNotIn("Автопродление включено", text)

    async def test_explicit_next_purchase_has_new_consent_and_predecessor(self):
        first_choice, confirm = await self.prepared()
        await self.feed(confirm)
        first_order = self.current["orderId"]
        self.current.update(paymentStatus="PAID", checkoutUrl=None)
        await self.feed("wmco_current")
        await self.feed(self.callback("wmco_next:"))
        await self.feed(self.callback("wmco_select:"))
        self.assertEqual(len(self.posts), 1)
        await self.feed(self.callback("wmco_confirm:"))
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.posts[1]["expected_previous_order_id"], first_order)
        await self.feed(first_choice)
        self.assertEqual(len(self.posts), 2)

    async def test_stale_next_purchase_does_not_rebase(self):
        self.current = wire(status="PAID")
        await self.feed("buy_key")
        await self.feed(self.callback("wmco_next:"))
        select = self.callback("wmco_select:")
        self.current = wire("another-order-123")
        await self.feed(select)
        self.assertEqual(self.posts, [])
        self.assertNotIn("wmco_confirm:", str(self.last()[1]))

    async def test_unknown_dispatch_blocks_new_consent_even_if_current_empty(self):
        _, confirm = await self.prepared()
        row = self.journal.active(123, connection_scope(self.client), OWNER)
        self.journal.claim_confirmed(row["id"], 123, connection_scope(self.client), OWNER)
        await self.feed("buy_key")
        self.assertIn("Статус оплаты пока", self.last()[0])
        self.assertNotIn("wmco_next:", str(self.last()[1]))
        await self.feed(confirm)
        self.assertEqual(self.posts, [])

    async def test_unknown_dispatch_exposes_explicit_reject_and_old_confirm_stays_dead(self):
        choice, confirm = await self.prepared()
        row = self.journal.active(123, connection_scope(self.client), OWNER)
        self.journal.claim_confirmed(row["id"], 123, connection_scope(self.client), OWNER)
        await self.feed("buy_key")
        text, buttons = self.last()
        self.assertIn("Если заказ по этой попытке не появился", text)
        reject = self.callback("wmco_reject:")
        self.assertEqual(next(b.text for b in buttons if b.callback_data == reject), "Завершить попытку")
        await self.feed(reject)
        self.assertIn("Покупка не создана", self.last()[0])
        self.assertEqual(len(self.reject_posts), 1)
        self.assertEqual(self.reject_posts[0]["idempotency_key"], row["request_key"])
        self.assertEqual(self.reject_posts[0]["original_payload"], json.loads(row["payload"]))
        await self.feed(reject, callback_id="duplicate-tap")
        await self.feed(confirm, callback_id="late-confirm")
        await self.feed(choice, callback_id="late-choice")
        self.assertEqual(len(self.reject_posts), 1)
        self.assertEqual(self.posts, [])
        await self.feed("buy_key")
        self.assertIn("Выберите тариф", self.last()[0])

    async def test_reject_response_without_get_proof_keeps_unknown_and_restricts_callbacks(self):
        _, _ = await self.prepared()
        row = self.journal.active(123, connection_scope(self.client), OWNER)
        self.journal.claim_confirmed(row["id"], 123, connection_scope(self.client), OWNER)
        self.client.reject_unadmitted_checkout.side_effect = AsyncMock(return_value=True)
        await self.feed("buy_key")
        reject = self.callback("wmco_reject:")
        for kw in ({"actor": 456, "chat": 456}, {"chat": -123, "chat_type": "group"}, {"inline": "inline-fixture"}):
            await self.feed(reject, **kw)
        self.client.reject_unadmitted_checkout.assert_not_awaited()
        await self.feed(reject)
        self.assertIn("Статус оплаты пока", self.last()[0])
        self.assertEqual(self.journal.active(123, connection_scope(self.client), OWNER)["phase"], "DISPATCHED")
        self.client.get_checkout_rejection.return_value = True
        await self.feed("wmco_current")
        self.assertIn("Покупка не создана", self.last()[0])

    async def test_late_order_removes_reject_action_without_post(self):
        _, _ = await self.prepared()
        row = self.journal.active(123, connection_scope(self.client), OWNER)
        self.journal.claim_confirmed(row["id"], 123, connection_scope(self.client), OWNER)
        await self.feed("buy_key")
        reject = self.callback("wmco_reject:")
        self.current = wire()
        self.originals[row["request_key"]] = self.current
        await self.feed(reject)
        self.assertIn("Ожидаем подтверждения", self.last()[0])
        self.assertNotIn("wmco_reject:", str(self.last()[1]))
        self.assertEqual(self.reject_posts, [])

    async def test_local_cancel_does_not_reuse_old_confirmation(self):
        choice, confirm = await self.prepared()
        await self.feed(self.callback("wmco_cancel:"))
        self.assertIn("Запрос на оплату не отправлялся", self.last()[0])
        await self.feed(confirm)
        await self.feed(choice)
        self.assertEqual(self.posts, [])

    async def test_all_legacy_recurring_surfaces_intercepted(self):
        context = ({"display_name": "Key"}, {"user_id": OWNER, "access": {"access_id": "access-fixture-123"}}, {})
        with patch("bot.handlers.user.payments.saas._load_checkout_context", AsyncMock(return_value=context)):
            for data in ("saas_new_checkout:"+TARIFF["tariff_id"], "saas_np:yk:"+TARIFF["tariff_id"],
                         "saas_checkout:7:"+TARIFF["tariff_id"], "saas_rp:7:yk:"+TARIFF["tariff_id"]):
                await self.feed(data)
                self.assertIn("Подтвердите подписку", self.last()[0])
                await self.feed(self.callback("wmco_cancel:"))
        self.assertEqual(self.posts, [])
        self.fallback.assert_not_awaited()

    async def test_platega_recurring_callback_cannot_fall_back_to_yookassa(self):
        await self.feed("saas_np:pg:"+TARIFF["tariff_id"])
        self.assertEqual(self.posts, [])
        self.assertIn("Заново выберите тариф", self.last()[0])

    async def test_renewal_preserves_selected_access(self):
        context = ({"display_name": "Key"}, {"user_id": OWNER, "access": {"access_id": "access-fixture-123"}}, {})
        with patch("bot.handlers.user.payments.saas._load_checkout_context", AsyncMock(return_value=context)):
            await self.feed("key_renew:7")
            await self.feed(self.callback("wmco_select:"))
            self.assertIn("Продление выбранного доступа", self.last()[0])
            await self.feed(self.callback("wmco_confirm:"))
        self.assertEqual(self.posts[0]["access_id"], "access-fixture-123")

    async def test_one_time_keeps_saas_default_provider_routing(self):
        self.tariffs[0]["billing_mode"] = "ONE_TIME"
        _, confirm = await self.prepared()
        self.assertEqual(self.posts, [])
        self.assertIn("Подтвердите разовую оплату", self.last()[0])
        self.assertIn("299 ₽ за 30 дней без автопродления", self.last()[0])
        self.assertNotIn("сохранение способа оплаты", self.last()[0])
        self.assertEqual(next(b.text for b in self.last()[1] if b.callback_data == confirm), "Подтвердить и оплатить")
        self.lost = True
        await self.feed(confirm)
        await self.feed(confirm, callback_id="another-tap")
        self.assertEqual(self.posts[0]["billing_mode"], "ONE_TIME")
        self.assertNotIn("provider", self.posts[0])
        self.assertNotIn("recurring_consent", self.posts[0])
        self.assertEqual(self.posts[0]["confirmed_terms"]["amountRub"], 299)
        self.assertEqual(len(self.posts), 1)

    async def test_one_time_next_purchase_preserves_explicit_predecessor(self):
        self.tariffs[0]["billing_mode"] = "ONE_TIME"
        choice, confirm = await self.prepared()
        await self.feed(confirm)
        original = self.current["orderId"]
        self.current.update(paymentStatus="PAID", checkoutUrl=None)
        await self.feed("wmco_current")
        self.assertIn("Разовая оплата без автопродления", self.last()[0])
        self.assertNotIn("Состояние автопродления", self.last()[0])
        await self.feed(self.callback("wmco_next:"))
        await self.feed(self.callback("wmco_select:"))
        self.assertEqual(len(self.posts), 1)
        await self.feed(self.callback("wmco_confirm:"))
        self.assertEqual(self.posts[1]["expected_previous_order_id"], original)
        await self.feed(choice)
        self.assertEqual(len(self.posts), 2)

    async def test_all_legacy_one_time_callbacks_prepare_without_direct_post(self):
        self.tariffs[0]["billing_mode"] = "ONE_TIME"
        context = ({"display_name": "Key"}, {"user_id": OWNER, "access": {"access_id": "access-fixture-123"}}, {})
        with patch("bot.handlers.user.payments.saas._load_checkout_context", AsyncMock(return_value=context)):
            for data in ("saas_new_checkout:"+TARIFF["tariff_id"], "saas_np:pg:"+TARIFF["tariff_id"],
                         "saas_checkout:7:"+TARIFF["tariff_id"], "saas_rp:7:yk:"+TARIFF["tariff_id"]):
                await self.feed(data)
                self.assertIn("Подтвердите разовую оплату", self.last()[0])
                self.assertEqual(self.posts, [])
                await self.feed(self.callback("wmco_cancel:"))
        self.fallback.assert_not_awaited()

    async def test_group_wrong_actor_and_inline_updates_do_nothing(self):
        for kw in ({"chat": -123, "chat_type": "group"}, {"actor": 456}, {"inline": "inline-fixture"}):
            await self.feed(**kw)
            await self.feed("wmco_current", **kw)
        self.client.get_telegram_dashboard.assert_not_awaited()
        self.sent.assert_not_awaited()
        self.assertEqual(self.posts, [])

    async def test_forged_ui_reference_fails_without_exposing_terms(self):
        await self.feed("buy_key")
        choice = self.callback("wmco_select:")
        await self.feed(choice, actor=456, chat=456)
        self.assertIn("Статус оплаты пока", self.last()[0])
        self.assertNotIn("299", self.last()[0])
        self.assertEqual(self.posts, [])

    async def test_discovery_outage_has_safe_retry_and_no_catalog(self):
        self.fail_current = True
        await self.feed("buy_key")
        self.assertIn("Статус оплаты пока", self.last()[0])
        self.assertNotIn("fixture-private", self.last()[0])
        self.client.list_tariffs.assert_not_awaited()
        self.assertEqual(self.callback("wmco_current"), "wmco_current")

    async def test_ui_references_fit_telegram_and_store_no_urls(self):
        _, confirm = await self.prepared()
        await self.feed(confirm)
        await self.feed(self.callback("wmco_pay:"))
        for call in self.sent.await_args_list:
            for row in call.kwargs["reply_markup"].inline_keyboard:
                for button in row:
                    if button.callback_data:
                        self.assertLessEqual(len(button.callback_data.encode()), 64)
        conn = self.connect()
        try:
            dumped = "\n".join(conn.iterdump())
        finally:
            conn.close()
        self.assertNotIn("https://", dumped)
        self.assertNotIn("fixture-only", dumped)


if __name__ == "__main__":
    unittest.main()
