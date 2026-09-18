"""Durable adapter intents. SaaS remains the owner of entitlements and runtime IDs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from uuid import uuid4

from database.connection import get_connection


class JournalConflict(RuntimeError):
    """Only bounded codes may escape this module."""


def ensure_schema(conn):
    # Deliberately no cascading FK: deleting a projection must not erase intent.
    conn.execute("""CREATE TABLE IF NOT EXISTS admin_provisioning (
        id TEXT PRIMARY KEY, callback_key TEXT NOT NULL UNIQUE,
        scope TEXT NOT NULL, admin_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        telegram_id INTEGER NOT NULL, key_id INTEGER NOT NULL UNIQUE,
        request_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
        user_payload TEXT NOT NULL, shadow_payload TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'PREPARED', status TEXT NOT NULL DEFAULT 'PENDING',
        access_id TEXT, command_id TEXT, node_id TEXT, expires_at TEXT, saas_user_id TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
        lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS admin_provisioning_unresolved_user
        ON admin_provisioning(user_id) WHERE status <> 'DONE'""")


def connection_scope(client):
    # Conservative credential fingerprint, NOT a claimed ServiceClient ID. Rotation
    # requires explicit reconciliation; a replacement credential cannot adopt work.
    value = json.dumps([client.base_url, client.tenant_id, client.token])
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Journal:
    def __init__(self, connect=get_connection, clock=time.time):
        self.connect, self.clock = connect, clock

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, operation_id):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM admin_provisioning WHERE id=?", (operation_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def for_callback(self, callback_key, admin_id, scope):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM admin_provisioning WHERE callback_key=?", (callback_key,)).fetchone()
            if row and (row["admin_id"] != admin_id or row["scope"] != scope):
                raise JournalConflict("OPERATION_SCOPE_CHANGED")
            return dict(row) if row else None
        finally:
            conn.close()

    def prepare(self, *, callback_key, admin_id, scope, user_id, telegram_id,
                tariff_id, days, traffic_limit, device_limit, requested_node_id=None):
        if (not all(type(v) is int and v > 0 for v in (admin_id, user_id, telegram_id, tariff_id))
                or type(days) is not int or not 1 <= days <= 99999
                or type(traffic_limit) is not int or not 0 <= traffic_limit <= 2**53-1
                or type(device_limit) is not int or not 1 <= device_limit <= 100):
            raise JournalConflict("INVALID_GRANT")
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM admin_provisioning WHERE callback_key=? OR (user_id=? AND status<>'DONE')",
                               (callback_key, user_id)).fetchone()
            if row:
                if row["scope"] != scope or row["admin_id"] != admin_id or row["user_id"] != user_id:
                    raise JournalConflict("UNRESOLVED_OPERATION_EXISTS")
                return dict(row)
            user = conn.execute("SELECT telegram_id,username,first_name,last_name,is_bot_blocked,is_banned FROM users WHERE id=?",
                                (user_id,)).fetchone()
            if not user or user["telegram_id"] != telegram_id or user["is_bot_blocked"] or user["is_banned"]:
                raise JournalConflict("LOCAL_OWNER_INVALID")
            now = self.clock()
            expires = (datetime.fromtimestamp(now, timezone.utc) + timedelta(days=days)).replace(microsecond=0)
            expiry_db = expires.strftime("%Y-%m-%d %H:%M:%S")
            key_id = conn.execute("""INSERT INTO vpn_keys(user_id,tariff_id,expires_at,traffic_limit)
                VALUES (?,?,?,?)""", (user_id, tariff_id, expiry_db, traffic_limit)).lastrowid
            operation_id = uuid4().hex
            payload = dict(telegram_id=telegram_id, legacy_key_id=key_id, duration_days=days,
                           traffic_limit_bytes=traffic_limit, device_limit=device_limit)
            if requested_node_id is not None:
                from database.saas_access_projection import identity
                payload["requested_node_id"] = identity(requested_node_id)
            user_payload = dict(telegram_id=telegram_id, username=user["username"],
                                display_name=" ".join(v for v in (user["first_name"], user["last_name"]) if v) or None,
                                is_bot_blocked=False)
            shadow = dict(telegram_id=str(telegram_id), legacy_key_id=str(key_id),
                          expires_at=expires.isoformat(), enabled=True, configured=False,
                          subscription_ready=False, device_limit=device_limit,
                          traffic_limit_bytes=str(traffic_limit), traffic_used_bytes="0")
            conn.execute("""INSERT INTO admin_provisioning
                (id,callback_key,scope,admin_id,user_id,telegram_id,key_id,request_key,
                 payload,user_payload,shadow_payload,created_at,updated_at,node_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, callback_key, scope, admin_id, user_id, telegram_id, key_id,
                 "admin-grant-" + operation_id, _json(payload), _json(user_payload), _json(shadow), now, now, requested_node_id))
            return dict(conn.execute("SELECT * FROM admin_provisioning WHERE id=?", (operation_id,)).fetchone())

    def due(self, limit=20):
        conn = self.connect()
        try:
            return [r[0] for r in conn.execute("""SELECT id FROM admin_provisioning
                WHERE status='PENDING' AND next_attempt<=? AND lease_until<=?
                ORDER BY updated_at LIMIT ?""", (self.clock(), self.clock(), limit))]
        finally:
            conn.close()

    def claim(self, operation_id, *, explicit=False):
        now, token = self.clock(), uuid4().hex
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM admin_provisioning WHERE id=?", (operation_id,)).fetchone()
            if not row or row["status"] == "DONE" or row["lease_until"] > now:
                return None
            if not explicit and (row["status"] != "PENDING" or row["next_attempt"] > now):
                return None
            conn.execute("""UPDATE admin_provisioning SET lease_token=?, lease_until=?,
                attempts=attempts+1 WHERE id=?""", (token, now + 120, operation_id))
            row = dict(row)
            row.update(lease_token=token, lease_until=now+120)
            return row

    def _owned(self, conn, row):
        current = conn.execute("SELECT * FROM admin_provisioning WHERE id=?", (row["id"],)).fetchone()
        if not current or current["lease_token"] != row["lease_token"] or current["lease_until"] <= self.clock():
            raise JournalConflict("LEASE_LOST")
        return current

    def advance(self, row, phase, **bindings):
        if not set(bindings) <= {"access_id", "command_id", "node_id", "expires_at", "saas_user_id"}:
            raise JournalConflict("INVALID_BINDING")
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if current["phase"] != row["phase"]:
                raise JournalConflict("PHASE_CHANGED")
            for key, value in bindings.items():
                if current[key] is not None and current[key] != value:
                    raise JournalConflict("BINDING_CHANGED")
            assignments = ",".join(f"{key}=?" for key in bindings)
            conn.execute(f"""UPDATE admin_provisioning SET phase=?,updated_at=?,last_error=NULL
                {',' + assignments if assignments else ''} WHERE id=?""",
                (phase, self.clock(), *bindings.values(), row["id"]))
        row.update(phase=phase, **bindings)

    def release(self, row, *, status="PENDING", error=None):
        if status not in {"PENDING", "FAILED", "TIMEOUT", "MANUAL_REVIEW"}:
            raise JournalConflict("INVALID_STATUS")
        if error is not None and (not error.isascii() or not error.replace("_", "").isalnum() or len(error)>64):
            raise JournalConflict("INVALID_ERROR_CODE")
        with self.transaction() as conn:
            self._owned(conn, row)
            conn.execute("""UPDATE admin_provisioning SET status=?,last_error=?,updated_at=?,
                lease_token=NULL,lease_until=0,next_attempt=? WHERE id=?""",
                (status, error, self.clock(), self.clock()+15, row["id"]))

    def owner_exists(self, row):
        conn = self.connect()
        try:
            return conn.execute("""SELECT 1 FROM vpn_keys k JOIN users u ON u.id=k.user_id
                WHERE k.id=? AND k.user_id=? AND u.telegram_id=? AND COALESCE(u.is_bot_blocked,0)=0
                AND COALESCE(u.is_banned,0)=0""",
                (row["key_id"], row["user_id"], row["telegram_id"])).fetchone() is not None
        finally:
            conn.close()

    def finalize(self, row, material, tenant_id):
        from database.saas_access_projection import apply_ready
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if (current["phase"] != "OBSERVED" or material["access_id"] != current["access_id"]
                    or material.get("node_id") != current["node_id"]):
                raise JournalConflict("MATERIAL_BINDING_CHANGED")
            key = conn.execute("SELECT tariff_id FROM vpn_keys WHERE id=?", (row["key_id"],)).fetchone()
            if not key:
                raise JournalConflict("LOCAL_OWNER_REMOVED")
            apply_ready(conn, tenant_id=tenant_id, saas_user_id=current["saas_user_id"],
                user_id=current["user_id"], telegram_id=current["telegram_id"], key_id=current["key_id"],
                material=material, expires_at=current["expires_at"], tariff_id=key["tariff_id"],
                traffic_limit=json.loads(current["payload"])["traffic_limit_bytes"])
            conn.execute("""UPDATE admin_provisioning SET phase='DONE',status='DONE',last_error=NULL,
                updated_at=?,lease_token=NULL,lease_until=0 WHERE id=?""", (self.clock(), row["id"]))
