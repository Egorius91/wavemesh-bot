import asyncio
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase, IsolatedAsyncioTestCase

from database.access_replacement import ReplacementJournal, ensure_schema
from database.admin_provisioning import JournalConflict, connection_scope
from database.migrations import migration_initial, MIGRATIONS
from database.saas_access_projection import project_ready
from bot.services.access_replacement import ReplacementWorker
from bot.services.replacement_contract import readback, reference, request_values


def connection(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class FakeClient:
    base_url, tenant_id, token = "https://api.example.invalid", "tenant", "fixture-not-a-token"

    def __init__(self):
        self.version = 1
        self.calls = []
        self.reads = []
        self.lost_response = False
        self.hidden = False
        self.result = None
        self.node = "node-1"
        self.saas_user = "saas-user"

    def material(self):
        suffix = "" if self.version == 1 else f"-{self.version}"
        return dict(access_id="access-1", node_id=self.node, ready=True, desired_version=self.version,
                    protocol="vless", primary_inbound_id=1, panel_email="fixture-email"+suffix,
                    client_uuid="fixture-uuid"+suffix, sub_id="fixture-sub"+suffix,
                    subscription_url="https://entry.example.invalid/sub/fixture"+suffix)

    async def get_telegram_dashboard(self, telegram_id):
        return {"user": {"tenant_id": self.tenant_id, "user_id": self.saas_user}, "accesses": [{
            "access_id": "access-1", "legacy_key_id": "1", "telegram_id": str(telegram_id), "authority": "managed",
            "status": "ready", "enabled": True, "desired_version": self.version,
            "expires_at": "2099-10-15T00:00:00Z", "traffic_limit_bytes": "1024", "traffic_used_bytes": "10",
            "subscription_url": self.material()["subscription_url"]}]}

    async def get_access_material(self, access_id):
        return self.material()

    async def replace_access(self, **kwargs):
        self.calls.append(kwargs)
        if self.version != kwargs["expected_version"]:
            raise RuntimeError("fixture-stale")
        self.version += 1
        self.result = dict(request_id=f"request-{len(self.calls)}", request_status="SUCCEEDED", submission="OBSERVED", status="READY",
                           can_retry_replace=False, access_id="access-1", command_id=f"command-{len(self.calls)}", command_status="SUCCEEDED",
                           assigned_entry_node_id=self.node, desired_version=self.version)
        if self.lost_response:
            raise TimeoutError("fixture-secret-must-not-escape")
        return dict(command_id=self.result["command_id"], status="pending", desired_version=self.version)

    async def get_access_replacement(self, access_id, request_key, expected_version):
        self.reads.append((access_id, request_key, expected_version))
        if self.hidden:
            return dict(request_id="request-1", request_status="PROCESSING", submission="UNCONFIRMED", status="TIMEOUT",
                        can_retry_replace=False, access_id=None, command_id=None, assigned_entry_node_id=None, desired_version=None)
        if self.result is None:
            raise LookupError("fixture-404")
        return self.result.copy()


class Fixture:
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"replacement.sqlite"
        self.now = 1000.0
        conn = self.connect()
        try:
            migration_initial(conn)
            for migration in MIGRATIONS.values():
                migration(conn)
            conn.execute("INSERT INTO users(id,telegram_id) VALUES (1,123)")
            conn.commit()
        finally:
            conn.close()
        self.client = FakeClient()
        project_ready(connect=self.connect, tenant_id="tenant", saas_user_id="saas-user", user_id=1, telegram_id=123,
                      tariff_id=1, expires_at="2099-10-15T00:00:00Z", traffic_limit=1024, traffic_used=20, material=self.client.material())
        self.journal = ReplacementJournal(self.connect, lambda: self.now)
        self.runner = ReplacementWorker(self.client, self.journal)

    def connect(self):
        return connection(self.path)

    def sql(self, query):
        conn = self.connect()
        try:
            result = [dict(r) for r in conn.execute(query)]
            conn.commit()
            return result
        finally:
            conn.close()

    def prepare(self, alias="message-one"):
        return self.journal.prepare(callback_key=alias, scope=connection_scope(self.client),
                                    binding=self.journal.binding(1, 123, "tenant"), expected_version=1)

    def confirm(self, row):
        return self.journal.confirm(row["id"], 123, connection_scope(self.client))


def process_barrier_init(barrier):
    global barrier_ready
    barrier_ready = barrier


def process_prepare(path):
    journal = ReplacementJournal(lambda: connection(path), lambda: 1000)
    binding = journal.binding(1, 123, "tenant")
    barrier_ready.wait(timeout=15)
    row = journal.prepare(callback_key=f"process-{os.getpid()}", scope=connection_scope(FakeClient()), binding=binding, expected_version=1)
    return row["id"], os.getpid()


def process_confirm(args):
    path, operation_id = args
    journal = ReplacementJournal(lambda: connection(path), lambda: 1000)
    barrier_ready.wait(timeout=15)
    journal.confirm(operation_id, 123, connection_scope(FakeClient()))
    row = journal.claim(operation_id, explicit=True)
    if row:
        journal.dispatch(row)
    return bool(row), os.getpid()


class JournalTests(Fixture, TestCase):
    def test_two_processes_prepare_one_operation_and_remember_both_messages(self):
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(2, mp_context=ctx, initializer=process_barrier_init, initargs=(ctx.Barrier(2),)) as pool:
            first, second = list(pool.map(process_prepare, [str(self.path)]*2))
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(first[0], second[0])
        self.assertEqual(len(self.sql("SELECT * FROM access_replacements")), 1)
        self.assertEqual(len(self.sql("SELECT * FROM access_replacement_callbacks")), 2)

    def test_two_processes_confirm_and_receive_only_one_dispatch_permission(self):
        row = self.prepare()
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(2, mp_context=ctx, initializer=process_barrier_init, initargs=(ctx.Barrier(2),)) as pool:
            results = list(pool.map(process_confirm, [(str(self.path), row["id"])]*2))
        self.assertNotEqual(results[0][1], results[1][1])
        self.assertEqual(sum(r[0] for r in results), 1)
        self.assertEqual(self.journal.get(row["id"])["phase"], "DISPATCHED")

    def test_expired_lease_cannot_dispatch_or_finalize_over_another_worker(self):
        row = self.confirm(self.prepare())
        old = self.journal.claim(row["id"])
        self.now += 121
        new = self.journal.claim(row["id"])
        with self.assertRaisesRegex(JournalConflict, "LEASE_LOST"):
            self.journal.dispatch(old)
        self.journal.dispatch(new)
        self.now += 121
        latest = self.journal.claim(row["id"])
        with self.assertRaisesRegex(JournalConflict, "ALREADY_DISPATCHED"):
            self.journal.dispatch(latest)
        with self.assertRaisesRegex(JournalConflict, "LEASE_LOST"):
            self.journal.release(new)

    def test_cancel_and_confirmation_expiry_cannot_dispatch(self):
        row = self.prepare()
        self.now += 601
        self.assertEqual(self.confirm(row)["phase"], "CANCELLED")
        self.assertIsNone(self.journal.claim(row["id"], explicit=True))
        second = self.journal.prepare(callback_key="second", scope=connection_scope(self.client),
                                      binding=self.journal.binding(1,123,"tenant"), expected_version=1, previous_id=row["id"])
        self.journal.cancel(second["id"],123,connection_scope(self.client))
        self.assertEqual(self.confirm(second)["phase"], "CANCELLED")

    def test_foreign_actor_scope_and_deleted_binding_fail_closed(self):
        row = self.prepare()
        for actor, scope in [(999,connection_scope(self.client)), (123,"other-scope")]:
            with self.assertRaises(JournalConflict):
                self.journal.confirm(row["id"],actor,scope)
        self.sql("DELETE FROM vpn_keys")
        with self.assertRaises(JournalConflict):
            self.confirm(row)
        self.assertIsNotNone(self.journal.get(row["id"]))
        self.assertEqual(self.sql("SELECT * FROM vpn_keys"), [])

    def test_migration_is_idempotent_and_does_not_store_material_in_intent(self):
        row = self.prepare()
        conn = self.connect()
        ensure_schema(conn)
        conn.close()
        self.assertEqual(self.journal.get(row["id"]), row)
        encoded = str(self.sql("SELECT * FROM access_replacements"))
        for sensitive in ("fixture-email", "fixture-uuid", "fixture-sub", self.client.token, self.client.base_url):
            self.assertNotIn(sensitive, encoded)


class WorkerTests(Fixture, IsolatedAsyncioTestCase):
    async def test_post_command_is_persisted_before_readback_and_cannot_change(self):
        row = self.confirm(self.prepare())
        original = self.client.get_access_replacement
        async def mismatch(*args):
            self.assertEqual(self.journal.get(row["id"])["command_id"], "command-1")
            return (await original(*args)) | {"command_id":"foreign-command"}
        self.client.get_access_replacement = mismatch
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["status"],"MANUAL_REVIEW")
        self.assertEqual(result["command_id"],"command-1")
        self.assertEqual(self.sql("SELECT desired_version FROM saas_access_projections")[0]["desired_version"],1)

    async def test_lease_expires_during_post_and_new_worker_only_reads_original(self):
        row = self.confirm(self.prepare())
        original = self.client.replace_access
        async def delayed(**kwargs):
            result = await original(**kwargs)
            self.now += 121
            other = ReplacementWorker(self.client,ReplacementJournal(self.connect,lambda: self.now))
            self.assertEqual((await other.reconcile(row["id"],explicit=True))["status"],"DONE")
            return result
        self.client.replace_access = delayed
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["status"],"DONE")
        self.assertEqual(len(self.client.calls),1)
        self.assertEqual(len(self.client.reads),1)

    async def test_local_binding_change_while_pending_stops_before_readback(self):
        row = self.confirm(self.prepare())
        self.client.hidden = True
        await self.runner.reconcile(row["id"],explicit=True)
        count = len(self.client.reads)
        self.sql("UPDATE saas_access_projections SET node_id='other-node'")
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["status"],"MANUAL_REVIEW")
        self.assertEqual(len(self.client.reads),count)
        self.assertEqual(len(self.client.calls),1)

    async def test_lost_response_and_restart_complete_once_without_reset_or_new_key(self):
        row = self.confirm(await self.runner.prepare("source",1,123))
        self.client.lost_response = True
        done = await self.runner.reconcile(row["id"], explicit=True)
        self.assertEqual(done["status"], "DONE")
        restarted = ReplacementWorker(self.client, ReplacementJournal(self.connect, lambda:self.now))
        await restarted.reconcile(row["id"], explicit=True)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["expected_version"],1)
        self.assertEqual(self.client.reads[0],("access-1",row["request_key"],1))
        keys = self.sql("SELECT * FROM vpn_keys")
        self.assertEqual(len(keys),1)
        self.assertEqual(keys[0]["traffic_used"],20)
        self.assertEqual(keys[0]["id"],1)
        self.assertEqual(keys[0]["client_uuid"],"fixture-uuid-2")

    async def test_old_completed_callback_stays_original_and_new_intent_is_explicit(self):
        row = self.confirm(await self.runner.prepare("old-message",1,123))
        await self.runner.reconcile(row["id"],explicit=True)
        replay = await self.runner.prepare("old-message",1,123)
        self.assertEqual(replay["id"],row["id"])
        self.assertEqual(self.confirm(replay)["phase"],"DONE")
        child = await self.runner.prepare("next:"+row["id"],1,123,previous_id=row["id"])
        self.assertNotEqual(child["id"],row["id"])
        self.assertEqual(child["expected_version"],2)
        self.assertEqual(len(self.client.calls),1)
        self.confirm(child)
        await self.runner.reconcile(child["id"],explicit=True)
        self.assertEqual(len(self.client.calls),2)
        self.assertEqual((await self.runner.prepare("next:"+row["id"],1,123,previous_id=row["id"]))["id"],child["id"])

    async def test_unconfirmed_late_result_binds_all_messages_and_never_resends(self):
        row = self.confirm(await self.runner.prepare("first",1,123))
        self.client.hidden = True
        pending = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(pending["status"],"TIMEOUT")
        alias = await self.runner.prepare("second",1,123)
        self.assertEqual(alias["id"],row["id"])
        self.now += 600
        await self.runner.run_once()
        self.assertEqual(len(self.client.calls),1)
        self.client.hidden = False
        done = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(done["status"],"DONE")
        self.assertEqual((await self.runner.prepare("second",1,123))["id"],row["id"])

    async def test_crash_after_dispatch_marker_but_before_network_does_not_resend(self):
        row = self.confirm(self.prepare())
        claimed = self.journal.claim(row["id"])
        self.journal.dispatch(claimed)
        self.now += 121
        pending = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(pending["phase"],"DISPATCHED")
        self.assertEqual(self.client.calls,[])
        self.assertEqual(pending["status"],"TIMEOUT")
        self.assertEqual((await self.runner.prepare("different-message",1,123))["id"],row["id"])

    async def test_atomic_finalize_failure_rolls_back_projection_and_later_readback_recovers(self):
        row = self.confirm(self.prepare())
        self.sql("""CREATE TRIGGER reject_done BEFORE UPDATE ON access_replacements WHEN NEW.phase='DONE'
            BEGIN SELECT RAISE(ABORT,'fixture-stop'); END""")
        pending = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(pending["phase"],"OBSERVED")
        self.assertEqual(self.sql("SELECT desired_version FROM saas_access_projections")[0]["desired_version"],1)
        self.assertEqual(self.sql("SELECT client_uuid FROM vpn_keys")[0]["client_uuid"],"fixture-uuid")
        self.sql("DROP TRIGGER reject_done")
        self.assertEqual((await self.runner.reconcile(row["id"],explicit=True))["status"],"DONE")
        self.assertEqual(len(self.client.calls),1)

    async def test_stale_before_dispatch_cancels_without_sending(self):
        row = self.confirm(self.prepare())
        self.client.version = 2
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["phase"],"CANCELLED")
        self.assertEqual(result["status"],"STALE")
        self.assertEqual(self.client.calls,[])

    async def test_deleted_or_changed_owner_during_pending_cannot_be_recreated(self):
        row = self.confirm(self.prepare())
        self.client.hidden = True
        await self.runner.reconcile(row["id"],explicit=True)
        self.sql("DELETE FROM vpn_keys")
        self.client.hidden = False
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["status"],"MANUAL_REVIEW")
        self.assertEqual(self.sql("SELECT * FROM vpn_keys"),[])
        self.assertEqual(len(self.client.calls),1)

    async def test_wrong_node_or_saas_owner_never_materializes(self):
        for field in ("node","saas_user"):
            row = self.confirm(self.prepare())
            self.client.hidden = True
            await self.runner.reconcile(row["id"],explicit=True)
            self.client.hidden = False
            old = getattr(self.client,field)
            setattr(self.client,field,"foreign")
            result = await self.runner.reconcile(row["id"],explicit=True)
            self.assertNotEqual(result["status"],"DONE")
            self.assertEqual(self.sql("SELECT desired_version FROM saas_access_projections")[0]["desired_version"],1)
            setattr(self.client,field,old)

    async def test_request_id_cannot_change_after_unconfirmed_read(self):
        row = self.confirm(self.prepare())
        self.client.hidden = True
        await self.runner.reconcile(row["id"],explicit=True)
        self.client.hidden = False
        self.client.result["request_id"] = "other-request"
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["status"],"MANUAL_REVIEW")
        self.assertEqual(len(self.client.calls),1)

    async def test_superseded_pending_command_stays_unresolved_until_original_is_terminal(self):
        row = self.confirm(self.prepare())
        self.client.hidden = True
        await self.runner.reconcile(row["id"],explicit=True)
        self.client.hidden = False
        self.client.result.update(status="SUPERSEDED",command_status="RUNNING")
        pending = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(pending["phase"],"OBSERVED")
        self.client.result["command_status"] = "SUCCEEDED"
        terminal = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(terminal["phase"],"DONE")
        self.assertEqual(terminal["status"],"SUPERSEDED")
        self.assertEqual(self.sql("SELECT desired_version FROM saas_access_projections")[0]["desired_version"],1)

    async def test_terminal_failure_never_projects_new_material(self):
        row = self.confirm(self.prepare())
        self.client.hidden = True
        await self.runner.reconcile(row["id"],explicit=True)
        self.client.hidden = False
        self.client.result.update(status="FAILED",command_status="ROLLED_BACK")
        result = await self.runner.reconcile(row["id"],explicit=True)
        self.assertEqual(result["phase"],"DONE")
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(self.sql("SELECT client_uuid FROM vpn_keys")[0]["client_uuid"],"fixture-uuid")

    async def test_scope_rotation_blocks_original_and_new_requests(self):
        row = self.confirm(self.prepare())
        self.client.token = "different-fixture-credential"
        self.assertEqual((await self.runner.reconcile(row["id"],explicit=True))["status"],"MANUAL_REVIEW")
        with self.assertRaises(JournalConflict):
            await self.runner.prepare("new-message",1,123)
        self.assertEqual(self.client.calls,[])


class ContractTests(TestCase):
    def test_request_version_and_path_are_strict(self):
        for version in (None,True,"1",0,-1,1.5,2_147_483_647):
            with self.assertRaises(ValueError):
                request_values("access","original-request-key",version)
        for access in ("../access","access?version=2",""):
            with self.assertRaises(ValueError):
                request_values(access,"original-request-key",1)

    def test_readback_rejects_wrong_command_version_and_strips_unknown_material(self):
        result = dict(request_id="request",request_status="SUCCEEDED",submission="OBSERVED",status="READY",
                      can_retry_replace=False,access_id="access",command_id="command",command_status="SUCCEEDED",
                      assigned_entry_node_id="node",desired_version=2,secret="must-not-escape")
        self.assertNotIn("secret",readback(result,"access",1))
        for change in ({"desired_version":True},{"desired_version":3},{"can_retry_replace":True},
                       {"access_id":"other"},{"command_status":"RUNNING"},{"assigned_entry_node_id":"../node"}):
            with self.assertRaises(ValueError):
                readback(result|change,"access",1)
        self.assertEqual(reference(dict(command_id="command",status="succeeded",desired_version=2),1)["desired_version"],2)
