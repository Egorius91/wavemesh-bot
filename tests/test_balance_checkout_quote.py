"""Full-balance authorization through real dispatch; all business effects are mocked."""
import asyncio
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User


ACTOR, OWNER, TARIFF, KEY = 202, 5, 7, 17


class BalanceCheckoutQuoteTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict('os.environ', {'WAVEMESH_SAAS_CLIENT_MODE': 'false'}))
        self.stack.enter_context(patch('database.connection.get_db', side_effect=AssertionError('unexpected DB access')))
        self.tariff = {'id': TARIFF, 'name': 'Fixture', 'price_rub': 299, 'price_cents': 999,
                       'price_stars': 123, 'duration_days': 30, 'traffic_limit_gb': 10, 'is_active': 1}
        self.key = {'id': KEY, 'tariff_id': TARIFF, 'display_name': 'Fixture key'}
        self.balance = 49900
        self.available = True
        self.renewable = True
        fixtures = {
            'get_tariff_by_id': MagicMock(side_effect=lambda _: dict(self.tariff)),
            'get_user_balance': MagicMock(side_effect=lambda _: self.balance),
            'get_user_internal_id': MagicMock(return_value=OWNER),
            'get_or_create_user': MagicMock(return_value=({'id': OWNER}, False)),
            'get_key_details_for_user': MagicMock(side_effect=lambda *_: self.key),
            'is_referral_enabled': MagicMock(side_effect=lambda: self.available),
            'get_referral_reward_type': MagicMock(return_value='balance'),
            'is_cards_enabled': MagicMock(return_value=True),
            'is_yookassa_qr_configured': MagicMock(return_value=True),
            'get_setting': MagicMock(return_value='0'),
            'deduct_from_balance': MagicMock(return_value=True),
            'create_initial_vpn_key': MagicMock(return_value=27),
            'create_pending_order': MagicMock(return_value=(12, 'fixture-order')),
            'complete_order': MagicMock(return_value=True),
            'update_payment_key_id': MagicMock(return_value=True),
            'find_order_by_order_id': MagicMock(return_value={'order_id': 'fixture-order', 'vpn_key_id': KEY}),
        }
        self.fx = {name: self.stack.enter_context(patch('database.requests.' + name, value))
                   for name, value in fixtures.items()}
        self.stack.enter_context(patch('bot.utils.groups.get_tariffs_for_renewal',
            side_effect=lambda _: [dict(self.tariff)] if self.renewable else []))
        self.stack.enter_context(patch('bot.services.user_locks.user_locks', defaultdict(asyncio.Lock)))
        self.renew = self.stack.enter_context(patch('bot.services.key_lifecycle.renew_key_access',
            AsyncMock(return_value={'db_updated': True, 'panel_synced': True})))
        self.stack.enter_context(patch('bot.services.notifications.notify_admins_payment', AsyncMock()))
        self.finalize = self.stack.enter_context(patch('bot.handlers.user.payments.base.finalize_payment_ui', AsyncMock()))
        self.answer = self.stack.enter_context(patch.object(CallbackQuery, 'answer', AsyncMock()))
        path = Path(__file__).resolve().parents[1] / 'bot/handlers/user/payments/balance.py'
        spec = importlib.util.spec_from_file_location('_balance_quote_fixture', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.render = self.stack.enter_context(patch.object(self.module, 'safe_edit_or_send', AsyncMock()))
        self.bot = Bot(token='777000:' + 'fixture' * 8)
        self.addAsyncCleanup(self.bot.session.close)
        self.network = self.stack.enter_context(patch.object(self.bot.session, 'make_request',
            AsyncMock(side_effect=AssertionError('unexpected Telegram network'))))
        self.storage = MemoryStorage()
        self.addAsyncCleanup(self.storage.close)
        self.dp = Dispatcher(storage=self.storage)
        self.dp.include_router(self.module.router)
        self.state = FSMContext(storage=self.storage,
            key=StorageKey(bot_id=self.bot.id, chat_id=ACTOR, user_id=ACTOR))
        self.sequence = 0

    async def feed(self, data, actor=ACTOR):
        self.sequence += 1
        event = CallbackQuery(id='fixture-' + str(self.sequence), chat_instance='fixture-chat', data=data,
            from_user=User(id=actor, is_bot=False, first_name='Fixture actor'),
            message=Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=actor, type='private'),
                from_user=User(id=self.bot.id, is_bot=True, first_name='Fixture bot')))
        return await self.dp.feed_update(self.bot, Update(update_id=self.sequence, callback_query=event))

    async def quote(self, key=None):
        await self.feed(f'balance_pay:{TARIFF}' + (f':{key}' if key else ''))
        markup = self.render.await_args.kwargs['reply_markup']
        return next(button.callback_data for row in markup.inline_keyboard for button in row
                    if (button.callback_data or '').startswith('pay_with_balance:'))

    def assert_no_money_or_grant(self):
        self.fx['deduct_from_balance'].assert_not_called()
        self.fx['create_initial_vpn_key'].assert_not_called()
        self.renew.assert_not_awaited()
        self.fx['create_pending_order'].assert_not_called()
        self.network.assert_not_awaited()

    def reset_business(self):
        for name in ('deduct_from_balance', 'create_initial_vpn_key', 'create_pending_order'):
            self.fx[name].reset_mock()
        self.renew.reset_mock()

    async def test_missing_and_incomplete_fsm_never_grant_a_free_tariff(self):
        for data in ({}, {'tariff_id': TARIFF}, {'tariff_price_cents': 29900},
                     {'tariff_id': TARIFF, 'tariff_price_cents': 29900, 'balance_to_deduct': 29900}):
            with self.subTest(data=data):
                await self.state.clear()
                await self.state.update_data(**data)
                self.reset_business()
                await self.feed(f'pay_with_balance:{TARIFF}')
                self.assert_no_money_or_grant()

    async def test_lost_fsm_after_restart_refuses_the_old_button(self):
        button = await self.quote()
        await self.state.clear()
        await self.feed(button)
        self.assert_no_money_or_grant()

    async def test_malformed_and_legacy_buttons_do_not_consume_current_quote(self):
        button = await self.quote()
        for suffix in ('7', '7:17', '0' * 15, 'g' * 16, '0' * 17,
                       button.split(':')[1] + ':7', button.split(':')[1] + '\n'):
            with self.subTest(suffix=suffix):
                await self.feed('pay_with_balance:' + suffix)
                self.assert_no_money_or_grant()
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)

    async def test_other_actor_cannot_use_button_or_copied_quote(self):
        button = await self.quote()
        other = ACTOR + 1
        self.fx['get_user_internal_id'].side_effect = lambda actor: OWNER if actor == ACTOR else OWNER + 1
        await self.feed(button, actor=other)
        self.assert_no_money_or_grant()
        other_state = FSMContext(storage=self.storage,
            key=StorageKey(bot_id=self.bot.id, chat_id=other, user_id=other))
        await other_state.update_data(**deepcopy(await self.state.get_data()))
        await self.feed(button, actor=other)
        self.assert_no_money_or_grant()
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)

    async def test_invalid_quote_types_cannot_reach_debit(self):
        for section, field, value in ((None, 'owner_id', True), (None, 'owner_id', str(OWNER)),
                (None, 'key_id', True), ('terms', 'tariff_id', str(TARIFF)),
                ('terms', 'price_cents', 0), ('terms', 'price_cents', -1),
                ('terms', 'price_cents', '29900')):
            with self.subTest(field=field, value=value):
                button = await self.quote()
                data = deepcopy(await self.state.get_data())
                target = data['balance_quote'] if section is None else data['balance_quote'][section]
                target[field] = value
                await self.state.update_data(balance_quote=data['balance_quote'])
                await self.feed(button)
                self.assert_no_money_or_grant()

    async def test_feature_and_renewal_eligibility_are_rechecked(self):
        for restriction in ('feature_off', 'other_reward', 'renewal_group'):
            with self.subTest(restriction=restriction):
                self.available, self.renewable = True, True
                self.fx['get_referral_reward_type'].return_value = 'balance'
                button = await self.quote(KEY)
                if restriction == 'feature_off':
                    self.available = False
                elif restriction == 'other_reward':
                    self.fx['get_referral_reward_type'].return_value = 'days'
                else:
                    self.renewable = False
                await self.feed(button)
                self.assert_no_money_or_grant()

    async def test_invalid_or_fractional_kopecks_do_not_issue_offer(self):
        for price in (0, -1, 'NaN', 'Infinity', '1.001', 'not-a-price'):
            with self.subTest(price=price):
                await self.state.clear()
                self.render.reset_mock()
                self.tariff['price_rub'] = price
                await self.feed(f'balance_pay:{TARIFF}')
                self.assertIsNone((await self.state.get_data()).get('balance_quote'))
                self.render.assert_not_awaited()
                self.assert_no_money_or_grant()

    async def test_new_screen_replaces_old_quote_and_only_current_quote_can_pay(self):
        old = await self.quote()
        current = await self.quote()
        self.assertNotEqual(old, current)
        self.assertRegex(current, r'^pay_with_balance:[a-f0-9]{16}$')
        self.assertLessEqual(len(current.encode()), 64)
        await self.feed(old)
        self.assert_no_money_or_grant()
        await self.feed(current)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)
        self.fx['create_initial_vpn_key'].assert_called_once()

    async def test_concurrent_screens_leave_a_payable_visible_button(self):
        entered, release = asyncio.Event(), asyncio.Event()
        visible, count = None, 0

        async def render(*args, **kwargs):
            nonlocal visible, count
            count += 1
            if count == 1:
                entered.set()
                await release.wait()
            visible = next(button.callback_data for row in kwargs['reply_markup'].inline_keyboard
                           for button in row if (button.callback_data or '').startswith('pay_with_balance:'))

        self.render.side_effect = render
        callback = CallbackQuery(id='screen-fixture', chat_instance='fixture-chat', data=f'balance_pay:{TARIFF}',
            from_user=User(id=ACTOR, is_bot=False, first_name='Fixture actor'),
            message=Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=ACTOR, type='private')))
        first = asyncio.create_task(self.module._show_balance_payment_screen(callback, self.state, TARIFF, OWNER))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 10)
            second = asyncio.create_task(self.module._show_balance_payment_screen(callback, self.state, TARIFF, OWNER))
            await asyncio.sleep(0)
        finally:
            release.set()
            await first
            if second is not None:
                await second
        self.assertEqual(count, 2)
        self.assertEqual(visible, 'pay_with_balance:' + (await self.state.get_data())['balance_quote']['token'])
        await self.feed(visible)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)

    async def test_current_offer_changes_require_reselection_before_debit(self):
        original = dict(self.tariff)
        for field, value in (('price_rub', 399), ('duration_days', 90), ('traffic_limit_gb', 100), ('is_active', 0)):
            with self.subTest(field=field):
                self.tariff = dict(original)
                button = await self.quote()
                self.tariff[field] = value
                self.reset_business()
                await self.feed(button)
                self.assert_no_money_or_grant()

    async def test_deleted_or_foreign_renewal_target_cannot_spend(self):
        button = await self.quote(KEY)
        self.key = None
        await self.feed(button)
        self.assert_no_money_or_grant()

    async def test_conditional_debit_false_never_provisions(self):
        button = await self.quote()
        self.fx['deduct_from_balance'].return_value = False
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)
        self.fx['create_initial_vpn_key'].assert_not_called()
        self.renew.assert_not_awaited()
        self.fx['create_pending_order'].assert_not_called()

    async def test_insufficient_current_balance_never_debits(self):
        button = await self.quote()
        self.balance = 29899
        await self.feed(button)
        self.assert_no_money_or_grant()

    async def test_normal_new_purchase_charges_exact_rub_not_crypto_price(self):
        button = await self.quote()
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)
        self.fx['create_initial_vpn_key'].assert_called_once_with(OWNER, TARIFF, 30, traffic_limit=10 * 1024 ** 3)
        self.finalize.assert_awaited_once()
        self.network.assert_not_awaited()

    async def test_exact_kopecks_are_displayed_and_charged_without_float_truncation(self):
        self.tariff['price_rub'] = 1.15
        button = await self.quote()
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 115)

    async def test_owned_renewal_panel_failure_does_not_repeat_debit_or_renewal(self):
        button = await self.quote(KEY)
        self.renew.return_value = {'db_updated': True, 'panel_synced': False}
        await self.feed(button)
        await self.feed(button)
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)
        self.renew.assert_awaited_once_with(KEY, 30, reset_traffic=True, tariff_id=TARIFF)
        self.assertTrue(any('панель' in str(call.args) for call in self.render.await_args_list))

    async def test_concurrent_duplicate_quote_only_charges_and_renews_once(self):
        button = await self.quote(KEY)
        entered, release = asyncio.Event(), asyncio.Event()

        async def renew(*args, **kwargs):
            entered.set()
            await release.wait()
            return {'db_updated': True, 'panel_synced': True}

        self.renew.side_effect = renew
        first = asyncio.create_task(self.feed(button))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 10)
            second = asyncio.create_task(self.feed(button))
            await asyncio.sleep(0)
        finally:
            release.set()
            await first
            if second is not None:
                await second
        self.fx['deduct_from_balance'].assert_called_once_with(OWNER, 29900)
        self.assertEqual(self.renew.await_count, 1)

    async def test_partial_card_and_qr_callbacks_and_amounts_are_preserved(self):
        self.balance = 10000
        await self.feed(f'balance_pay:{TARIFF}')
        buttons = [button.callback_data for row in self.render.await_args.kwargs['reply_markup'].inline_keyboard
                   for button in row]
        self.assertEqual(buttons, [f'pay_card_balance:{TARIFF}:0', f'pay_qr_balance:{TARIFF}:0', 'buy_key'])
        data = await self.state.get_data()
        self.assertEqual(data['balance_to_deduct'], 10000)
        self.assertEqual(data['tariff_price_cents'], 29900)
        self.assertEqual(data['tariff_id'], TARIFF)
        self.assert_no_money_or_grant()
