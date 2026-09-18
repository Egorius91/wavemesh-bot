from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from database.admin_provisioning import JournalConflict
from database.migrations import migration_initial, MIGRATIONS
from database.saas_access_projection import project_ready, get_binding


def connection(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def values():
    return dict(tenant_id="tenant", saas_user_id="saas-user", user_id=1, telegram_id=123,
                tariff_id=1, expires_at="2026-10-15T00:00:00Z", traffic_limit=1024, traffic_used=20,
                material={"access_id":"access-1", "node_id":"node-1", "ready":True, "desired_version":1,
                          "protocol":"vless", "primary_inbound_id":1, "panel_email":"fixture-email",
                          "client_uuid":"fixture-uuid", "sub_id":"fixture-sub"})


def set_process_barrier(barrier):
    global process_barrier
    process_barrier = barrier


def concurrent_project(path):
    process_barrier.wait(timeout=15)
    return project_ready(connect=lambda:connection(path), **values())[0], os.getpid()


class ProjectionTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"projection.sqlite"
        conn = self.connect()
        try:
            migration_initial(conn)
            for migration in MIGRATIONS.values():
                migration(conn)
            conn.execute("INSERT INTO users(id,telegram_id) VALUES (1,123)")
            conn.commit()
        finally:
            conn.close()

    def connect(self):
        return connection(self.path)

    def rows(self, sql):
        conn = self.connect()
        try:
            return [dict(r) for r in conn.execute(sql)]
        finally:
            conn.close()

    def mutate(self, sql):
        conn = self.connect()
        try:
            conn.execute(sql)
            conn.commit()
        finally:
            conn.close()

    def project(self, **overrides):
        return project_ready(connect=self.connect, **(values() | overrides))

    def test_two_processes_and_restart_reuse_one_serverless_key(self):
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(2, mp_context=ctx, initializer=set_process_barrier,
                                 initargs=(ctx.Barrier(2),)) as pool:
            first, second = list(pool.map(concurrent_project, [str(self.path)]*2))
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(first[0], second[0])
        self.assertEqual(self.project()[0], first[0])
        keys = self.rows("SELECT * FROM vpn_keys")
        self.assertEqual(len(keys), 1)
        self.assertIsNone(keys[0]["server_id"])
        self.assertEqual(keys[0]["saas_managed"], 1)
        self.assertEqual(len(self.rows("SELECT * FROM saas_access_projections")), 1)

    def test_deleted_projection_is_not_resurrected(self):
        key_id = self.project()[0]
        self.mutate("DELETE FROM vpn_keys")
        self.assertIsNotNone(get_binding(key_id, connect=self.connect))
        with self.assertRaisesRegex(JournalConflict, "LOCAL_PROJECTION_REMOVED"):
            self.project()
        self.assertEqual(self.rows("SELECT * FROM vpn_keys"), [])

    def test_canonical_owner_node_and_key_cannot_change(self):
        self.project()
        for override in ({"saas_user_id":"other"}, {"key_id":99},
                         {"material":values()["material"] | {"node_id":"node-2"}}):
            with self.subTest(override=override), self.assertRaisesRegex(JournalConflict, "BINDING_CHANGED"):
                self.project(**override)

    def test_stale_or_same_version_material_cannot_overwrite(self):
        self.project()
        material = values()["material"]
        for override in ({"material":material | {"client_uuid":"different"}},
                         {"expires_at":"2026-11-15T00:00:00Z"}, {"traffic_limit":99},
                         {"material":material | {"primary_inbound_id":2}}):
            with self.subTest(override=override), self.assertRaises(JournalConflict):
                self.project(**override)
        self.project(material=material | {"desired_version":2})
        with self.assertRaisesRegex(JournalConflict, "STALE_SAAS_MATERIAL"):
            self.project()

    def test_renewal_and_rotation_keep_key_node_and_traffic(self):
        key_id = self.project()[0]
        material = values()["material"] | {"desired_version":2}
        self.assertEqual(self.project(material=material, expires_at="2026-11-15T00:00:00Z")[0], key_id)
        material = material | {"desired_version":3, "client_uuid":"rotated", "sub_id":"rotated-sub"}
        self.assertEqual(self.project(material=material, expires_at="2026-11-15T00:00:00Z", traffic_used=0)[0], key_id)
        row = self.rows("SELECT * FROM vpn_keys")[0]
        self.assertEqual((row["client_uuid"],row["traffic_used"]), ("rotated",20))
        self.assertEqual(get_binding(key_id, connect=self.connect)["node_id"], "node-1")

    def test_projection_failure_rolls_back_key_and_binding(self):
        self.mutate("CREATE TRIGGER fail_binding BEFORE INSERT ON saas_access_projections BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.project()
        self.assertEqual(self.rows("SELECT * FROM vpn_keys"), [])
        self.assertEqual(self.rows("SELECT * FROM saas_access_projections"), [])

    def test_adoption_requires_exact_material_and_one_access(self):
        self.mutate("INSERT INTO vpn_keys(id,user_id,tariff_id,client_uuid,expires_at) VALUES (10,1,1,'foreign','2026-10-15 00:00:00')")
        with self.assertRaisesRegex(JournalConflict,"LOCAL_MATERIAL_CHANGED"):
            self.project(key_id=10)
        self.mutate("UPDATE vpn_keys SET client_uuid='fixture-uuid'")
        self.assertEqual(self.project(key_id=10)[0],10)
        with self.assertRaisesRegex(JournalConflict,"LOCAL_PROJECTION_ALREADY_BOUND"):
            self.project(key_id=10,material=values()["material"] | {"access_id":"access-2"})

    def test_invalid_limits_and_banned_owner_are_rejected(self):
        for override in ({"traffic_used":-1}, {"traffic_limit":2**63}, {"user_id":True}, {"key_id":0}):
            with self.subTest(override=override), self.assertRaises(JournalConflict):
                self.project(**override)
        self.mutate("UPDATE users SET is_banned=1")
        with self.assertRaisesRegex(JournalConflict,"LOCAL_OWNER_INVALID"):
            self.project()

    def test_binding_does_not_contain_material(self):
        key_id = self.project()[0]
        binding = str(get_binding(key_id, connect=self.connect))
        for value in ("fixture-uuid", "fixture-sub", "fixture-email"):
            self.assertNotIn(value,binding)
