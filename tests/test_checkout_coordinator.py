import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web

from bot.services.checkout_contract import CheckoutContractError, snapshot
from bot.services.checkout_coordinator import CheckoutCoordinator
from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient
from database.admin_provisioning import JournalConflict, connection_scope
from database.checkout_intents import CheckoutJournal, ensure_schema


OWNER = "user-fixture-123"
TARIFF = {"tariff_id": "tariff-fixture-123", "name": "Original", "billing_mode": "RECURRING",
          "price_rub": 299, "duration_days": 30, "device_limit": 2, "traffic_limit_gb": None}


def wire(order="order-fixture-123", status="PENDING"):
    return {"version": 1, "allowNewCreate": False, "orderId": order, "paymentStatus": status,
            "checkoutUrl": "https://checkout.invalid/original" if status == "PENDING" else None,
            "terms": {"tariffId": TARIFF["tariff_id"], "name": "Original", "amountRub": 299, "durationDays": 30,
                      "deviceLimit": 2, "trafficLimitGb": None, "purchaseKind": "NEW_ACCESS"},
            "entitlement": {"status": "PENDING"}, "access": None, "recurring": "PENDING"}


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "journal.db"
        conn = self.connect()
        ensure_schema(conn)
        conn.commit()
        conn.close()
        self.journal = CheckoutJournal(self.connect)
        self.owner, self.current, self.originals = OWNER, None, {}
        self.posts, self.requests, self.catalog = [], [], [deepcopy(TARIFF)]
        self.post_mode, self.discovery_status = "success", 200
        self.accesses = []
        self.app = web.Application()
        self.app.router.add_route("*", "/{path:.*}", self.handle)
        self.server = web.AppRunner(self.app, access_log=None)
        await self.server.setup()
        site = web.TCPSite(self.server, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.client = WaveMeshInternalApiClient()
        self.client.base_url = f"http://127.0.0.1:{port}"
        self.client.tenant_id, self.client.token, self.client.enabled = "tenant-fixture", "fixture-only", True
        self.runner = CheckoutCoordinator(self.client, self.journal)

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.cleanup()
        self.tmp.cleanup()

    async def handle(self, request):
        self.requests.append((request.method, request.path))
        self.assertEqual(request.headers["Authorization"], "Bearer fixture-only")
        self.assertEqual(request.headers["x-wavevpn-tenant-id"], "tenant-fixture")
        if request.path == "/bot/users/123/dashboard":
            return web.json_response({"user": {"user_id": self.owner}, "accesses": self.accesses})
        if request.path == "/catalog/tariffs":
            return web.json_response(self.catalog)
        if request.path == "/bot/orders/checkout/current":
            self.assertEqual(request.query["user_id"], self.owner)
            return web.json_response(self.current or {"version": 1, "current": None, "allowNewCreate": False}, status=self.discovery_status)
        if request.path == "/bot/orders/checkout/status":
            self.assertEqual(request.query["user_id"], self.owner)
            original = self.originals.get(request.headers["Idempotency-Key"])
            return web.json_response(original or {"code": "CHECKOUT_NOT_FOUND"}, status=200 if original else 404)
        if request.path == "/bot/orders" and request.method == "POST":
            body = await request.json()
            key = request.headers["Idempotency-Key"]
            # Prove the dispatch is committed and visible from another connection before HTTP.
            conn = self.connect()
            try:
                row = conn.execute("SELECT * FROM checkout_intents WHERE request_key=?", (key,)).fetchone()
                self.assertEqual(row["phase"], "DISPATCHED")
                self.assertIsNotNone(row["confirmed_at"])
                self.assertEqual(body, json.loads(row["payload"]) | {"return_channel": "TELEGRAM"})
            finally:
                conn.close()
            self.posts.append((key, body))
            if self.post_mode in {"reject", "lost-reject"}:
                self.current = wire("competing-order-123")
                if self.post_mode == "lost-reject":
                    request.transport.close()
                return web.json_response({"code": "CHECKOUT_ADMISSION_REQUIRED"}, status=409)
            self.current = wire("order-fixture-"+str(len(self.posts)))
            if body.get("access_id"):
                self.current["terms"]["purchaseKind"] = "RENEWAL"
            self.originals[key] = self.current
            if self.post_mode == "lost":
                request.transport.close()
            return web.json_response({"order_id": self.current["orderId"], "checkout_url": self.current["checkoutUrl"], "status": "pending"})
        return web.json_response({"code": "NOT_FOUND"}, status=404)

    async def prepare(self, callback="callback-original-123", **kwargs):
        return (await self.runner.prepare(123, callback, TARIFF["tariff_id"], **kwargs))["operation"]

    async def test_explicit_confirmation_sends_persisted_original_terms(self):
        row = await self.prepare()
        self.assertEqual(row["phase"], "PREPARED")
        self.assertEqual(self.posts, [])
        self.catalog[0]["price_rub"] = 999
        result = await self.runner.confirm(123, row["id"])
        self.assertEqual(result["current"]["payment_status"], "PENDING")
        self.assertEqual(self.posts[0][1]["recurring_consent"]["amountRub"], 299)
        self.assertEqual(self.posts[0][1]["provider"], "YOOKASSA")

    async def test_lost_http_response_and_restart_never_resend(self):
        row = await self.prepare()
        self.post_mode = "lost"
        first = await self.runner.confirm(123, row["id"])
        restarted = CheckoutCoordinator(self.client, CheckoutJournal(self.connect))
        second = await restarted.confirm(123, row["id"])
        self.assertEqual(first["original"], second["original"])
        self.assertEqual(len(self.posts), 1)

    async def test_concurrent_confirmations_send_one_post(self):
        row = await self.prepare()
        other = CheckoutCoordinator(self.client, CheckoutJournal(self.connect))
        await asyncio.gather(self.runner.confirm(123, row["id"]), other.confirm(123, row["id"]))
        self.assertEqual(len(self.posts), 1)

    async def test_independent_connections_claim_once(self):
        row = await self.prepare()
        scope = connection_scope(self.client)
        def claim(_):
            return CheckoutJournal(self.connect).claim_confirmed(row["id"], 123, scope, OWNER)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(claim, range(8)))
        self.assertEqual(sum(outcomes), 1)
        # Crash after claim and before POST is unresolved even with an empty server.
        result = await self.runner.confirm(123, row["id"])
        self.assertTrue(result["unresolved"])
        self.assertEqual(self.posts, [])

    async def test_commit_failure_cannot_dispatch(self):
        row = await self.prepare()
        with patch.object(self.journal, "claim_confirmed", side_effect=sqlite3.OperationalError("fixture commit failed")):
            with self.assertRaises(sqlite3.OperationalError):
                await self.runner.confirm(123, row["id"])
        self.assertEqual(self.posts, [])

    async def test_concurrent_selection_and_changed_tariff_attach_original(self):
        rows = await asyncio.gather(self.prepare("callback-first-123"), self.prepare("callback-second-123"))
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        original = await self.runner.prepare(123, "callback-third-123", "different-tariff-123")
        self.assertEqual(original["operation"]["id"], rows[0]["id"])

    async def test_callback_tombstone_survives_cancel_and_new_selection(self):
        old = await self.prepare()
        await self.runner.cancel(123, old["id"])
        new = await self.prepare("callback-next-123")
        self.assertNotEqual(old["id"], new["id"])
        self.assertEqual((await self.prepare())["id"], old["id"])
        await self.runner.confirm(123, old["id"])
        self.assertEqual(self.posts, [])

    async def test_attach_after_terminal_race_never_allocates(self):
        old = await self.prepare()
        await self.runner.cancel(123, old["id"])
        attached = self.journal.attach("callback-racing-123", old["id"], 123, connection_scope(self.client), OWNER)
        self.assertEqual(attached["id"], old["id"])
        self.assertEqual(attached["phase"], "CANCELLED")

    async def test_other_device_discovery_allocates_nothing(self):
        self.current = wire()
        result = await self.runner.prepare(123, "callback-discovery-123", TARIFF["tariff_id"])
        self.assertIsNone(result["operation"])
        self.assertEqual(result["current"]["order_id"], self.current["orderId"])
        self.assertIsNone(self.journal.active(123, connection_scope(self.client), OWNER))

    async def test_terminal_predecessor_requires_explicit_new_action(self):
        first = await self.prepare()
        await self.runner.confirm(123, first["id"])
        self.current.update(paymentStatus="PAID", checkoutUrl=None)
        await self.runner.recover(123, first["id"])
        discovery = await self.runner.prepare(123, "callback-next-123", TARIFF["tariff_id"])
        self.assertIsNone(discovery["operation"])
        second = await self.prepare("callback-explicit-123", previous=self.current["orderId"])
        await self.runner.confirm(123, second["id"])
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.posts[1][1]["expected_previous_order_id"], "order-fixture-1")
        self.assertEqual((await self.prepare())["id"], first["id"])

    async def test_other_device_advancing_predecessor_prevents_post(self):
        self.current = wire(status="PAID")
        row = await self.prepare(previous=self.current["orderId"])
        self.current = wire("another-order-123")
        result = await self.runner.confirm(123, row["id"])
        self.assertTrue(result["unresolved"])
        self.assertEqual(self.posts, [])

    async def test_discovery_outage_never_allocates(self):
        self.discovery_status = 503
        with self.assertRaises(InternalApiError):
            await self.prepare()
        self.assertIsNone(self.journal.active(123, connection_scope(self.client), OWNER))

    async def test_owner_or_credentials_change_cannot_adopt_intent(self):
        row = await self.prepare()
        self.owner = "changed-user-123"
        with self.assertRaises(JournalConflict):
            await self.runner.confirm(123, row["id"])
        with self.assertRaises(JournalConflict):
            await self.prepare("callback-changed-123")
        self.owner = OWNER
        self.client.token = "rotated-fixture"
        with patch.object(self.runner, "context", return_value=(OWNER, connection_scope(self.client), {})):
            with self.assertRaises(JournalConflict):
                await self.runner.recover(123, row["id"])
        self.assertEqual(self.posts, [])

    async def test_renewal_target_rechecked_before_dispatch(self):
        self.accesses = [{"access_id": "access-fixture-123"}]
        row = await self.prepare(access_id="access-fixture-123")
        self.accesses = []
        with self.assertRaises(JournalConflict):
            await self.runner.confirm(123, row["id"])
        self.assertEqual(self.posts, [])

    async def test_definite_rejection_retained_through_outage_then_resolved(self):
        row = await self.prepare()
        self.post_mode = "reject"
        original_request = self.client._request
        async def call(*args, **kwargs):
            result = await original_request(*args, **kwargs)
            return result
        # Switch discovery to outage only after a received rejection.
        async def rejected(*args, **kwargs):
            try:
                return await call(*args, **kwargs)
            except InternalApiError as error:
                if error.code == "CHECKOUT_ADMISSION_REQUIRED":
                    self.discovery_status = 503
                raise
        with patch.object(self.client, "_request", side_effect=rejected):
            with self.assertRaises(InternalApiError):
                await self.runner.confirm(123, row["id"])
        self.assertEqual(self.journal.owned(row["id"], 123, connection_scope(self.client), OWNER)["phase"], "REJECTED")
        self.discovery_status = 200
        result = await CheckoutCoordinator(self.client, CheckoutJournal(self.connect)).recover(123, row["id"])
        self.assertEqual(result["operation"]["payment_status"], "NOT_ADMITTED")
        self.assertFalse(result["unresolved"])
        self.assertEqual(len(self.posts), 1)

    async def test_lost_rejection_never_clears_unknown_original(self):
        row = await self.prepare()
        self.post_mode = "lost-reject"
        result = await self.runner.confirm(123, row["id"])
        self.assertTrue(result["unresolved"])
        self.current.update(paymentStatus="PAID", checkoutUrl=None)
        again = await self.prepare("callback-again-123", previous=self.current["orderId"])
        self.assertEqual(again["id"], row["id"])
        await self.runner.confirm(123, again["id"])
        self.assertEqual(len(self.posts), 1)

    async def test_cancel_after_dispatch_cannot_release_original(self):
        row = await self.prepare()
        await self.runner.confirm(123, row["id"])
        cancelled = await self.runner.cancel(123, row["id"])
        self.assertEqual(cancelled["phase"], "DISPATCHED")
        self.assertEqual((await self.prepare("callback-again-123"))["id"], row["id"])

    async def test_wrong_original_terms_cannot_mark_terminal(self):
        row = await self.prepare()
        await self.runner.confirm(123, row["id"])
        self.current.update(paymentStatus="PAID", checkoutUrl=None)
        self.current["terms"]["amountRub"] = 1
        with self.assertRaises(JournalConflict):
            await self.runner.recover(123, row["id"])
        self.assertEqual(self.journal.active(123, connection_scope(self.client), OWNER)["id"], row["id"])

    async def test_snapshot_and_journal_exclude_upstream_credentials(self):
        self.current = wire()
        self.current.update(subscriptionUrl="fixture-private-vpn", providerMethodId="fixture-method", token="fixture-token")
        parsed = await self.client.get_current_checkout(OWNER)
        self.assertNotIn("fixture-private", json.dumps(parsed))
        self.current = None
        row = await self.prepare()
        await self.runner.confirm(123, row["id"])
        conn = self.connect()
        try:
            serialized = "\n".join(conn.iterdump())
        finally:
            conn.close()
        self.assertNotIn("https://", serialized)
        self.assertNotIn("fixture-only", serialized)
        self.assertNotIn("checkout_url", serialized)

    async def test_invalid_input_cannot_start_http(self):
        for user in ("../escape", "user?wrong=123", "x"*129):
            with self.assertRaises(InternalApiError):
                await self.client.get_current_checkout(user)
        self.assertEqual(self.requests, [])

    async def test_schema_migration_is_additive_and_repeatable(self):
        row = await self.prepare()
        from database.migrations import migration_46
        conn = self.connect()
        try:
            migration_46(conn)
            migration_46(conn)
            self.assertEqual(conn.execute("SELECT id FROM checkout_intents").fetchone()[0], row["id"])
        finally:
            conn.close()


class SnapshotTests(unittest.TestCase):
    def test_malformed_snapshots_fail_closed(self):
        changes = [{"version": True}, {"allowNewCreate": True}, {"paymentStatus": "UNKNOWN"},
                   {"checkoutUrl": "https://user:secret@checkout.invalid"}, {"checkoutUrl": "https://"},
                   {"checkoutUrl": "https://checkout.invalid\\evil"}, {"checkoutUrl": "https://checkout.invalid/\nsecret"},
                   {"checkoutUrl": "http://checkout.invalid"}, {"checkoutUrl": "https://checkout.invalid:bad"},
                   {"access": {"configurationReady": 1}}, {"terms": {}}, {"orderId": "bad"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises((CheckoutContractError, TypeError)):
                snapshot(wire() | change)
        with self.assertRaises(CheckoutContractError):
            snapshot({"version": 1, "current": None, "allowNewCreate": False, "orderId": "order-fixture-123"}, current=True)


if __name__ == "__main__":
    unittest.main()
