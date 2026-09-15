"""Canonical adapter bindings; no panel identity, credentials or URLs in this table."""
from datetime import datetime, timezone
import re

from database.admin_provisioning import Journal, JournalConflict
from database.connection import get_connection


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS saas_access_projections (
        tenant_id TEXT NOT NULL, access_id TEXT NOT NULL, node_id TEXT NOT NULL,
        saas_user_id TEXT NOT NULL, user_id INTEGER NOT NULL, telegram_id INTEGER NOT NULL,
        key_id INTEGER NOT NULL UNIQUE, desired_version INTEGER NOT NULL,
        PRIMARY KEY(tenant_id,access_id)
    )""")


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise JournalConflict("INVALID_SAAS_IDENTITY")
    return value


def apply_ready(conn, *, tenant_id, saas_user_id, user_id, telegram_id, material,
                expires_at, traffic_limit, tariff_id, key_id=None, traffic_used=0):
    if (any(type(v) is not int or v < 1 for v in (user_id, telegram_id, tariff_id))
            or (key_id is not None and (type(key_id) is not int or key_id < 1))
            or any(type(v) is not int or not 0 <= v <= 2**63-1 for v in (traffic_limit, traffic_used))):
        raise JournalConflict("INVALID_SAAS_PROJECTION")
    access_id, node_id = identity(material["access_id"]), identity(material["node_id"])
    identity(tenant_id)
    identity(saas_user_id)
    version = material["desired_version"]
    if (material.get("ready") is not True or type(version) is not int or version < 1
            or material.get("protocol") != "vless" or type(material.get("primary_inbound_id")) is not int
            or material["primary_inbound_id"] < 1
            or any(not isinstance(material.get(k), str) or not material[k] for k in ("panel_email","client_uuid","sub_id"))):
        raise JournalConflict("INVALID_READY_MATERIAL")
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        raise JournalConflict("INVALID_READY_EXPIRY")
    owner = conn.execute("SELECT telegram_id,is_banned,is_bot_blocked FROM users WHERE id=?", (user_id,)).fetchone()
    if not owner or owner["telegram_id"] != telegram_id or owner["is_banned"] or owner["is_bot_blocked"]:
        raise JournalConflict("LOCAL_OWNER_INVALID")
    binding = conn.execute("SELECT * FROM saas_access_projections WHERE tenant_id=? AND access_id=?",
                           (tenant_id,access_id)).fetchone()
    if binding:
        if (binding["node_id"] != node_id or binding["saas_user_id"] != saas_user_id
                or binding["user_id"] != user_id or binding["telegram_id"] != telegram_id
                or (key_id is not None and binding["key_id"] != key_id)):
            raise JournalConflict("SAAS_PROJECTION_BINDING_CHANGED")
        if version < binding["desired_version"]:
            raise JournalConflict("STALE_SAAS_MATERIAL")
        key_id = binding["key_id"]
    key = conn.execute("SELECT * FROM vpn_keys WHERE id=?", (key_id,)).fetchone() if key_id else None
    if key_id and (not key or key["user_id"] != user_id):
        raise JournalConflict("LOCAL_PROJECTION_REMOVED")
    if key:
        other = conn.execute("SELECT tenant_id,access_id FROM saas_access_projections WHERE key_id=?", (key_id,)).fetchone()
        if other and (other["tenant_id"] != tenant_id or other["access_id"] != access_id):
            raise JournalConflict("LOCAL_PROJECTION_ALREADY_BOUND")
        # Adoption requires exact current credentials; rotation requires a higher
        # authenticated desired version on the same canonical access and Node.
        if not binding or version == binding["desired_version"]:
            for field in ("panel_email","client_uuid","sub_id"):
                if key[field] and key[field] != material[field]:
                    raise JournalConflict("LOCAL_MATERIAL_CHANGED")
    expiry_db = expiry.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if key and binding and version == binding["desired_version"]:
        if (key["expires_at"] != expiry_db or key["traffic_limit"] != traffic_limit
                or key["panel_inbound_id"] != material["primary_inbound_id"]):
            raise JournalConflict("SAME_VERSION_MATERIAL_CHANGED")
    outcome = "existing" if key else "created"
    if key and (key["tariff_id"] != tariff_id or key["expires_at"] != expiry_db or key["traffic_limit"] != traffic_limit):
        outcome = "renewed"
    if not key:
        key_id = conn.execute("""INSERT INTO vpn_keys(user_id,tariff_id,expires_at,traffic_limit,saas_managed)
            VALUES (?,?,?,?,1)""", (user_id,tariff_id,expiry_db,traffic_limit)).lastrowid
    # Credential rotation is not authorization for a quota reset. Until SaaS
    # exposes an explicit quota-period/reset contract, retain the high-water mark.
    if key:
        traffic_used = max(traffic_used, key["traffic_used"] or 0)
    conn.execute("""UPDATE vpn_keys SET saas_managed=1,panel_inbound_id=?,panel_email=?,client_uuid=?,sub_id=?,
        tariff_id=?,expires_at=?,traffic_limit=?,traffic_used=? WHERE id=?""",
        (material["primary_inbound_id"],material["panel_email"],material["client_uuid"],material["sub_id"],
         tariff_id,expiry_db,traffic_limit,traffic_used,key_id))
    conn.execute("""INSERT INTO saas_access_projections
        (tenant_id,access_id,node_id,saas_user_id,user_id,telegram_id,key_id,desired_version)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,access_id) DO UPDATE SET desired_version=excluded.desired_version""",
        (tenant_id,access_id,node_id,saas_user_id,user_id,telegram_id,key_id,version))
    return key_id, outcome


def project_ready(*, connect=get_connection, **values):
    with Journal(connect).transaction() as conn:
        return apply_ready(conn, **values)


def get_binding(key_id, *, connect=get_connection):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM saas_access_projections WHERE key_id=?", (key_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
