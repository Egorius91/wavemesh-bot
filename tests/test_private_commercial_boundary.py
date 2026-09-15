import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Message, Update, User

from bot.middlewares.bot_blocked import BotBlockedResetMiddleware
from bot.middlewares.internal_api_shadow import InternalApiDashboardShadowMiddleware
from bot.middlewares.private_commercial import install_private_commercial_boundary
from bot.services.private_chat import private_actor_id, private_message_for
from bot.handlers.user.payments import payment_return
from bot.services.internal_api import InternalApiError


def user(user_id=123, *, is_bot=False):
    return User(id=user_id, is_bot=is_bot, first_name="Fixture")


def message(*, chat_id=123, kind="private", actor=123, text="/buy", **fields):
    return Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=chat_id,type=kind),
                   from_user=user(actor) if actor is not None else None, text=text, **fields)


def callback(*, chat_id=123, kind="private", actor=123, data="saas_new_checkout:tariff-1", **fields):
    return CallbackQuery(id="fixture-callback", chat_instance="fixture-chat", from_user=user(actor),
                         message=message(chat_id=chat_id,kind=kind,actor=777000),data=data, **fields)


def denied_messages():
    return [message(chat_id=-1,kind=kind) for kind in ("group","supergroup","channel")] + [
        message(chat_id=124), message(actor=None),
        message(sender_chat=Chat(id=-1,type="channel")),
        message(business_connection_id="business-fixture"),
        message().model_copy(update={"from_user":user(123,is_bot=True)}),
    ]


def denied_callbacks():
    return [callback(chat_id=-1,kind=kind) for kind in ("group","supergroup","channel")] + [
        callback(chat_id=124), callback().model_copy(update={"message":None}),
        callback(inline_message_id="inline-fixture"),
        callback().model_copy(update={"message":InaccessibleMessage(chat=Chat(id=123,type="private"),message_id=1,date=0)}),
        callback().model_copy(update={"message":message().model_copy(update={"date":datetime.fromtimestamp(0,timezone.utc)})}),
        callback().model_copy(update={"from_user":None}),
        callback().model_copy(update={"from_user":user(123,is_bot=True)}),
        callback().model_copy(update={"message":message(business_connection_id="business-fixture")}),
    ]


class PrivateActorTests(TestCase):
    def test_private_actor_and_outgoing_delivery_target_are_distinct(self):
        self.assertEqual(private_actor_id(message()),123)
        self.assertEqual(private_actor_id(callback()),123)
        outgoing = message(actor=777000).model_copy(update={"from_user":user(777000,is_bot=True)})
        self.assertIsNone(private_actor_id(outgoing))
        self.assertIs(private_message_for(outgoing,123),outgoing)

    def test_invalid_actor_and_target_matrix_is_denied(self):
        for event in denied_messages()+denied_callbacks()+[None,object()]:
            with self.subTest(event_type=type(event).__name__):
                self.assertIsNone(private_actor_id(event))
        for target in (message(chat_id=124),message(chat_id=-1,kind="group"),None,
                       callback(actor=124),callback(inline_message_id="inline")):
            self.assertIsNone(private_message_for(target,123))
        for owner in (None,0,-1,True,"123"):
            self.assertIsNone(private_message_for(message(),owner))

    def test_production_boundary_is_installed_before_side_effect_middlewares(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="main")
        install = [n for n in ast.walk(main) if isinstance(n,ast.Call)
                   and isinstance(n.func,ast.Name) and n.func.id=="install_private_commercial_boundary"]
        side_effects = [n.lineno for n in ast.walk(main) if isinstance(n,ast.Call)
                        and isinstance(n.func,ast.Attribute) and n.func.attr in {"outer_middleware","include_router"}]
        self.assertEqual(len(install),1)
        self.assertLess(install[0].lineno,min(side_effects))


class DispatcherBoundaryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Bot(token="777000:"+"fixture"*8)
        self.addAsyncCleanup(self.bot.session.close)
        self.dp = Dispatcher(disable_fsm=True)
        install_private_commercial_boundary(self.dp)
        self.dp.message.outer_middleware(BotBlockedResetMiddleware())
        self.dp.callback_query.outer_middleware(BotBlockedResetMiddleware())
        self.dp.message.outer_middleware(InternalApiDashboardShadowMiddleware())
        self.dp.callback_query.outer_middleware(InternalApiDashboardShadowMiddleware())
        self.handler = AsyncMock(return_value="handled")
        async def handle(event):
            return await self.handler(event)
        self.dp.message.register(handle)
        self.dp.callback_query.register(handle)
        self.mode = patch("bot.middlewares.private_commercial.saas_client_mode_enabled",return_value=True).start()
        self.db = patch("bot.middlewares.bot_blocked.mark_user_bot_unblocked",MagicMock()).start()
        self.shadow = patch("bot.middlewares.internal_api_shadow.schedule_dashboard_shadow_read",MagicMock()).start()
        self.answer = patch.object(CallbackQuery,"answer",AsyncMock()).start()
        self.addCleanup(patch.stopall)

    async def feed(self,event):
        # model_construct retains intentionally absent actors for negative tests.
        key = "callback_query" if isinstance(event,CallbackQuery) else "message"
        update = Update.model_construct(update_id=1,**{key:event}).as_(self.bot)
        return await self.dp.feed_update(self.bot,update)

    async def test_invalid_messages_stop_before_db_upstream_or_business_handler(self):
        for event in denied_messages():
            for text in ("/start pay_"+"A"*32,"/buy","/billing","/trial","/mykeys"):
                await self.feed(event.model_copy(update={"text":text}))
        self.db.assert_not_called()
        self.shadow.assert_not_called()
        self.handler.assert_not_awaited()
        self.answer.assert_not_awaited()

    async def test_invalid_callbacks_stop_all_commercial_surfaces(self):
        for event in denied_callbacks():
            for data in ("buy_key","saas_new_checkout:tariff-1","saas_np:pg:tariff-1",
                         "saas_checkout:7:tariff-1","saas_rp:7:pg:tariff-1","saas_new_check:order-1",
                         "key_renew:7","key_replace:7","saas_billing_cancel:agreement-1",
                         "trial_activate","my_keys","onboarding_ready:7"):
                await self.feed(event.model_copy(update={"data":data}))
        self.db.assert_not_called()
        self.shadow.assert_not_called()
        self.handler.assert_not_awaited()
        for call in self.answer.await_args_list:
            self.assertEqual(call.args,("Откройте личный чат с ботом.",))
            self.assertEqual(call.kwargs,{"show_alert":True})

    async def test_private_commands_and_callbacks_keep_existing_middleware_flow(self):
        for event in (message(text="/mykeys"),callback(data="my_keys")):
            self.assertEqual(await self.feed(event),"handled")
        self.assertEqual(self.handler.await_count,2)
        self.assertEqual(self.db.call_count,2)
        self.assertEqual(self.shadow.call_count,2)
        self.answer.assert_not_awaited()

    async def test_legacy_mode_is_unchanged(self):
        self.mode.return_value = False
        self.assertEqual(await self.feed(message(chat_id=-1,kind="group")),"handled")
        self.handler.assert_awaited_once()

    async def test_callback_answer_failure_does_not_open_boundary_or_log_payload(self):
        self.answer.side_effect = RuntimeError("fixture-sensitive-payload")
        with patch("logging.Logger._log") as log:
            await self.feed(callback(chat_id=-1,kind="group"))
        self.assertNotIn("fixture-sensitive-payload",str(log.call_args_list))
        self.db.assert_not_called()
        self.handler.assert_not_awaited()


class DeliveryBoundaryTests(IsolatedAsyncioTestCase):
    async def test_shared_ready_delivery_denies_target_before_loading_or_projecting(self):
        with patch.object(payment_return,"load_verified_ready_payment_return",AsyncMock()) as load, \
             patch.object(payment_return,"materialize_ready_payment_return",AsyncMock()) as project, \
             patch.object(payment_return,"_render_verified_subscription",AsyncMock()) as render:
            for target in (message(chat_id=-1,kind="group"),message(chat_id=124),None):
                with self.assertRaises(InternalApiError) as error:
                    await payment_return.process_ready_payment_return(message=target,telegram_id=123,access_id="access-1")
                self.assertEqual(error.exception.code,"PRIVATE_CHAT_REQUIRED")
        load.assert_not_awaited()
        project.assert_not_awaited()
        render.assert_not_awaited()

    async def test_direct_renderer_requires_verified_owner_target(self):
        verified = payment_return.VerifiedReadyPaymentReturn(access_id="access-1",telegram_id=123,
            subscription_url="https://entry.invalid/sub/fixture",access={},material={})
        with patch("bot.utils.key_sender_core.render_key_delivery_page",AsyncMock()) as render:
            for target in (message(chat_id=124),message(chat_id=-1,kind="supergroup"),None):
                with self.assertRaises(InternalApiError):
                    await payment_return._render_verified_subscription(target,verified)
            render.assert_not_awaited()
            await payment_return._render_verified_subscription(message(actor=777000),verified)
            render.assert_awaited_once()

    async def test_deeplink_direct_call_denies_before_local_user_or_token_resolution(self):
        with patch("database.requests.get_or_create_user") as local, \
             patch.object(payment_return,"schedule_telegram_user_upsert") as upsert, \
             patch.object(payment_return.internal_api_client,"resolve_payment_return",AsyncMock()) as resolve:
            for target in denied_messages():
                await payment_return.payment_return_deeplink(target,AsyncMock(),CommandObject(command="start",args="pay_"+"A"*32))
        local.assert_not_called()
        upsert.assert_not_called()
        resolve.assert_not_awaited()

    async def test_verified_projection_cannot_be_reused_for_another_telegram_owner(self):
        verified = payment_return.VerifiedReadyPaymentReturn(access_id="access-1",telegram_id=123,
            subscription_url="https://entry.invalid/sub/fixture",access={},material={})
        with patch.object(payment_return.internal_api_client,"list_tariffs",AsyncMock()) as catalog:
            with self.assertRaises(InternalApiError):
                await payment_return.materialize_ready_payment_return(telegram_id=124,access_id="access-1",verified=verified)
        catalog.assert_not_awaited()
