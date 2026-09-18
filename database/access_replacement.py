"""Durable adapter actions; only SaaS decides whether a credential can change."""
from uuid import uuid4

from database.admin_provisioning import Journal, JournalConflict
from database.saas_access_projection import apply_ready, identity


def ensure_schema(conn):
    # Tombstones and callback aliases survive deletion of a displayed key.
    conn.execute("""CREATE TABLE IF NOT EXISTS access_replacements (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, tenant_id TEXT NOT NULL,
        access_id TEXT NOT NULL, node_id TEXT NOT NULL, saas_user_id TEXT NOT NULL,
        user_id INTEGER NOT NULL, telegram_id INTEGER NOT NULL, key_id INTEGER NOT NULL,
        expected_version INTEGER NOT NULL, request_key TEXT NOT NULL UNIQUE,
        phase TEXT NOT NULL DEFAULT 'PREPARED', status TEXT NOT NULL DEFAULT 'CONFIRMATION',
        command_id TEXT, request_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        confirmed_at REAL, lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS access_replacement_unresolved
        ON access_replacements(tenant_id,access_id) WHERE phase NOT IN ('DONE','CANCELLED')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS access_replacement_callbacks (
        callback_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL
    )""")


class ReplacementJournal(Journal):
    def get(self, operation_id):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM access_replacements WHERE id=?", (operation_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _actor(row, telegram_id, scope):
        if not row or type(telegram_id) is not int or row["telegram_id"] != telegram_id or row["scope"] != scope:
            raise JournalConflict("REPLACEMENT_OWNER_CHANGED")
        return dict(row)

    def owned(self, operation_id, telegram_id, scope):
        return self._actor(self.get(operation_id), telegram_id, scope)

    def for_callback(self, callback_key, telegram_id, scope):
        conn = self.connect()
        try:
            row = conn.execute("""SELECT r.* FROM access_replacements r JOIN access_replacement_callbacks c
                ON c.operation_id=r.id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            return self._actor(row, telegram_id, scope) if row else None
        finally:
            conn.close()

    @staticmethod
    def _canonical(conn, row, versions):
        binding = conn.execute("SELECT * FROM saas_access_projections WHERE key_id=?", (row["key_id"],)).fetchone()
        key = conn.execute("""SELECT k.*,u.telegram_id,u.is_banned,u.is_bot_blocked FROM vpn_keys k
            JOIN users u ON u.id=k.user_id WHERE k.id=?""", (row["key_id"],)).fetchone()
        fields = ("tenant_id", "access_id", "node_id", "saas_user_id", "user_id", "telegram_id", "key_id")
        if (not key or not binding or any(binding[f] != row[f] for f in fields)
                or key["user_id"] != row["user_id"] or key["telegram_id"] != row["telegram_id"]
                or key["is_banned"] or key["is_bot_blocked"] or not key["saas_managed"]):
            raise JournalConflict("REPLACEMENT_BINDING_CHANGED")
        if binding["desired_version"] not in versions:
            raise JournalConflict("REPLACEMENT_VERSION_CHANGED")
        return dict(key)

    def binding(self, key_id, telegram_id, tenant_id):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM saas_access_projections WHERE key_id=?", (key_id,)).fetchone()
            if not row or row["telegram_id"] != telegram_id or row["tenant_id"] != tenant_id:
                raise JournalConflict("REPLACEMENT_BINDING_MISSING")
            self._canonical(conn, row, {row["desired_version"]})
            return dict(row)
        finally:
            conn.close()

    def attach_active(self, callback_key, binding, scope):
        with self.transaction() as conn:
            existing = conn.execute("""SELECT r.* FROM access_replacements r JOIN access_replacement_callbacks c
                ON c.operation_id=r.id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            if existing:
                return self._actor(existing, binding["telegram_id"], scope)
            existing = conn.execute("""SELECT * FROM access_replacements WHERE tenant_id=? AND access_id=?
                AND phase NOT IN ('DONE','CANCELLED')""", (binding["tenant_id"], binding["access_id"])).fetchone()
            if not existing:
                return None
            row = self._actor(existing, binding["telegram_id"], scope)
            if any(row[f] != binding[f] for f in ("key_id", "user_id", "node_id", "saas_user_id")):
                raise JournalConflict("REPLACEMENT_BINDING_CHANGED")
            conn.execute("INSERT INTO access_replacement_callbacks VALUES (?,?)", (callback_key, row["id"]))
            return row

    def prepare(self, *, callback_key, scope, binding, expected_version, previous_id=None):
        if type(expected_version) is not int or not 1 <= expected_version <= 2_147_483_646:
            raise JournalConflict("INVALID_REPLACEMENT_VERSION")
        for field in ("tenant_id", "access_id", "node_id", "saas_user_id"):
            identity(binding[field])
        with self.transaction() as conn:
            existing = conn.execute("""SELECT r.* FROM access_replacements r JOIN access_replacement_callbacks c
                ON c.operation_id=r.id WHERE c.callback_key=?""", (callback_key,)).fetchone()
            if existing:
                return self._actor(existing, binding["telegram_id"], scope)
            if previous_id:
                previous = conn.execute("SELECT * FROM access_replacements WHERE id=?", (previous_id,)).fetchone()
                self._actor(previous, binding["telegram_id"], scope)
                if (previous["phase"] not in {"DONE", "CANCELLED"} or previous["access_id"] != binding["access_id"]
                        or previous["key_id"] != binding["key_id"]):
                    raise JournalConflict("REPLACEMENT_UNRESOLVED")
            self._canonical(conn, binding, {expected_version})
            existing = conn.execute("""SELECT * FROM access_replacements WHERE tenant_id=? AND access_id=?
                AND phase NOT IN ('DONE','CANCELLED')""", (binding["tenant_id"], binding["access_id"])).fetchone()
            if existing:
                row = self._actor(existing, binding["telegram_id"], scope)
            else:
                operation_id = uuid4().hex
                now = self.clock()
                conn.execute("""INSERT INTO access_replacements
                    (id,scope,tenant_id,access_id,node_id,saas_user_id,user_id,telegram_id,key_id,
                     expected_version,request_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (operation_id, scope, binding["tenant_id"], binding["access_id"], binding["node_id"],
                     binding["saas_user_id"], binding["user_id"], binding["telegram_id"], binding["key_id"],
                     expected_version, "replace-"+operation_id, now, now))
                row = dict(conn.execute("SELECT * FROM access_replacements WHERE id=?", (operation_id,)).fetchone())
            # Also bind messages opened during a pending operation, so replay after DONE stays original.
            conn.execute("INSERT INTO access_replacement_callbacks VALUES (?,?)", (callback_key, row["id"]))
            return row

    def confirm(self, operation_id, telegram_id, scope):
        with self.transaction() as conn:
            row = self._actor(conn.execute("SELECT * FROM access_replacements WHERE id=?", (operation_id,)).fetchone(), telegram_id, scope)
            if row["phase"] == "PREPARED":
                self._canonical(conn, row, {row["expected_version"]})
                if self.clock() - row["created_at"] > 600:
                    conn.execute("UPDATE access_replacements SET phase='CANCELLED',status='STALE',updated_at=? WHERE id=?",
                                 (self.clock(), operation_id))
                else:
                    conn.execute("""UPDATE access_replacements SET phase='QUEUED',status='PENDING',confirmed_at=?,updated_at=?
                        WHERE id=?""", (self.clock(), self.clock(), operation_id))
        return self.owned(operation_id, telegram_id, scope)

    def cancel(self, operation_id, telegram_id, scope):
        with self.transaction() as conn:
            row = self._actor(conn.execute("SELECT * FROM access_replacements WHERE id=?", (operation_id,)).fetchone(), telegram_id, scope)
            if row["phase"] == "PREPARED":
                conn.execute("UPDATE access_replacements SET phase='CANCELLED',status='CANCELLED',updated_at=? WHERE id=?",
                             (self.clock(), operation_id))
        return self.owned(operation_id, telegram_id, scope)

    def due(self, limit=20):
        conn = self.connect()
        try:
            return [r[0] for r in conn.execute("""SELECT id FROM access_replacements
                WHERE phase IN ('QUEUED','DISPATCHED','OBSERVED') AND status IN ('PENDING','TIMEOUT')
                AND next_attempt<=? AND lease_until<=? ORDER BY updated_at LIMIT ?""", (self.clock(), self.clock(), limit))]
        finally:
            conn.close()

    def claim(self, operation_id, *, explicit=False):
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM access_replacements WHERE id=?", (operation_id,)).fetchone()
            if (not row or row["phase"] not in {"QUEUED", "DISPATCHED", "OBSERVED"} or row["lease_until"] > self.clock()
                    or (not explicit and (row["status"] not in {"PENDING", "TIMEOUT"} or row["next_attempt"] > self.clock()))):
                return None
            row = dict(row)
            row.update(lease_token=uuid4().hex, lease_until=self.clock()+120, attempts=row["attempts"]+1)
            conn.execute("UPDATE access_replacements SET lease_token=?,lease_until=?,attempts=? WHERE id=?",
                         (row["lease_token"], row["lease_until"], row["attempts"], operation_id))
            return row

    def _owned(self, conn, row):
        current = conn.execute("SELECT * FROM access_replacements WHERE id=?", (row["id"],)).fetchone()
        if (not current or current["lease_token"] != row["lease_token"] or current["lease_until"] <= self.clock()
                or current["phase"] != row["phase"]):
            raise JournalConflict("LEASE_LOST")
        return current

    def dispatch(self, row):
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if current["phase"] != "QUEUED":
                raise JournalConflict("REPLACEMENT_ALREADY_DISPATCHED")
            self._canonical(conn, current, {current["expected_version"]})
            conn.execute("UPDATE access_replacements SET phase='DISPATCHED',updated_at=? WHERE id=?", (self.clock(), row["id"]))
        row["phase"] = "DISPATCHED"

    def observe(self, row, result):
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if current["phase"] not in {"DISPATCHED", "OBSERVED"}:
                raise JournalConflict("REPLACEMENT_NOT_DISPATCHED")
            for field in ("command_id", "request_id"):
                identity(result[field])
                if current[field] is not None and current[field] != result[field]:
                    raise JournalConflict("REPLACEMENT_RESULT_CHANGED")
            if (result["access_id"] != current["access_id"] or result["assigned_entry_node_id"] != current["node_id"]
                    or result["desired_version"] != current["expected_version"]+1):
                raise JournalConflict("REPLACEMENT_RESULT_CHANGED")
            conn.execute("""UPDATE access_replacements SET phase='OBSERVED',command_id=?,request_id=?,updated_at=? WHERE id=?""",
                         (result["command_id"], result["request_id"], self.clock(), row["id"]))
        row.update(phase="OBSERVED", command_id=result["command_id"], request_id=result["request_id"])

    def note_request(self, row, request_id):
        identity(request_id)
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if current["request_id"] is not None and current["request_id"] != request_id:
                raise JournalConflict("REPLACEMENT_RESULT_CHANGED")
            conn.execute("UPDATE access_replacements SET request_id=? WHERE id=?", (request_id, row["id"]))
        row["request_id"] = request_id

    def note_command(self, row, command_id):
        identity(command_id)
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if current["command_id"] is not None and current["command_id"] != command_id:
                raise JournalConflict("REPLACEMENT_RESULT_CHANGED")
            conn.execute("UPDATE access_replacements SET command_id=? WHERE id=?", (command_id, row["id"]))
        row["command_id"] = command_id

    def release(self, row, *, status="PENDING", terminal=False):
        if status not in {"PENDING", "TIMEOUT", "MANUAL_REVIEW", "FAILED", "SUPERSEDED", "STALE"}:
            raise JournalConflict("INVALID_REPLACEMENT_STATUS")
        with self.transaction() as conn:
            current = self._owned(conn, row)
            phase = current["phase"]
            if terminal:
                if phase == "QUEUED" and status == "STALE":
                    phase = "CANCELLED"  # No dispatch was recorded or permitted yet.
                elif phase == "OBSERVED" and status in {"FAILED", "SUPERSEDED"}:
                    phase = "DONE"  # Worker must have observed a terminal original command.
                else:
                    raise JournalConflict("INVALID_REPLACEMENT_TERMINAL")
            delay = min(300, max(15, row["attempts"]*15))
            conn.execute("""UPDATE access_replacements SET phase=?,status=?,updated_at=?,next_attempt=?,lease_token=NULL,lease_until=0
                WHERE id=?""", (phase, status, self.clock(), self.clock()+delay, row["id"]))

    def finalize(self, row, access, material):
        with self.transaction() as conn:
            current = self._owned(conn, row)
            if (current["phase"] != "OBSERVED" or material["access_id"] != current["access_id"]
                    or material["node_id"] != current["node_id"] or type(material["desired_version"]) is not int
                    or material["desired_version"] != current["expected_version"]+1):
                raise JournalConflict("REPLACEMENT_MATERIAL_CHANGED")
            key = self._canonical(conn, current, {current["expected_version"], current["expected_version"]+1})
            apply_ready(conn, tenant_id=current["tenant_id"], saas_user_id=current["saas_user_id"],
                        user_id=current["user_id"], telegram_id=current["telegram_id"], key_id=current["key_id"],
                        tariff_id=key["tariff_id"], material=material, expires_at=access["expires_at"],
                        traffic_limit=int(access["traffic_limit_bytes"]), traffic_used=int(access.get("traffic_used_bytes") or 0))
            conn.execute("""UPDATE access_replacements SET phase='DONE',status='DONE',updated_at=?,lease_token=NULL,lease_until=0
                WHERE id=?""", (self.clock(), row["id"]))
