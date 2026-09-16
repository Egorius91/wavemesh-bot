"""Immutable private UI references; never store checkout or VPN URLs."""
import json
from uuid import uuid4

from database.admin_provisioning import Journal, JournalConflict


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS checkout_ui (
        id TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL, scope TEXT NOT NULL,
        saas_user_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
    )""")


class CheckoutUIJournal(Journal):
    def create(self, actor, scope, owner, kind, payload):
        if kind not in {"STATUS", "CHOICE"} or set(payload) - {"operation_id", "order_id", "key_id", "tariff_id", "previous"}:
            raise JournalConflict("INVALID_CHECKOUT_UI")
        ref = uuid4().hex
        with self.transaction() as conn:
            conn.execute("INSERT INTO checkout_ui VALUES (?,?,?,?,?,?)", (ref, actor, scope, owner, kind, json.dumps(payload)))
        return ref

    def owned(self, ref, actor, scope, owner, kind):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM checkout_ui WHERE id=?", (ref,)).fetchone()
            if not row or row["telegram_id"] != actor or row["scope"] != scope or row["saas_user_id"] != owner or row["kind"] != kind:
                raise JournalConflict("CHECKOUT_UI_OWNER_CHANGED")
            return json.loads(row["payload"])
        finally:
            conn.close()
