"""Durable Telegram intent and one-shot dispatch; SaaS owns commercial state."""
import json
from uuid import uuid4

from bot.services.checkout_contract import consent, identity, request_key
from database.admin_provisioning import Journal, JournalConflict


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS checkout_intents (
        id TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL, scope TEXT NOT NULL,
        saas_user_id TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
        name TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase IN
            ('PREPARED','DISPATCHED','REJECTED','TERMINAL','CANCELLED')),
        order_id TEXT, payment_status TEXT, created_at REAL NOT NULL, confirmed_at REAL
    )""")
    # Do not let changed credentials or relinking bypass an unresolved local intent.
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS checkout_intent_unresolved
        ON checkout_intents(telegram_id) WHERE phase NOT IN ('TERMINAL','CANCELLED')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS checkout_callbacks (
        callback_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES checkout_intents(id)
    )""")


class CheckoutJournal(Journal):
    @staticmethod
    def _owned(row, actor, scope, owner):
        if (not row or type(actor) is not int or row["telegram_id"] != actor
                or row["scope"] != scope or row["saas_user_id"] != owner):
            raise JournalConflict("CHECKOUT_OWNER_CHANGED")
        return dict(row)

    def owned(self, operation_id, actor, scope, owner):
        conn = self.connect()
        try:
            return self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
        finally:
            conn.close()

    def active(self, actor, scope, owner):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM checkout_intents WHERE telegram_id=? AND phase NOT IN ('TERMINAL','CANCELLED')", (actor,)).fetchone()
            return self._owned(row, actor, scope, owner) if row else None
        finally:
            conn.close()

    def for_callback(self, callback_key, actor, scope, owner):
        conn = self.connect()
        try:
            row = conn.execute("""SELECT i.* FROM checkout_intents i JOIN checkout_callbacks c
                ON i.id=c.operation_id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            return self._owned(row, actor, scope, owner) if row else None
        finally:
            conn.close()

    def prepare(self, *, callback_key, actor, scope, owner, tariff, access_id=None, previous=None):
        if type(actor) is not int or actor <= 0 or not isinstance(scope, str) or len(scope) != 64:
            raise JournalConflict("INVALID_CHECKOUT_ACTOR")
        request_key(callback_key)
        payload = {"user_id": identity(owner), "tariff_id": identity(tariff["tariff_id"]),
                   "billing_mode": "RECURRING", "provider": "YOOKASSA",
                   "recurring_consent": consent(tariff["recurring_consent"])}
        if access_id is not None:
            payload["access_id"] = identity(access_id)
        if previous is not None:
            payload["expected_previous_order_id"] = identity(previous)
        if not isinstance(tariff["name"], str) or not 1 <= len(tariff["name"]) <= 300:
            raise JournalConflict("INVALID_CHECKOUT_NAME")
        with self.transaction() as conn:
            row = conn.execute("""SELECT i.* FROM checkout_intents i JOIN checkout_callbacks c
                ON i.id=c.operation_id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            if row:
                return self._owned(row, actor, scope, owner)
            row = conn.execute("SELECT * FROM checkout_intents WHERE telegram_id=? AND phase NOT IN ('TERMINAL','CANCELLED')", (actor,)).fetchone()
            if row:
                result = self._owned(row, actor, scope, owner)
            else:
                operation_id = uuid4().hex
                conn.execute("""INSERT INTO checkout_intents
                    (id,telegram_id,scope,saas_user_id,request_key,payload,name,phase,created_at)
                    VALUES (?,?,?,?,?,?,?,'PREPARED',?)""", (operation_id, actor, scope, owner,
                    "checkout-"+operation_id, json.dumps(payload, sort_keys=True), tariff["name"], self.clock()))
                result = dict(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone())
            conn.execute("INSERT INTO checkout_callbacks VALUES (?,?)", (callback_key, result["id"]))
            return result

    def attach(self, callback_key, operation_id, actor, scope, owner):
        request_key(callback_key)
        with self.transaction() as conn:
            row = conn.execute("""SELECT i.* FROM checkout_intents i JOIN checkout_callbacks c
                ON i.id=c.operation_id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            if row:
                return self._owned(row, actor, scope, owner)
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            # It may have finished since discovery; still bind this message to it.
            conn.execute("INSERT INTO checkout_callbacks VALUES (?,?)", (callback_key, operation_id))
            return row

    def claim_confirmed(self, operation_id, actor, scope, owner):
        with self.transaction() as conn:
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            if row["phase"] != "PREPARED":
                return False
            # No lease or time-based release: a crash after this commit is unknown.
            conn.execute("UPDATE checkout_intents SET phase='DISPATCHED',confirmed_at=? WHERE id=?", (self.clock(), operation_id))
            return True

    def cancel(self, operation_id, actor, scope, owner):
        with self.transaction() as conn:
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            if row["phase"] == "PREPARED":
                conn.execute("UPDATE checkout_intents SET phase='CANCELLED' WHERE id=?", (operation_id,))

    def rejected(self, operation_id, actor, scope, owner):
        with self.transaction() as conn:
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            if row["phase"] == "DISPATCHED":
                conn.execute("UPDATE checkout_intents SET phase='REJECTED' WHERE id=?", (operation_id,))

    def prove_rejected(self, operation_id, actor, scope, owner):
        # Call only after the original-key SaaS proof. Retain the row and all
        # callback aliases; a delayed callback can never allocate or dispatch again.
        with self.transaction() as conn:
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            if (row["order_id"] is not None or row["phase"] not in {"DISPATCHED", "REJECTED", "TERMINAL"}
                    or row["phase"] == "TERMINAL" and row["payment_status"] != "NOT_ADMITTED"):
                raise JournalConflict("CHECKOUT_REJECTION_CONTRADICTED")
            conn.execute("UPDATE checkout_intents SET phase='TERMINAL',payment_status='NOT_ADMITTED' WHERE id=?", (operation_id,))

    def observe(self, operation_id, actor, scope, owner, original):
        with self.transaction() as conn:
            row = self._owned(conn.execute("SELECT * FROM checkout_intents WHERE id=?", (operation_id,)).fetchone(), actor, scope, owner)
            if original is None:
                if row["order_id"] is not None:
                    raise JournalConflict("CHECKOUT_ORIGINAL_MISSING")
                return
            payload = json.loads(row["payload"])
            if (original["terms"]["tariff_id"] != payload["tariff_id"] or original["terms"]["recurring_consent"] != payload["recurring_consent"]
                    or original["purchase_kind"] != ("RENEWAL" if payload.get("access_id") else "NEW_ACCESS")
                    or row["order_id"] is not None and row["order_id"] != original["order_id"]
                    or row["phase"] in {"PREPARED", "CANCELLED"} or row["payment_status"] == "NOT_ADMITTED"):
                raise JournalConflict("CHECKOUT_ORIGINAL_CHANGED")
            if row["phase"] == "TERMINAL" and original["payment_status"] not in {"PAID", "CANCELLED", "REFUNDED"}:
                raise JournalConflict("CHECKOUT_STATUS_REGRESSED")
            phase = "TERMINAL" if original["payment_status"] in {"PAID", "CANCELLED", "REFUNDED"} else row["phase"]
            conn.execute("UPDATE checkout_intents SET phase=?,order_id=?,payment_status=? WHERE id=?",
                         (phase, identity(original["order_id"]), original["payment_status"], operation_id))
