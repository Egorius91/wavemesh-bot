from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import IsolatedAsyncioTestCase

from bot.services.admin_provisioning import ProvisioningWorker
from database.admin_provisioning import Journal, JournalConflict, connection_scope
from database.migrations import migration_initial, MIGRATIONS


class FakeSaas:
    base_url, tenant_id, token = "https://saas.invalid/internal/v1", "tenant", "test-credential"

    def __init__(self):
        self.calls, self.shadow, self.provisioned = [], None, False
        self.lose, self.ready, self.exists = None, True, False
        self.owner, self.binding, self.expiry = "saas-user", "access-1", "2026-10-15T00:00:00Z"
        self.dispatch_entered = self.dispatch_release = None

    async def upsert_telegram_user(self, **payload):
        self.calls.append(("user", payload["idempotency_key"]))
        self.exists = True
        if self.lose == "user":
            raise TimeoutError("raw credential should never escape")
        return {}

    async def sync_access_shadow(self, **payload):
        self.calls.append(("shadow", payload["idempotency_key"]))
        self.shadow = payload["payload"]
        if self.lose == "shadow":
            raise TimeoutError("raw credential should never escape")
        return {"access_id": self.binding}

    async def create_access(self, **payload):
        self.calls.append(("create", payload["idempotency_key"]))
        self.provisioned = True
        if self.dispatch_entered:
            self.dispatch_entered.set()
            await self.dispatch_release.wait()
        if self.lose == "create":
            raise TimeoutError("raw credential should never escape")
        return {"access_id": self.binding, "command_id": "command-1"}

    async def get_access_provisioning(self, key):
        if not self.provisioned:
            return {"submission": "UNCONFIRMED", "status": "TIMEOUT", "can_retry_create": False}
        return {"submission": "OBSERVED", "status": "READY" if self.ready else "MATERIALIZING",
                "access_id": self.binding, "command_id": "command-1", "assigned_entry_node_id": "node-1",
                "legacy_key_id": self.shadow["legacy_key_id"], "expires_at": self.expiry, "can_retry_create": False}

    async def get_telegram_dashboard(self, telegram_id):
        if not self.exists:
            raise LookupError("not yet visible")
        accesses = []
        if self.shadow:
            accesses.append({**self.shadow, "access_id": self.binding,
                "authority": "managed" if self.provisioned else "legacy_snapshot",
                "expires_at": self.expiry if self.provisioned else self.shadow["expires_at"],
                "status": "ready" if self.ready else "materializing", "enabled": True,
                "desired_version": 1, "subscription_url": "https://entry.invalid/sub/fixture"})
        return {"user": {"user_id": self.owner, "tenant_id": self.tenant_id}, "accesses": accesses}

    async def get_access_material(self, access_id):
        return {"access_id": access_id, "status": "ready" if self.ready else "materializing", "ready": self.ready,
                "desired_version": 1, "panel_email": "fixture-email", "client_uuid": "fixture-uuid",
                "sub_id": "fixture-sub", "primary_inbound_id": 1, "protocol": "vless",
                "subscription_url": "https://entry.invalid/sub/fixture"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class JournalTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"test.sqlite"
        self.now = 1789430400.0
        self.client = FakeSaas()
        with self.connect() as conn:
            migration_initial(conn)
            for migration in MIGRATIONS.values():
                migration(conn)
            conn.execute("INSERT INTO users(id,telegram_id,first_name) VALUES (1,123,'Fixture')")
            conn.execute("""INSERT INTO servers(id,name,host,port,web_base_path,login,password)
                VALUES (1,'fixture','entry.invalid',443,'/','fixture','fixture')""")
        self.journal = Journal(self.connect, lambda: self.now)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def prepare(self, **overrides):
        args = dict(callback_key="9:9:1", admin_id=9, scope=connection_scope(self.client),
            user_id=1, telegram_id=123, tariff_id=1, days=30, traffic_limit=1024, device_limit=1)
        args.update(overrides)
        return self.journal.prepare(**args)

    async def test_duplicate_confirmation_and_two_connections_create_one_draft(self):
        barrier = Barrier(2)
        def prepare():
            barrier.wait()
            return self.prepare()
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(prepare) for _ in range(2)]
            rows = [f.result() for f in futures]
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vpn_keys").fetchone()[0], 1)
        self.assertEqual(self.prepare(callback_key="9:9:2")["id"], rows[0]["id"])

    async def test_prepare_rollback_does_not_leave_draft(self):
        with self.connect() as conn:
            conn.execute("""CREATE TRIGGER fail_intent BEFORE INSERT ON admin_provisioning
                BEGIN SELECT RAISE(ABORT,'fixture'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.prepare()
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vpn_keys").fetchone()[0], 0)

    async def test_lost_responses_reconstruct_worker_without_repeating_any_write(self):
        for phase in ("user", "shadow", "create"):
            with self.subTest(phase=phase):
                self.client = FakeSaas()
                row = self.prepare(callback_key="9:9:"+phase)
                self.client.lose = phase
                await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
                self.client.lose = None
                self.now += 16
                result = await ProvisioningWorker(self.client, Journal(self.connect, lambda: self.now)).reconcile(row["id"])
                self.assertEqual(result["status"], "DONE")
                for action in ("user", "shadow", "create"):
                    self.assertEqual(self.client.calls.count((action, row["request_key"] + ("-"+action if action != "create" else ""))), 1)
                with self.connect() as conn:
                    self.assertEqual(conn.execute("SELECT expires_at FROM vpn_keys WHERE id=?", (row["key_id"],)).fetchone()[0], "2026-10-15 00:00:00")

    async def test_two_workers_and_expired_lease_do_not_repeat_dispatch(self):
        row = self.prepare()
        self.client.dispatch_entered, self.client.dispatch_release = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(ProvisioningWorker(self.client, self.journal).reconcile(row["id"]))
        await self.client.dispatch_entered.wait()
        second = ProvisioningWorker(self.client, Journal(self.connect, lambda: self.now))
        self.assertEqual((await second.reconcile(row["id"]))["phase"], "SUBMIT_DISPATCHED")
        self.now += 121
        self.assertEqual((await second.reconcile(row["id"]))["status"], "DONE")
        self.client.dispatch_release.set()
        await first
        self.assertEqual(sum(a=="create" for a, _ in self.client.calls), 1)
        self.assertEqual(self.journal.get(row["id"])["status"], "DONE")

    async def test_crash_after_dispatch_intent_before_http_never_authorizes_create(self):
        row = self.prepare()
        claimed = self.journal.claim(row["id"])
        self.journal.advance(claimed, "SUBMIT_DISPATCHED")
        self.now += 121
        worker = ProvisioningWorker(self.client, self.journal)
        result = await worker.reconcile(row["id"])
        self.assertEqual(result["status"], "TIMEOUT")
        await worker.reconcile(row["id"], explicit=True)
        self.assertEqual(self.client.calls, [])

    async def test_processing_readback_keeps_polling_until_late_commit_is_visible(self):
        row = self.prepare()
        self.client.lose = "create"
        worker = ProvisioningWorker(self.client, self.journal)
        await worker.reconcile(row["id"])
        original = self.client.get_access_provisioning
        async def processing(key):
            return {"submission":"UNCONFIRMED", "status":"PENDING", "can_retry_create":False}
        self.client.get_access_provisioning = processing
        self.now += 16
        result = await worker.reconcile(row["id"])
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["phase"], "SUBMIT_DISPATCHED")
        self.client.get_access_provisioning = original
        self.now += 16
        await ProvisioningWorker(self.client, self.journal).run_once()
        self.assertEqual(self.journal.get(row["id"])["status"], "DONE")
        self.assertEqual(sum(a=="create" for a, _ in self.client.calls), 1)

    async def test_deletion_does_not_erase_intent_or_resurrect_projection(self):
        row = self.prepare()
        self.client.lose = "create"
        await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        with self.connect() as conn:
            conn.execute("DELETE FROM vpn_keys WHERE id=?", (row["key_id"],))
        self.now += 16
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["last_error"], "LOCAL_OWNER_REMOVED")
        self.assertEqual(result["status"], "MANUAL_REVIEW")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vpn_keys").fetchone()[0], 0)

    async def test_projection_and_done_are_atomic_and_recover_after_failed_commit(self):
        row = self.prepare()
        with self.connect() as conn:
            conn.execute("""CREATE TRIGGER fail_done BEFORE UPDATE ON admin_provisioning
                WHEN NEW.status='DONE' BEGIN SELECT RAISE(ABORT,'fixture'); END""")
        await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT client_uuid FROM vpn_keys WHERE id=?", (row["key_id"],)).fetchone()[0])
            conn.execute("DROP TRIGGER fail_done")
        self.now += 16
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(sum(a=="create" for a, _ in self.client.calls), 1)

    async def test_credential_change_cannot_adopt_old_operation(self):
        row = self.prepare()
        self.client.token = "different-service-client"
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["last_error"], "SERVICE_CREDENTIAL_CHANGED")
        self.assertEqual(self.client.calls, [])

    async def test_wrong_server_host_requires_review(self):
        row = self.prepare()
        with self.connect() as conn:
            conn.execute("UPDATE servers SET host='other.invalid'")
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["last_error"], "SERVER_MAPPING_AMBIGUOUS")
        with self.connect() as conn:
            conn.execute("UPDATE servers SET host='entry.invalid'")
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"], explicit=True)
        self.assertEqual(result["status"], "DONE")

    async def test_duplicate_server_mapping_and_owner_change_require_review(self):
        row = self.prepare()
        self.client.lose = "create"
        await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        with self.connect() as conn:
            conn.execute("""INSERT INTO servers(name,host,port,web_base_path,login,password)
                VALUES ('second','entry.invalid',443,'/','fixture','fixture')""")
        self.now += 16
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["last_error"], "SERVER_MAPPING_AMBIGUOUS")
        self.client.owner = "different-user"
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"], explicit=True)
        self.assertEqual(result["last_error"], "SAAS_OWNER_CHANGED")
        self.assertEqual(sum(a=="create" for a, _ in self.client.calls), 1)

    async def test_saas_terminal_failure_is_visible_without_another_grant(self):
        row = self.prepare()
        original = self.client.get_access_provisioning
        async def failed(key):
            return {**await original(key), "status":"FAILED"}
        self.client.get_access_provisioning = failed
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["status"], "FAILED")
        await ProvisioningWorker(self.client, self.journal).reconcile(row["id"], explicit=True)
        self.assertEqual(sum(a=="create" for a, _ in self.client.calls), 1)

    async def test_foreign_admin_and_banned_user_are_rejected(self):
        self.prepare()
        with self.assertRaises(JournalConflict):
            self.prepare(admin_id=10)
        with self.assertRaises(JournalConflict):
            self.journal.for_callback("9:9:1", 10, connection_scope(self.client))
        with self.connect() as conn:
            conn.execute("UPDATE users SET is_banned=1")
        result = await ProvisioningWorker(self.client, self.journal).reconcile(self.prepare()["id"])
        self.assertEqual(result["last_error"], "LOCAL_OWNER_REMOVED")

    async def test_journal_never_persists_material_or_raw_errors(self):
        row = self.prepare()
        self.client.lose = "create"
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertNotIn("raw credential", json.dumps(result))
        self.now += 16
        result = await ProvisioningWorker(self.client, self.journal).reconcile(row["id"])
        self.assertEqual(result["status"], "DONE")
        for secret in (self.client.token, "fixture-email", "fixture-uuid", "fixture-sub", "https://entry.invalid"):
            self.assertNotIn(secret, json.dumps(result))
