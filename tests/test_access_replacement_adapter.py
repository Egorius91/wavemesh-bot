import asyncio
import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.handlers.user import replacement as handler
from bot.handlers.user.payments import saas
from bot.services import access_replacement as service
from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient
from database.access_replacement import ReplacementJournal
from test_access_replacement_journal import Fixture


def callback(data, *, actor=123, chat=123, kind="private", message_id=1, callback_id="fixture"):
    return CallbackQuery(id=callback_id, chat_instance="fixture-chat", data=data,
        from_user=User(id=actor, is_bot=False, first_name="Fixture"),
        message=Message(message_id=message_id, date=datetime.now(timezone.utc),
                        chat=Chat(id=chat,type=kind), from_user=User(id=777000,is_bot=True,first_name="Bot")))


class ReplacementRouterTests(Fixture, IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Bot(token="777000:"+"fixture"*8)
        self.addAsyncCleanup(self.bot.session.close)
        self.dp = Dispatcher(disable_fsm=True)
        # Use the actual production registrations without reparenting the singleton router.
        self.dp.callback_query.handlers.extend(saas.router.callback_query.handlers)
        patch.object(handler,"internal_api_client",self.client).start()
        patch.object(handler,"worker",side_effect=lambda: service.ReplacementWorker(
            self.client, ReplacementJournal(self.connect,lambda: self.now))).start()
        self.output = patch.object(handler,"safe_edit_or_send",AsyncMock()).start()
        patch.object(CallbackQuery,"answer",AsyncMock()).start()
        self.addCleanup(patch.stopall)

    async def feed(self, data, **fields):
        event = callback(data, **fields)
        await self.dp.feed_update(self.bot, Update(update_id=1,callback_query=event))

    def row(self):
        return self.sql("SELECT * FROM access_replacements ORDER BY rowid DESC")[0]

    async def test_router_confirmation_replay_and_explicit_next_intent(self):
        await self.feed("key_replace:1")
        row = self.row()
        self.assertEqual(row["phase"],"PREPARED")
        self.assertEqual(self.client.calls,[])
        buttons = self.output.await_args.kwargs["reply_markup"].inline_keyboard
        self.assertTrue(all(len(b.callback_data.encode())<=64 for group in buttons for b in group))
        await self.feed("replacement_confirm:"+row["id"])
        self.assertEqual(self.row()["status"],"DONE")
        self.assertIn("https://entry.example.invalid/sub/fixture-2",self.output.await_args.args[1])
        await self.feed("key_replace:1",callback_id="another-telegram-update")
        await self.feed("replacement_confirm:"+row["id"])
        self.assertEqual(len(self.client.calls),1)
        await self.feed("replacement_new:"+row["id"])
        second = self.row()
        self.assertNotEqual(second["id"],row["id"])
        self.assertEqual(second["expected_version"],2)
        self.assertEqual(len(self.client.calls),1)
        await self.feed("replacement_confirm:"+second["id"])
        self.assertEqual(self.row()["status"],"DONE")
        self.assertEqual(len(self.client.calls),2)
        await self.feed("replacement_new:"+row["id"])
        self.assertEqual(len(self.sql("SELECT * FROM access_replacements")),2)
        await self.feed("replacement_confirm:"+row["id"])
        self.assertNotIn("https://",self.output.await_args.args[1])
        self.assertEqual(len(self.sql("SELECT * FROM vpn_keys")),1)

    async def test_pending_alias_restart_and_result_check_never_resend(self):
        await self.feed("key_replace:1")
        row = self.row()
        self.client.lost_response = True
        self.client.hidden = True
        await self.feed("replacement_confirm:"+row["id"])
        await self.feed("key_replace:1",message_id=2)
        await self.feed("replacement_confirm:"+row["id"])
        self.assertEqual(len(self.client.calls),1)
        self.assertNotIn("https://",self.output.await_args.args[1])
        self.client.hidden = False
        await self.feed("replacement_check:"+row["id"])
        self.assertEqual(self.row()["status"],"DONE")
        await self.feed("key_replace:1",message_id=2)
        self.assertEqual(len(self.sql("SELECT * FROM access_replacements")),1)
        self.assertEqual(len(self.client.calls),1)

    async def test_cancelled_old_confirmation_does_not_dispatch(self):
        await self.feed("key_replace:1")
        row = self.row()
        await self.feed("replacement_cancel:"+row["id"])
        await self.feed("replacement_confirm:"+row["id"])
        self.assertEqual(self.row()["phase"],"CANCELLED")
        self.assertEqual(self.client.calls,[])

    async def test_foreign_private_actor_cannot_confirm_or_read_result(self):
        await self.feed("key_replace:1")
        row = self.row()
        for action in ("confirm","check","cancel","new"):
            await self.feed("replacement_"+action+":"+row["id"],actor=124,chat=124)
        self.assertEqual(self.row()["phase"],"PREPARED")
        self.assertEqual(self.client.calls,[])
        self.assertNotIn("https://",str(self.output.await_args_list))

    async def test_direct_group_inline_or_wrong_target_never_opens_journal(self):
        for event in (callback("key_replace:1",kind="group",chat=-1),
                      callback("key_replace:1",chat=124),
                      callback("key_replace:1").model_copy(update={"inline_message_id":"inline","message":None})):
            with patch.object(handler,"worker") as factory:
                await handler.begin_replacement(event)
                await handler.replacement_action(event.model_copy(update={"data":"replacement_confirm:"+"a"*32}))
                factory.assert_not_called()
        self.output.assert_not_awaited()

    async def test_failed_response_never_logs_or_renders_raw_error(self):
        await self.feed("key_replace:1")
        row = self.row()
        self.client.lost_response = True
        with patch.object(self.client,"get_access_replacement",AsyncMock(side_effect=TimeoutError("fixture-secret-must-not-escape"))), \
             patch("logging.Logger._log") as log:
            await self.feed("replacement_confirm:"+row["id"])
            self.assertNotIn("fixture-secret-must-not-escape",str(log.call_args_list))
        self.assertNotIn("fixture-secret-must-not-escape",str(self.output.await_args_list))
        self.assertEqual(len(self.client.calls),1)
        self.assertEqual(self.row()["phase"],"DISPATCHED")


class ReplacementHttpTests(IsolatedAsyncioTestCase):
    def result(self):
        return dict(request_id="request-1",request_status="SUCCEEDED",submission="OBSERVED",status="READY",
                    can_retry_replace=False,access_id="access-1",command_id="command-1",command_status="SUCCEEDED",
                    assigned_entry_node_id="node-1",desired_version=2,raw_error="must-not-forward")

    async def test_get_uses_original_key_and_version_and_strips_unknown_fields(self):
        client = WaveMeshInternalApiClient()
        with patch.object(client,"_request",AsyncMock(return_value=self.result())) as request:
            result = await client.get_access_replacement("access-1","original-request-key",1)
            request.assert_awaited_once_with("GET","bot/accesses/access-1/replacement?expected_version=1",
                                           idempotency_key="original-request-key")
            self.assertNotIn("raw_error",result)

    async def test_invalid_request_never_reaches_transport(self):
        client = WaveMeshInternalApiClient()
        for access,key,version in (("../other","original-request-key",1),("access-1","short",1),
                                   *( ("access-1","original-request-key",v) for v in (True,"1",None,0,2147483647) )):
            with patch.object(client,"_request",AsyncMock()) as request:
                with self.assertRaises(InternalApiError):
                    await client.replace_access(access_id=access,idempotency_key=key,expected_version=version)
                with self.assertRaises(InternalApiError):
                    await client.get_access_replacement(access,key,version)
                request.assert_not_awaited()

    async def test_malformed_response_is_bounded_and_does_not_retry_http(self):
        client = WaveMeshInternalApiClient()
        for result in (None,{},self.result()|{"desired_version":True},self.result()|{"status":[]},
                       self.result()|{"access_id":"foreign"},self.result()|{"can_retry_replace":True}):
            with patch.object(client,"_request",AsyncMock(return_value=result)) as request:
                with self.assertRaises(InternalApiError) as caught:
                    await client.get_access_replacement("access-1","original-request-key",1)
                self.assertNotIn("must-not-forward",str(caught.exception))
                self.assertEqual(request.await_count,1)
        with patch.object(client,"_request",AsyncMock(return_value=dict(command_id="command-1",status="succeeded",desired_version=2))):
            self.assertEqual((await client.replace_access(access_id="access-1",idempotency_key="original-request-key",expected_version=1))["status"],"succeeded")


class ReplacementStartupTests(IsolatedAsyncioTestCase):
    async def test_worker_is_saas_only_singleton_and_shutdown_cancels_it(self):
        await service.stop_access_replacement_worker()
        self.addAsyncCleanup(service.stop_access_replacement_worker)
        for mode, enabled in ((False,True),(True,False)):
            with patch("bot.services.runtime_mode.saas_client_mode_enabled",return_value=mode), \
                 patch("bot.services.internal_api.internal_api_client",SimpleNamespace(enabled=enabled)):
                service.start_access_replacement_worker()
                self.assertIsNone(service._task)
        entered = asyncio.Event()
        async def run_once():
            entered.set()
            await asyncio.Event().wait()
        with patch("bot.services.runtime_mode.saas_client_mode_enabled",return_value=True), \
             patch("bot.services.internal_api.internal_api_client",SimpleNamespace(enabled=True)), \
             patch.object(service.ReplacementWorker,"run_once",side_effect=run_once):
            service.start_access_replacement_worker()
            original = service._task
            service.start_access_replacement_worker()
            self.assertIs(service._task,original)
            await asyncio.wait_for(entered.wait(),1)
            await service.stop_access_replacement_worker()
            self.assertTrue(original.done())
            self.assertIsNone(service._task)

    async def test_startup_runs_after_migration_and_shutdown_paths_stop_worker(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        functions = {n.name:n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)}
        startup = functions["on_startup"]
        calls = {n.func.id:n.lineno for n in ast.walk(startup) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertLess(calls["enforce_internal_api_startup"],calls["start_access_replacement_worker"])
        self.assertLess(calls["run_migrations"],calls["start_access_replacement_worker"])
        branch = next(n for n in startup.body if isinstance(n,ast.If) and any(
            isinstance(c,ast.Call) and isinstance(c.func,ast.Name) and c.func.id=="start_access_replacement_worker"
            for c in ast.walk(n)))
        self.assertEqual(ast.unparse(branch.test),"internal_api_ready and saas_mode")
        for name in ("on_shutdown","main"):
            self.assertTrue(any(isinstance(n,ast.Await) and isinstance(n.value,ast.Call)
                and isinstance(n.value.func,ast.Name) and n.value.func.id=="stop_access_replacement_worker"
                for n in ast.walk(functions[name])))
